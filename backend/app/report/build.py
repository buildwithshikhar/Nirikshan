"""Assemble ReportData (a plain JSON-able dict) for one case from the database.

Nothing here is invented: every value is read from a table, from `custody.verify_chain` (re-run
now), from the timeline builder used by the UI, from the model cards / measured error rates that
ship with the code, or from docs/validation/results.json. Missing data is reported as missing.

`content_hash` is the SHA-256 of the canonical JSON of the data WITHOUT the `generated` block
(generation time and NTP status). Same database state + same code => same content_hash.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__, custody, signing
from app.analytics import TRIAGE_LABEL
from app.analytics.models import AnalyticsRun, Detection, MotionInterval
from app.carving.export import ffmpeg_version
from app.clock import ntp_status as current_ntp_status
from app.clock import utc_now_iso
from app.models import CarveRun, Case, Clip, CustodyEntry, Evidence
from app.timeline.models import ReferenceObservation
from app.timeline.timestamps import FLAG_HELP, VENDOR_CONFLICTS
from app.vendors.base import TIERS

REPORT_FORMAT = "1"
DISCLAIMER_CLOCK = (
    "The UTC generation time (with the NTP status observed at that moment) is the ONLY content "
    "that depends on when the report is generated. Everything else is derived from the database "
    "state shown here, the code version and the installed tool versions."
)
NOMINAL_NOTE = (
    "Nominal duration = frames / stream frame rate of the exported media. It is NOT recording "
    "time: it says nothing about when the footage was recorded."
)
WRITE_BLOCKER_NOTE = "examiner attestation, not verified by the tool"
MAX_ROWS = 300  # per table; truncation is stated in the report
MAX_TEXT = 1200  # per free-text value; truncation is stated in the report


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def content_hash_of(data: dict) -> str:
    body = {k: v for k, v in data.items() if k not in ("generated", "content_hash")}
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def clip_text(value, limit: int = MAX_TEXT) -> str:
    s = value if isinstance(value, str) else canonical(value)
    if len(s) <= limit:
        return s
    return s[:limit] + f" [truncated at {limit} of {len(s)} characters; full value in database]"


def _j(text: str | None, default):
    try:
        return json.loads(text) if text else default
    except ValueError:
        return default


def library_versions() -> dict:
    import reportlab

    try:
        import pypdf

        pypdf_v = pypdf.__version__
    except ImportError:  # pypdf is only needed by tests
        pypdf_v = "not installed (tests only)"
    return {
        "reportlab": {"version": reportlab.Version, "licence": "BSD-3-Clause"},
        "font": {
            "name": "Bitstream Vera Sans (Vera, VeraBd, VeraIt), as shipped inside ReportLab",
            "licence": "Bitstream Vera Fonts licence (permissive; redistribution allowed, the "
            "fonts may not be sold by themselves)",
            "scope": "Latin only. Characters the font lacks are replaced by a visible [U+XXXX] "
            "marker and counted in the colophon; none is dropped silently.",
        },
        "pypdf_tests_only": {"version": pypdf_v, "licence": "BSD-3-Clause"},
    }


def _ffmpeg() -> str:
    try:
        return ffmpeg_version()
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({type(exc).__name__})"


# ------------------------------------------------------------------ evidence


def _evidence_rows(db: Session, case_id: int) -> list[dict]:
    rows = db.scalars(
        select(Evidence).where(Evidence.case_id == case_id).order_by(Evidence.id)
    ).all()
    out = []
    for e in rows:
        verified = {-1: "never verified after acquisition", 0: "FAILED", 1: "passed"}.get(
            e.last_verify_ok, "unknown"
        )
        out.append(
            {
                "id": e.id,
                "label": e.label,
                "source_path": e.source_path,
                "source_type": e.source_type,
                "write_blocker_attested": e.write_blocker,
                "write_blocker_note": WRITE_BLOCKER_NOTE,
                "status": e.status,
                "size_bytes": e.size_bytes,
                "md5": e.md5,
                "sha256": e.sha256,
                "examiner": e.examiner,
                "acquired_at": e.acquired_at,
                "last_verified_at": e.last_verified_at,
                "last_verify_result": verified,
            }
        )
    return out


# ------------------------------------------------------------------ custody


def _custody(db: Session, case_id: int) -> dict:
    ver = custody.verify_chain(db, case_id)
    entries = db.scalars(
        select(CustodyEntry).where(CustodyEntry.case_id == case_id).order_by(CustodyEntry.seq)
    ).all()
    return {
        "verification": ver,
        "entry_rows": [
            {
                "seq": e.seq,
                "timestamp_utc": e.timestamp_utc,
                "action": e.action,
                "examiner": e.examiner,
                "evidence_id": e.evidence_id,
                "tool_version": e.tool_version,
                "ntp_status": e.ntp_status,
                "entry_hash": e.entry_hash,
            }
            for e in entries
        ],
        "public_key_hex": signing.public_key_hex(),
    }


# ------------------------------------------------------------------ carve runs


def _flat(d: dict, prefix: str = "") -> list[list[str]]:
    out: list[list[str]] = []
    for k in sorted(d):
        v = d[k]
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out.extend(_flat(v, key + "."))
        else:
            out.append([key, clip_text(v, 300)])
    return out


def _parser_block(p: dict, vendor_conflicts: dict) -> dict:
    fields = p.get("fields", []) or []
    counts = {"parsed": 0, "inferred": 0, "unknown": 0}
    for f in fields:
        counts[f.get("status", "unknown")] = counts.get(f.get("status", "unknown"), 0) + 1
    conflicts = [
        {"name": f["name"], "status": f.get("status", ""), "value": clip_text(f.get("value"))}
        for f in fields
        if "conflict" in f.get("name", "")
    ]
    cc = (p.get("crosscheck") or {}).get("disagreements", [])
    by_kind: dict[str, int] = {}
    for d in cc:
        by_kind[d.get("kind", "?")] = by_kind.get(d.get("kind", "?"), 0) + 1
    vendor_key = str(p.get("vendor", "")).lower()
    static = [txt for k, txt in vendor_conflicts.items() if k in vendor_key]
    return {
        "parser": p.get("parser", ""),
        "vendor": p.get("vendor", ""),
        "tier": p.get("tier", ""),
        "status": p.get("status", ""),
        "options": _flat(p.get("options", {}) or {}),
        "image_field_counts": counts,
        "open_source_conflicts": conflicts,
        "documented_source_conflicts": static,
        "inconsistencies": [clip_text(x, 400) for x in (p.get("inconsistencies") or [])[:50]],
        "warnings": [clip_text(x, 400) for x in (p.get("warnings") or [])[:50]],
        "stats": _flat(p.get("stats", {}) or {}),
        "crosscheck": {
            "parser_clips": (p.get("crosscheck") or {}).get("parser_clips"),
            "generic_clips": (p.get("crosscheck") or {}).get("generic_clips"),
            "disagreements": len(cc),
            "by_kind": sorted(by_kind.items()),
        },
    }


def _clip_row(c: Clip) -> dict:
    return {
        "id": c.id,
        "engine": c.engine,
        "codec": c.codec,
        "channel": c.channel,
        "start_offset": c.start_offset,
        "end_offset": c.end_offset,
        "size_bytes": c.size_bytes,
        "extent_count": len(_j(c.extents_json, [])),
        "bitstream_sha256": c.bitstream_sha256,
        "mp4_sha256": c.mp4_sha256,
        "decode_status": c.decode_status,
        "decode_errors": [clip_text(x, 300) for x in _j(c.decode_errors_json, [])[:5]],
        "error": clip_text(c.error, 400),
        "reassembled": bool(c.reassembled),
        "end_reason": clip_text(c.reason, 300),
        "duration_s_nominal": c.duration_s,
        "frames": c.packets,
        "fps": c.fps,
        "width": c.width,
        "height": c.height,
    }


def _runs(db: Session, case_id: int) -> list[dict]:
    runs = db.scalars(
        select(CarveRun).where(CarveRun.case_id == case_id).order_by(CarveRun.id)
    ).all()
    out = []
    for r in runs:
        params = _j(r.params_json, {})
        clips = db.scalars(
            select(Clip).where(Clip.run_id == r.id).order_by(Clip.kind, Clip.engine, Clip.seq)
        ).all()
        # per-clip parser field status counts (stored with each parser clip)
        clip_counts = {"parsed": 0, "inferred": 0, "unknown": 0}
        for c in clips:
            for f in _j(c.parsed_json, {}).get("fields", []) or []:
                s = f.get("status", "unknown")
                clip_counts[s] = clip_counts.get(s, 0) + 1
        real = [c for c in clips if c.kind == "clip"]
        orphans = [c for c in clips if c.kind == "orphan"]
        failed = [
            _clip_row(c) for c in real if c.decode_status != "ok" or c.error or not c.mp4_sha256
        ]
        out.append(
            {
                "id": r.id,
                "evidence_id": r.evidence_id,
                "status": r.status,
                "examiner": r.examiner,
                "tool_version": r.tool_version,
                "ffmpeg_version": r.ffmpeg_version,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "error": clip_text(r.error, 400),
                "params": _flat(params),
                "vendor_matches": [
                    {
                        "vendor": m.get("vendor"),
                        "tier": m.get("tier"),
                        "confidence": m.get("confidence"),
                        "notes": [clip_text(n, 300) for n in m.get("notes", [])],
                        "basis": m.get("basis", []),
                        "signature_counts": sorted((m.get("signature_counts") or {}).items()),
                    }
                    for m in _j(r.vendor_json, [])
                ],
                "parsers": [_parser_block(p, VENDOR_CONFLICTS) for p in _j(r.parse_json, [])],
                "clip_field_counts": clip_counts,
                "stats": _flat(_j(r.stats_json, {})),
                "clips": [_clip_row(c) for c in real[:MAX_ROWS]],
                "clips_total": len(real),
                "failed": failed[:MAX_ROWS],
                "failed_total": len(failed),
                "orphans": [
                    {
                        "id": o.id,
                        "engine": o.engine,
                        "channel": o.channel,
                        "start_offset": o.start_offset,
                        "end_offset": o.end_offset,
                        "size_bytes": o.size_bytes,
                        "reason": clip_text(o.reason, 300),
                    }
                    for o in orphans[:MAX_ROWS]
                ],
                "orphans_total": len(orphans),
            }
        )
    return out


# ------------------------------------------------------------------ timestamps


_REC_KEYS = (
    "raw", "field", "format", "offset", "wall_clock_as_stored", "assumed_timezone",
    "tz_evidence", "epoch_basis", "flags", "conflict_note", "utc_lo", "utc_hi",
    "corrected_utc_lo", "corrected_utc_hi",
)  # fmt: skip


def _rec(r: dict | None) -> dict | None:
    if not r:
        return None
    return {k: r.get(k) for k in _REC_KEYS}


def _timestamps(db: Session, case_id: int) -> dict:
    from app.timeline.routes import build_case_timeline

    tl = build_case_timeline(db, case_id, 1.0)
    refs = db.scalars(
        select(ReferenceObservation)
        .where(ReferenceObservation.case_id == case_id)
        .order_by(ReferenceObservation.id)
    ).all()
    evidence = []
    for e in tl["evidence"]:
        evidence.append(
            {
                "evidence_id": e["evidence_id"],
                "label": e["label"],
                "tz_status": e["tz_status"],
                "timezone": e["timezone"],
                "epoch_basis": e["epoch_basis"],
                "evidence_kind": e["evidence_kind"],
                "notes": clip_text(e["notes"] or "", 800),
                "set_by": e["examiner"],
                "updated_at": e["updated_at"],
                "references": [
                    {
                        "id": r.id,
                        "device_time_raw": r.device_time_raw,
                        "true_time_utc": r.true_time_utc,
                        "method": r.method,
                        "notes": clip_text(r.notes, 400),
                        "reading_uncertainty_s": r.reading_uncertainty_s,
                    }
                    for r in refs
                    if r.evidence_id == e["evidence_id"]
                ],
                "model": e["model"],
            }
        )

    def row(p: dict) -> dict:
        return {
            "clip_id": p["clip_id"],
            "evidence_id": p["evidence_id"],
            "channel": p["channel"],
            "engine": p["engine"],
            "flags": p["flags"],
            "tz_status": p["tz_status"],
            "drift_model_id": p["drift_model_id"],
            "start_record": _rec(p.get("start_record")),
            "end_record": _rec(p.get("end_record")),
            "plot_start": p.get("start"),
            "plot_end": p.get("end"),
            "end_note": p.get("end_note", ""),
            "reason": p.get("reason", ""),
            "order": p.get("order"),
            "ambiguous_order_with": p.get("ambiguous_order_with", []),
        }

    return {
        "tie_break": tl["tie_break"],
        "evidence": evidence,
        "placed": [row(p) for p in tl["placed"][:MAX_ROWS]],
        "placed_total": len(tl["placed"]),
        "unplaceable": [row(p) for p in tl["unplaceable"][:MAX_ROWS]],
        "unplaceable_total": len(tl["unplaceable"]),
        "gaps": tl["gaps"][:100],
        "gaps_total": len(tl["gaps"]),
        "overlaps": tl["overlaps"][:100],
        "overlaps_total": len(tl["overlaps"]),
        "flag_help": {k: v for k, v in FLAG_HELP.items()},
        "disclaimer": tl["disclaimer"],
    }


# ------------------------------------------------------------------ analytics


def _rates(er: dict | None) -> dict | None:
    if not er:
        return None
    cfgs = []
    for c in er.get("configs", []) or []:
        cfgs.append(
            {
                k: c.get(k)
                for k in (
                    "condition",
                    "class",
                    "confidence_threshold",
                    "iou_threshold",
                    "dataset",
                    "label",
                    "n_images",
                    "tp",
                    "fp",
                    "fn",
                    "precision",
                    "recall",
                    "precision_ci_wilson",
                    "recall_ci_wilson",
                )
            }  # fmt: skip
        )
    return {
        "label": er.get("label", ""),
        "note": er.get("note", ""),
        "unmeasured_note": er.get("unmeasured_note", ""),
        "generated_by": er.get("generated_by", ""),
        "run_threshold_measured": er.get("run_threshold_measured"),
        "run_params_match_measured": er.get("run_params_match_measured"),
        "configs": cfgs,
    }


def _analytics(db: Session, case_id: int) -> list[dict]:
    runs = db.scalars(
        select(AnalyticsRun).where(AnalyticsRun.case_id == case_id).order_by(AnalyticsRun.id)
    ).all()
    out = []
    for r in runs:
        summary: dict = {}
        if r.kind == "motion":
            ivs = db.scalars(
                select(MotionInterval)
                .where(MotionInterval.run_id == r.id)
                .order_by(MotionInterval.start_frame)
            ).all()
            summary["intervals"] = [
                [m.start_frame, m.end_frame, m.start_time_s, m.end_time_s, m.score_peak]
                for m in ivs[:50]
            ]
            summary["intervals_total"] = len(ivs)
        else:
            dets = db.scalars(select(Detection).where(Detection.run_id == r.id)).all()
            by: dict[str, dict] = {}
            for d in dets:
                s = by.setdefault(d.class_name, {"n": 0, "max_conf": 0.0, "t0": d.nominal_time_s,
                                                 "t1": d.nominal_time_s})  # fmt: skip
                s["n"] += 1
                s["max_conf"] = max(s["max_conf"], d.confidence)
                s["t0"], s["t1"] = min(s["t0"], d.nominal_time_s), max(s["t1"], d.nominal_time_s)
            summary["by_class"] = [[k, v["n"], v["max_conf"], v["t0"], v["t1"]]
                                   for k, v in sorted(by.items())]  # fmt: skip
            summary["detections_total"] = len(dets)
        out.append(
            {
                "id": r.id,
                "clip_id": r.clip_id,
                "kind": r.kind,
                "status": r.status,
                "label": r.label,
                "expected_label": TRIAGE_LABEL,
                "examiner": r.examiner,
                "bitstream_sha256": r.bitstream_sha256,
                "mp4_sha256": r.mp4_sha256,
                "params": _flat(_j(r.params_json, {})),
                "model": _j(r.model_json, None),
                "error_rates": _rates(_j(r.error_rates_json, None)),
                "tool": _flat(_j(r.tool_json, {})),
                "frames_analysed": r.frames_analysed,
                "result_count": r.result_count,
                "started_at": r.started_at,
                "error": clip_text(r.error, 400),
                "summary": summary,
            }
        )
    return out


# ------------------------------------------------------------------ limitations


def validation_results_path() -> Path:
    env = os.getenv("NIRIKSHAN_VALIDATION_RESULTS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "docs" / "validation" / "results.json"


def reassembler_false_accept(path: Path | None = None) -> dict:
    """Read the measured false-accept rate of the H.264 fragment reassembler from the committed
    baseline. Returns {'available': False, 'reason': ...} rather than guessing."""
    p = path or validation_results_path()
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        return {"available": False, "reason": f"{p.name} not readable ({type(exc).__name__})"}
    for s in d.get("scenarios", []):
        m = s.get("metrics", {}).get("reassembler_false_accept")
        if m and s.get("scenario", s.get("id")) == "fragmented_decoy_join_on" and m.get("n"):
            return {
                "available": True,
                "scenario": "fragmented_decoy_join_on",
                "k": m["k"],
                "n": m["n"],
                "rate": m["rate"],
                "ci95": m["ci95"],
                "source": f"docs/validation/results.json (seed {d.get('seed')}, "
                f"digest {str(d.get('results_digest'))[:16]})",
                "synthetic": bool(d.get("synthetic")),
            }
    return {"available": False, "reason": "scenario fragmented_decoy_join_on not in results file"}


def _limitations(runs: list[dict], fa_path: Path | None) -> dict:
    tiers = sorted(
        {m["tier"] for r in runs for m in r["vendor_matches"] if m.get("tier")}
        | {p["tier"] for r in runs for p in r["parsers"] if p.get("tier")}
    )
    return {
        "tiers_in_this_report": tiers,
        "tiers_defined_in_code": list(TIERS),
        "reassembler": reassembler_false_accept(fa_path),
    }


# ------------------------------------------------------------------ entry point


def build_report_data(
    db: Session,
    case_id: int,
    generated_at: str | None = None,
    ntp: str | None = None,
    validation_results: Path | None = None,
) -> dict:
    case = db.get(Case, case_id)
    if case is None:
        raise LookupError(f"case {case_id} not found")
    cust = _custody(db, case_id)
    runs = _runs(db, case_id)
    data = {
        "report_format": REPORT_FORMAT,
        "cover": {
            "case_id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "description": clip_text(case.description, 1500),
            "case_examiner": case.examiner,
            "case_created_at": case.created_at,
            "tool_version": __version__,
            "ffmpeg_version": _ffmpeg(),
            "signing_key_id": cust["verification"]["key_id"],
            "libraries": library_versions(),
        },
        "evidence": _evidence_rows(db, case_id),
        "custody": cust,
        "runs": runs,
        "timestamps": _timestamps(db, case_id),
        "analytics": _analytics(db, case_id),
        "limitations": _limitations(runs, validation_results),
        "generated": {
            "generated_at": generated_at or utc_now_iso(),
            "ntp_status": ntp if ntp is not None else current_ntp_status(),
        },
    }
    data["content_hash"] = content_hash_of(data)
    return data
