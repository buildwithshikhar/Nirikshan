"""Turn a worker's analyze_plan JSON back into the pipeline's objects, after validating it.

The worker is less trusted than the parent (it parsed hostile bytes), so its output is checked
before anything is persisted: types, offsets inside the image, ranges equal to what the parent
computes itself, and the image hash the worker saw. Rebuilding uses the same dataclasses the
in-process pipeline produces, so app.analyze stores both paths through the same code.
"""

from __future__ import annotations

from app.carving.carve import Clip as CarvedClip
from app.carving.carve import Orphan
from app.vendors.base import Hit, Match
from app.vendors.parse import ParsedClip, ParsedField, ParsedOrphan, ParseResult, RawTimestamp

CODECS = {"h264", "h265", "mpeg4", "mjpeg", "unknown"}


class PlanInvalid(RuntimeError):
    pass


def _unbytes(v):
    if isinstance(v, dict) and set(v) == {"__bytes_hex__"}:
        return bytes.fromhex(v["__bytes_hex__"])
    if isinstance(v, list):
        return [_unbytes(x) for x in v]
    if isinstance(v, dict):
        return {k: _unbytes(x) for k, x in v.items()}
    return v


def _extents(ext, size: int) -> list[list[int]]:
    out = []
    if not isinstance(ext, list) or not ext:
        raise PlanInvalid("clip without extents")
    for e in ext:
        if not (isinstance(e, list) and len(e) == 2 and all(isinstance(x, int) for x in e)):
            raise PlanInvalid("malformed extent")
        s, t = e
        if not 0 <= s < t <= size:
            raise PlanInvalid(f"extent [{s}, {t}) outside the image (size {size})")
        out.append([s, t])
    return out


def _match(d: dict) -> Match:
    return Match(
        vendor=str(d["vendor"]),
        tier=str(d["tier"]),
        confidence=str(d["confidence"]),
        evidence=[Hit(**h) for h in d.get("evidence", [])],
        signature_counts=dict(d.get("signature_counts", {})),
        basis=list(d.get("basis", [])),
        notes=list(d.get("notes", [])),
    )


def _ts(d):
    return None if d is None else RawTimestamp(**_unbytes(d))


def _parsed_clip(d: dict, size: int) -> ParsedClip:
    if d.get("codec") not in CODECS:
        raise PlanInvalid(f"unknown codec {d.get('codec')!r}")
    d = dict(d)
    d["extents"] = _extents(d["extents"], size)
    d["timestamps"] = [_ts(t) for t in d.get("timestamps", [])]
    d["fields"] = [ParsedField(**_unbytes(f)) for f in d.get("fields", [])]
    return ParsedClip(**d)


def _parse_result(d: dict | None, size: int) -> ParseResult | None:
    if d is None:
        return None
    d = dict(d)
    d["fields"] = [ParsedField(**_unbytes(f)) for f in d.get("fields", [])]
    d["clips"] = [_parsed_clip(c, size) for c in d.get("clips", [])]
    d["orphans"] = [ParsedOrphan(**o) for o in d.get("orphans", [])]
    d["timestamps"] = [_ts(t) for t in d.get("timestamps", [])]
    for o in d["orphans"]:
        if not 0 <= o.start <= o.end <= size:
            raise PlanInvalid("parser orphan outside the image")
    return ParseResult(**d)


def _generic(d: dict, size: int):
    d = dict(d)
    kind = d.pop("type")
    if d.get("codec") not in CODECS:
        raise PlanInvalid(f"unknown codec {d.get('codec')!r}")
    if kind == "clip":
        d["extents"] = _extents(d["extents"], size)
        return CarvedClip(**d)
    if kind == "orphan":
        if not 0 <= d["start"] <= d["end"] <= size:
            raise PlanInvalid("generic orphan outside the image")
        return Orphan(**d)
    raise PlanInvalid(f"unknown generic item type {kind!r}")


class PlannedSource:
    """Same interface as app.analyze.LiveSource, backed by a validated worker plan."""

    def __init__(self, plan: dict, size: int, expected_sha256: str):
        try:
            if plan["size"] != size or plan["sha256"] != expected_sha256:
                raise PlanInvalid("the worker analysed different bytes than the recorded image")
            self.matches = [_match(m) for m in plan["matches"]]
            self.parsed = [_parse_result(r, size) for r in plan["parsed"]]
            if len(self.parsed) != len(self.matches):
                raise PlanInvalid("parser results do not line up with vendor matches")
            self._ranges = [tuple(r) for r in plan["ranges"]]
            self._generic = [_generic(g, size) for g in plan["generic"]]
            self._full = [_generic({"type": "clip", **c}, size) for c in plan["full_generic"]]
            self.timings = {k: float(v) for k, v in plan.get("timings", {}).items()}
        except PlanInvalid:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanInvalid(f"malformed worker plan ({type(exc).__name__}: {exc})") from None

    def identify(self) -> list[Match]:
        return self.matches

    def parse(self, index: int, _match) -> ParseResult | None:
        return self.parsed[index]

    def generic(self, ranges: list[tuple[int, int]]):
        if [tuple(r) for r in ranges] != self._ranges:
            raise PlanInvalid("worker carved different ranges than the parent computed")
        return iter(self._generic)

    def full_generic(self) -> list[CarvedClip]:
        return self._full
