"""Structured-parse result types shared by all vendor parsers (P4).

Rules every parser follows:
  * Never raise: any inconsistency or exception becomes status 'fallback'/'partial' plus
    warnings, and the generic carver's output stands on its own.
  * Every field is tagged `parsed` (read directly from bytes the source documents), `inferred`
    (our reading of the sources, or a heuristic) or `unknown` (present but undocumented / not
    verified). A parser must not report a field it did not parse.
  * Timestamps are returned RAW (value, byte offset, format, source). No timezone is assumed;
    P5 normalizes. `wall_clock_as_stored` is a plain decode of the stored fields, not UTC.
  * Tier labels are not changed by parsing (all three are Tier B).
"""

from dataclasses import asdict, dataclass, field


@dataclass
class ParsedField:
    name: str
    value: object
    status: str  # parsed | inferred | unknown
    source: str = ""  # RESEARCH / field-table reference
    note: str = ""


@dataclass
class RawTimestamp:
    field: str
    offset: int  # byte offset in the image
    raw: object  # integer value as stored
    format: str  # e.g. "dhav packed bit fields", "unix seconds (u32 LE)"
    wall_clock_as_stored: str = ""  # plain decode, NO timezone claim
    tz_basis: str = "not assumed"  # never 'UTC' or 'local' unless a parser option labels it
    note: str = ""


@dataclass
class ParsedClip:
    codec: str  # h264 | h265 | mpeg4 | mjpeg | unknown
    extents: list[list[int]]  # payload byte ranges (concatenated = elementary stream)
    channel: int | None = None
    frames: int = 0
    key_frames: int = 0
    exportable: bool = True  # False for codecs the exporter does not handle
    width: int | None = None
    height: int | None = None
    timestamps: list[RawTimestamp] = field(default_factory=list)
    fields: list[ParsedField] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    end_reason: str = ""

    @property
    def start(self) -> int:
        return self.extents[0][0]

    @property
    def end(self) -> int:
        return self.extents[-1][1]

    @property
    def size(self) -> int:
        return sum(e - s for s, e in self.extents)


@dataclass
class ParsedOrphan:
    channel: int | None
    start: int
    end: int
    frames: int
    reason: str


@dataclass
class ParseResult:
    parser: str
    vendor: str
    tier: str
    status: str  # parsed | partial | fallback
    options: dict = field(default_factory=dict)
    fields: list[ParsedField] = field(default_factory=list)
    clips: list[ParsedClip] = field(default_factory=list)
    orphans: list[ParsedOrphan] = field(default_factory=list)
    timestamps: list[RawTimestamp] = field(default_factory=list)  # image-level samples (capped)
    warnings: list[str] = field(default_factory=list)
    inconsistencies: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    crosscheck: dict = field(default_factory=dict)

    def to_dict(self, compact: bool = True) -> dict:
        """compact drops per-clip extent lists (they live in the clips table)."""
        d = asdict(self)
        for c, src in zip(d["clips"], self.clips, strict=True):
            c["size"], c["start"], c["end"] = src.size, src.start, src.end
            if compact:
                c["extents"] = len(src.extents)
        return d


def fallback(parser, vendor, tier, options, reason: str, **kw) -> ParseResult:
    return ParseResult(parser, vendor, tier, "fallback", options, warnings=[reason], **kw)


def _overlap(a: list[list[int]], b: list[list[int]]) -> int:
    tot = 0
    for s1, e1 in a:
        for s2, e2 in b:
            tot += max(0, min(e1, e2) - max(s1, s2))
    return tot


def crosscheck(parsed: list[ParsedClip], generic: list, tolerance: float = 0.5) -> dict:
    """Compare parser clips with generic-carver clips (objects with .extents/.vcl_count/.codec)
    on the same image and list every disagreement. `generic` clips include vendor header bytes
    between NAL units, so byte equality is not expected: the comparison is overlap of payload
    bytes plus frame-count agreement."""
    out: list[dict] = []
    used: set[int] = set()
    for i, p in enumerate(parsed):
        if not p.exportable:
            continue
        best, best_ov = None, 0
        for j, g in enumerate(generic):
            ov = _overlap(p.extents, [list(e) for e in g.extents])
            if ov > best_ov:
                best, best_ov = j, ov
        if best is None or best_ov < tolerance * p.size:
            out.append(
                {
                    "kind": "parser_clip_not_found_by_generic",
                    "parser_clip": i,
                    "channel": p.channel,
                    "offset": p.start,
                    "bytes": p.size,
                }
            )
            continue
        used.add(best)
        g = generic[best]
        if g.codec != p.codec:
            out.append(
                {
                    "kind": "codec_mismatch",
                    "parser_clip": i,
                    "generic_clip": best,
                    "parser": p.codec,
                    "generic": g.codec,
                }
            )
        if g.vcl_count != p.frames:
            out.append(
                {
                    "kind": "frame_count_mismatch",
                    "parser_clip": i,
                    "generic_clip": best,
                    "parser_frames": p.frames,
                    "generic_vcl_nal_units": g.vcl_count,
                    "note": "generic counts VCL NAL units; multi-slice frames differ benignly",
                }
            )
        extra = sum(e - s for s, e in g.extents) - best_ov
        if extra > 0.02 * max(1, sum(e - s for s, e in g.extents)):
            out.append(
                {
                    "kind": "generic_includes_extra_bytes",
                    "parser_clip": i,
                    "generic_clip": best,
                    "extra_bytes": extra,
                    "note": "vendor headers/gaps absorbed by the generic carver",
                }
            )
    for j, g in enumerate(generic):
        if j in used:
            continue
        if not any(_overlap([list(e) for e in g.extents], p.extents) for p in parsed):
            out.append(
                {
                    "kind": "generic_clip_not_explained_by_parser",
                    "generic_clip": j,
                    "offset": g.extents[0][0],
                    "bytes": sum(e - s for s, e in g.extents),
                }
            )
    return {"parser_clips": len(parsed), "generic_clips": len(generic), "disagreements": out}
