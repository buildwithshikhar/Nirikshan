"""Device intelligence: manufacturer / model / firmware ONLY from documented structures.

Reuses the parser registry's Probe/Signature definitions and the shared single-pass scan
(app.vendors.base.scan_image). Each probe/signature is wrapped so the scan also records what it
rejected; the parsers' own identify() then produces the Match exactly as in analysis, so the
breakdown and the analysis pipeline cannot disagree.

Model/firmware attributes are read only where docs/parsers/ documents the field:
  * Honeywell: Machine Data device ID (0x4440) and model (0x4468), field doc 1.3. Firmware is
    shown only in a UI screenshot of the source: no on-disk field, so firmware = unknown.
  * Hikvision: the Master Sector has no documented model or firmware field. The text at
    +0x20 (e.g. "HIK.2011.03.08") is reported as a version-like string whose meaning is
    undocumented; it is NOT presented as firmware.
  * Dahua: DHAV frames (dhav.c) carry no model or firmware field.
Everything else is 'unknown' with the reason. Unknown devices are routed to generic carving.
"""

from dataclasses import dataclass, field
from typing import BinaryIO

from app.vendors import TIER_C_VENDORS, default_registry
from app.vendors.base import Probe, Scope, Signature, VendorParser, scan_image

MAX_REJECT_SAMPLES = 10
PREVIEW = 32


@dataclass
class _Rec:
    name: str
    kind: str  # probe | signature
    parser: str
    pattern: bytes = b""
    offset: int | None = None  # probes only
    length: int = 0
    has_validator: bool = False
    checked: bool = False  # probes: offset inside image
    seen_bytes: bytes = b""  # probes: bytes read at the fixed offset (preview)
    candidates: int = 0  # signatures: occurrences handed to the validator
    rejected: int = 0
    rejected_offsets: list[int] = field(default_factory=list)


class _Wrapped(VendorParser):
    """Delegates probes/signatures of `inner`, recording every check and rejection."""

    def __init__(self, inner: VendorParser, recs: dict[str, _Rec]):
        self.inner, self.recs = inner, recs
        self.vendor = inner.vendor

    def probes(self) -> list[Probe]:
        out = []
        for p in self.inner.probes():
            rec = self.recs.setdefault(
                p.name, _Rec(p.name, "probe", self.vendor, offset=p.offset, length=p.length)
            )

            def check(b: bytes, p=p, rec=rec):
                rec.checked, rec.seen_bytes = True, b[:PREVIEW]
                return p.check(b)

            out.append(Probe(p.name, p.offset, p.length, check))
        return out

    def signatures(self) -> list[Signature]:
        out = []
        for s in self.inner.signatures():
            rec = self.recs.setdefault(
                s.name,
                _Rec(
                    s.name,
                    "signature",
                    self.vendor,
                    pattern=s.pattern,
                    length=len(s.pattern),
                    has_validator=s.validate is not None,
                ),
            )

            def validate(read, off, s=s, rec=rec):
                rec.candidates += 1
                detail = "signature match" if s.validate is None else s.validate(read, off)
                if not detail:
                    rec.rejected += 1
                    if len(rec.rejected_offsets) < MAX_REJECT_SAMPLES:
                        rec.rejected_offsets.append(off)
                return detail

            out.append(Signature(s.name, s.pattern, validate))
        return out


def _pattern_text(b: bytes) -> str:
    return b.decode("ascii") if b and all(32 <= c < 127 for c in b) else b.hex(" ")


def _breakdown(rec: _Rec, scope: Scope, size: int) -> dict:
    count = scope.counts.get(rec.name, 0)
    hits = scope.hits.get(rec.name, [])
    d = {
        "name": rec.name,
        "kind": rec.kind,
        "matched": count > 0,
        "count": count,
        "offsets": [h.offset for h in hits],
        "details": sorted({h.detail for h in hits})[:5],
        "length": rec.length,
    }
    if rec.kind == "probe":
        d["expected_offset"] = rec.offset
        if not rec.checked:
            d["reason"] = f"image ({size} bytes) ends before the documented offset {rec.offset}"
        elif not count:
            d["reason"] = (
                f"bytes at the documented offset {rec.offset} (0x{rec.offset:X}) do not satisfy "
                "the documented check"
            )
            d["bytes_seen_hex"] = rec.seen_bytes.hex(" ")
        return d
    d["pattern"] = _pattern_text(rec.pattern)
    d["pattern_hex"] = rec.pattern.hex(" ")
    d["structural_validation"] = rec.has_validator
    d["candidates"] = rec.candidates
    d["rejected"] = rec.rejected
    d["rejected_offsets_sample"] = rec.rejected_offsets
    if not count:
        d["reason"] = (
            "pattern not present in the image"
            if rec.candidates == 0
            else f"pattern found {rec.candidates} time(s) but every occurrence failed the "
            "documented structural validation"
        )
    return d


def _attr(value, status: str, source: str = "", offset: int | None = None, note: str = ""):
    return {"value": value, "status": status, "source": source, "offset": offset, "note": note}


def _unknown(reason: str) -> dict:
    return _attr(None, "unknown", note=reason)


