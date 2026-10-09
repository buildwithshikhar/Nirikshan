"""Per-clip recoverability estimate: a fixed, documented rule over stored evidence (no learned
weights, nothing fitted to ground truth). Rule version RULE_VERSION; docs/recoverability.md.

    estimate = decode_factor * irap_factor * continuity_factor * header_factor

  decode_factor      stored decode test of the carved bitstream (ffmpeg -f null)
                       ok 1.0 | decode_errors 0.5 | export_failed 0.0 | not exported -> no estimate
                       (the stored test says THAT errors occurred, not how many frames failed, so
                       decode_errors gets the midpoint 0.5)
  irap_factor        1.0 if the clip contains at least one IRAP picture (IDR/CRA/BLA), else 0.0
                       (nothing decodes before the first IRAP)
  continuity_factor  1.0 for one contiguous NAL run; 0.5 if the clip was joined across a gap by
                       the fragment reassembler (a heuristic with a measured false-accept rate)
  header_factor      1.0 if parameter sets were syntax-checked by the carver or the decoder
                       accepted the stream; 0.75 otherwise

Bands: high >= 0.9, medium >= 0.5, low < 0.5. Orphans get 0.0 (no IRAP + parameter sets).
The factors were fixed before measurement and are not tuned (docs/recoverability.md reports the
measured agreement with ground truth on the reference images, good or bad).
"""

import json

RULE_VERSION = "1"
DECODE = {"ok": 1.0, "decode_errors": 0.5, "export_failed": 0.0}
REASSEMBLED = 0.5
HEADER_UNCHECKED = 0.75


def band(x: float) -> str:
    return "high" if x >= 0.9 else "medium" if x >= 0.5 else "low"


def features_from_row(clip, validate_params: bool | None) -> dict:
    return {
        "kind": clip.kind,
        "engine": clip.engine,
        "codec": clip.codec,
        "decode_status": clip.decode_status,
        "decode_errors": json.loads(clip.decode_errors_json or "[]"),
        "irap_count": clip.irap_count,
        "vcl_count": clip.vcl_count,
        "nal_count": clip.nal_count,
        "reassembled": bool(clip.reassembled),
        "extent_count": len(json.loads(clip.extents_json or "[]")),
        "end_reason": clip.reason,
        "validate_params": validate_params,
    }


def estimate(ft: dict) -> dict:
    if ft["kind"] == "orphan":
        return {
            "available": True,
            "rule_version": RULE_VERSION,
            "estimate": 0.0,
            "band": "low",
            "components": [],
            "explanation": "orphan range: NAL data without an IRAP picture and parameter sets; "
            "it cannot be decoded on its own",
        }
    ds = ft["decode_status"]
    if ds not in DECODE:
        return {
            "available": False,
            "rule_version": RULE_VERSION,
            "reason": f"no stored decode test (decode_status={ds}); the rule needs one",
        }
    comps = []

    def comp(name, factor, evidence, why):
        comps.append({"name": name, "factor": factor, "evidence": evidence, "why": why})

    comp(
        "decode_test",
        DECODE[ds],
        {"decode_status": ds, "error_lines": len(ft["decode_errors"])},
        {
            "ok": "the carved bitstream decoded without errors",
            "decode_errors": "the decoder reported errors; how many frames are affected is "
            "not recorded, so the midpoint 0.5 is used",
            "export_failed": "the clip could not be muxed or decoded",
        }[ds],
    )
    irap = ft["irap_count"] > 0
    comp(
        "irap_present",
        1.0 if irap else 0.0,
        {"irap_count": ft["irap_count"]},
        "contains at least one IRAP picture" if irap else "no IRAP picture: nothing decodes",
    )
    re = ft["reassembled"]
    comp(
        "nal_continuity",
        REASSEMBLED if re else 1.0,
        {"reassembled": re, "extent_count": ft["extent_count"], "end_reason": ft["end_reason"]},
        "joined across gaps by the fragment reassembler (heuristic)"
        if re
        else "one contiguous NAL run (payload extents of a vendor container count as one run)",
    )
    checked = (ft["engine"] == "generic" and ft["validate_params"]) or ds == "ok"
    comp(
        "header_validity",
        1.0 if checked else HEADER_UNCHECKED,
        {"engine": ft["engine"], "params_syntax_checked": ft["validate_params"]},
        "parameter sets syntax-checked by the carver or accepted by the decoder"
        if checked
        else "parameter sets not syntax-checked and the decoder reported problems",
    )
    est = 1.0
    for c in comps:
        est *= c["factor"]
    est = round(est, 4)
    return {
        "available": True,
        "rule_version": RULE_VERSION,
        "estimate": est,
        "band": band(est),
        "components": comps,
        "explanation": " x ".join(f"{c['name']} {c['factor']}" for c in comps) + f" = {est}",
    }


def limitations(ft: dict, fa_rate: float | None = None) -> list[str]:
    out = [
        "The estimate is a fixed rule over stored test results, not a measurement of this clip; "
        "its agreement with ground truth was measured only on reference test images "
        "(docs/recoverability.md).",
    ]
    if ft["kind"] == "orphan":
        return out + ["Orphan ranges are listed for completeness; they are not exported."]
    if ft["engine"] == "generic":
        out.append(
            "Generic carving: no vendor, channel or recording-time attribution; interleaved "
            "channels may be mixed in one clip."
        )
        out.append(
            "Random (non-zero) bytes between NAL units cannot be told apart from payload; they "
            "are absorbed and only the decode test can reveal the damage."
        )
    else:
        out.append(
            f"{ft['engine']} parser clip: the parser is built from published research and is "
            "unvalidated on real devices."
        )
    if ft["codec"] == "h265":
        out.append("H.265: no slice-continuity check is applied, so splices may go undetected.")
    if ft["reassembled"]:
        fa = f" (measured false-accept rate on reference data: {fa_rate:.1%})" if fa_rate else ""
        out.append("Joined across a gap by the fragment reassembler, a heuristic" + fa + ".")
    if ft["decode_status"] == "decode_errors":
        out.append("The decoder reported errors; some frames are damaged or missing.")
    if ft["irap_count"] == 0:
        out.append("No IRAP picture: the clip cannot be decoded from its start.")
    out.append(
        "Durations assume the stream's frame rate (25 fps when the stream has no timing); they "
        "are not wall-clock recording durations."
    )
    if ft["end_reason"]:
        out.append(f"Clip ended because: {ft['end_reason']}.")
    return out