def _honeywell_attrs(f: BinaryIO, size: int) -> dict:
    from app.vendors import honeywell_fs as H

    c = H._Ctx(f, size, {k: v["default"] for k, v in H.OPTIONS.items()})
    H.parse_machine_data(c)
    got = {x.name: x for x in c.fields}
    src = "docs/parsers/honeywell-fields.md 1.3 (arXiv 2605.07430 [S5] Fig. 3)"
    out = {}
    for key, name, off in (
        ("model", "model", H.MODEL_ABS),
        ("device_id", "device_id", H.DEVICE_ID_ABS),
    ):
        fld = got.get(name)
        out[key] = (
            _attr(fld.value, "parsed", src, off, fld.note)
            if fld is not None
            else _unknown(
                "Machine Data field absent or not printable ASCII at the documented offset "
                f"0x{off:X}"
                + (f" ({'; '.join(c.incons + c.warnings)})" if c.incons or c.warnings else "")
            )
        )
    out["firmware"] = _unknown(
        "the source shows firmware only in a UI screenshot (1.24.1.146.20241120); no on-disk "
        "firmware field is documented"
    )
    return out


def _hikvision_attrs(f: BinaryIO, size: int) -> dict:
    from app.vendors import hikvision_fs as K

    run = K._Run(K.HikvisionFsParser(), f, size, {k: v["default"] for k, v in K.OPTIONS.items()})
    m = run.master()
    out = {
        "model": _unknown("no model field is documented in the Hikvision Master Sector [S1][S2]"),
        "firmware": _unknown(
            "no firmware field is documented; the +0x20 text is a version-like string of "
            "undocumented meaning and is not presented as firmware"
        ),
    }
    if m is not None:
        fld = next((x for x in run.fields if x.name == "version_like_string"), None)
        if fld is not None:
            out["filesystem_version_like_string"] = _attr(
                fld.value,
                "unknown",
                "docs/parsers/hikvision-fields.md s1 (+0x20)",
                m["base"] + 0x20,
                "value read; meaning undocumented (partly documented); not used as firmware",
            )
    return out


def _dahua_attrs(_f, _size) -> dict:
    why = "DHAV frames (FFmpeg dhav.c [S9]) carry no {} field; DHFS structures are undocumented"
    return {"model": _unknown(why.format("model")), "firmware": _unknown(why.format("firmware"))}


ATTRS = {"Honeywell": _honeywell_attrs, "Hikvision": _hikvision_attrs, "Dahua": _dahua_attrs}


def identify(f: BinaryIO, size: int) -> dict:
    registry = default_registry()
    recs: dict[str, _Rec] = {}
    wrapped = [_Wrapped(p, recs) for p in registry.parsers]
    scope = scan_image(f, size, wrapped)
    parsers = []
    matches = []
    for p in registry.parsers:
        m = p.identify(scope)
        names = [x.name for x in p.probes()] + [x.name for x in p.signatures()]
        sigs = [_breakdown(recs[n], scope, size) for n in names]
        entry = {
            "vendor": p.vendor,
            "tier": p.tier,
            "parser_version": getattr(p, "parser_version", ""),
            "confidence": m.confidence,
            "matched": m.confidence != "none",
            "signatures_matched": sum(1 for s in sigs if s["matched"]),
            "signatures_total": len(sigs),
            "signatures": sigs,
            "basis": m.basis,
            "notes": m.notes,
            "confidence_rule": "parser identify(): best possible is 'medium' (no vendor is Tier A)",
        }
        parsers.append(entry)
        if m.confidence != "none":
            matches.append(entry)
    order = {"medium": 2, "low": 1}
    matches.sort(key=lambda e: -order[e["confidence"]])
    top = matches[0] if matches else None
    ambiguous = len(matches) > 1 and matches[0]["confidence"] == matches[1]["confidence"]
    if top is None:
        manufacturer = _unknown(
            "no documented signature of any supported parser matched "
            f"({', '.join(p.vendor for p in registry.parsers)} checked)"
        )
        device = {
            "model": _unknown("manufacturer unknown"),
            "firmware": _unknown("manufacturer unknown"),
        }
        routing = {
            "engine": "generic carving only",
            "reason": "unknown device: vendor-agnostic H.264/H.265 carving; no vendor, channel "
            "or time attribution",
        }
    else:
        manufacturer = _attr(
            top["vendor"],
            "identified" if not ambiguous else "ambiguous",
            "; ".join(top["basis"]),
            note=f"confidence {top['confidence']} from documented signatures; Tier {top['tier']}"
            + ("; another vendor matched with equal confidence" if ambiguous else ""),
        )
        device = ATTRS[top["vendor"]](f, size)
        routing = {
            "engine": f"{top['vendor']} parser first, then generic carving of uncovered bytes",
            "reason": "documented signature matched; the parser is unvalidated on real devices",
        }
    return {
        "available": True,
        "image_size": size,
        "manufacturer": manufacturer,
        "device": device,
        "ambiguous": ambiguous,
        "matches": [{k: e[k] for k in ("vendor", "tier", "confidence")} for e in matches],
        "routing": routing,
        "parsers": parsers,
        "not_identifiable": {
            "vendors": list(TIER_C_VENDORS),
            "reason": "Tier C: no public byte-level signature, so these cannot be identified; "
            "their images are carved generically and left unattributed (see /api/oem-registry)",
        },
        "limits": [
            "Identification uses only signatures documented in docs/RESEARCH.md and docs/parsers/.",
            "No vendor is Tier A; nothing is validated on a real device; confidence is at most "
            "'medium'.",
            "Model and firmware are reported only where a documented on-disk field exists.",
        ],
    }
