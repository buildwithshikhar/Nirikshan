"""Deterministic offline query grammar for the event index (hand-written; no LLM, no network).

Example:  person camera 2 between 10:00 and 11:00 confidence>0.5
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time

from app.analytics.registry import COCO_LABELS
from app.timeline.timestamps import TzError, get_zone

CLASSES = frozenset(COCO_LABELS) | {"face", "motion"}
GROUPS = {
    "vehicle": frozenset({"bicycle", "car", "motorcycle", "bus", "truck"}),
    "people": frozenset({"person"}),
    "persons": frozenset({"person"}),
    "faces": frozenset({"face"}),
}
KINDS = ("motion", "objects", "faces")
STOPWORDS = frozenset(
    "show find list all the a an and or with of at in events event detections detection any".split()
)
OPS = (">=", "<=", "!=", ">", "<", "=")

GRAMMAR = {
    "summary": (
        "Space-separated clauses, combined with AND; repeated values of one clause type are "
        "ORed (person car = person OR car). Matching is deterministic and offline."
    ),
    "clauses": [
        {
            "form": "<class>",
            "example": "person",
            "meaning": "detection class: any COCO label (person, car, traffic_light, ...), face, "
            "motion; plural 's' accepted; 'vehicle' = bicycle/car/motorcycle/bus/truck",
        },
        {
            "form": "camera N | cam N | channel N | ch N",
            "example": "camera 2",
            "meaning": "recorder channel of the clip",
        },
        {"form": "clip N", "example": "clip 14", "meaning": "one clip id"},
        {"form": "evidence N", "example": "evidence 3", "meaning": "one evidence id"},
        {"form": "kind motion|objects|faces", "example": "kind faces", "meaning": "analytics kind"},
        {
            "form": "between HH:MM[:SS] and HH:MM[:SS]",
            "example": "between 10:00 and 11:00",
            "meaning": "time of day (window may cross midnight). PLACED clips only",
        },
        {
            "form": "after HH:MM[:SS] | before HH:MM[:SS]",
            "example": "after 22:30",
            "meaning": "open-ended time of day. PLACED clips only",
        },
        {
            "form": "on YYYY-MM-DD",
            "example": "on 2025-06-01",
            "meaning": "calendar date. PLACED clips only",
        },
        {
            "form": "utc | tz <IANA zone>",
            "example": "tz Asia/Kolkata",
            "meaning": "zone for time-of-day/date clauses. Without it, times are read as each "
            "evidence item's device-local wall clock using the EXAMINER-ENTERED timezone "
            "assumption; nothing is defaulted",
        },
        {
            "form": "confidence OP X | conf OP X  (OP: > >= < <= = !=)",
            "example": "confidence>0.5",
            "meaning": "detector confidence 0..1 (motion events have none and never match)",
        },
        {
            "form": "placed | unplaceable",
            "example": "unplaceable",
            "meaning": "only events whose clip the timeline does / does not place in absolute time",
        },
        {
            "form": '"free text"',
            "example": '"traffic light"',
            "meaning": "full-text terms over class, kind, camera, clip, evidence and model name",
        },
    ],
    "ignored_words": sorted(STOPWORDS),
    "notes": [
        "Absolute times exist only for clips the case timeline places (examiner timezone "
        "assumption, no default); the response counts the clips excluded as unplaceable.",
        "Results are triage leads, not identification. Face results are face DETECTIONS only.",
    ],
}

TOKEN_RE = re.compile(r'"([^"]*)"|(>=|<=|!=|>|<|=)|([^\s"<>=!]+)')
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
NUM_RE = re.compile(r"^(?:\d+(?:\.\d*)?|\.\d+)$")


class QueryError(ValueError):
    def __init__(self, message: str, position: int | None = None, token: str | None = None):
        super().__init__(message)
        self.message, self.position, self.token = message, position, token

    def to_dict(self) -> dict:
        return {
            "error": self.message,
            "position": self.position,
            "token": self.token,
            "grammar": GRAMMAR,
        }


@dataclass
class Query:
    classes: set[str] = field(default_factory=set)
    cameras: set[int] = field(default_factory=set)
    clips: set[int] = field(default_factory=set)
    evidence: set[int] = field(default_factory=set)
    kinds: set[str] = field(default_factory=set)
    tod_start: time | None = None
    tod_end: time | None = None
    on_date: date | None = None
    zone: str | None = None  # None = device-local per evidence assumption
    confidence: list[tuple[str, float]] = field(default_factory=list)
    placement: str | None = None
    text: list[str] = field(default_factory=list)

    @property
    def has_time(self) -> bool:
        return self.tod_start is not None or self.tod_end is not None or self.on_date is not None

    def describe(self) -> list[str]:
        out = []
        if self.classes:
            out.append("class in {" + ", ".join(sorted(self.classes)) + "}")
        for name, vals in (
            ("camera", self.cameras),
            ("clip", self.clips),
            ("evidence", self.evidence),
            ("kind", self.kinds),
        ):
            if vals:
                out.append(f"{name} in {{" + ", ".join(str(v) for v in sorted(vals)) + "}")
        if self.has_time:
            zone = (
                self.zone or "device-local wall clock (examiner timezone assumption per evidence)"
            )
            s = self.tod_start.isoformat() if self.tod_start else "00:00:00"
            e = self.tod_end.isoformat() if self.tod_end else "23:59:59.999999"
            d = f" on {self.on_date.isoformat()}" if self.on_date else ""
            out.append(f"time of day {s}-{e}{d} in {zone}; placed clips only")
        for op, v in self.confidence:
            out.append(f"confidence {op} {v}")
        if self.placement:
            out.append(f"placement = {self.placement}")
        if self.text:
            out.append("full text: " + " ".join(self.text))
        return out


def tokenize(q: str) -> list[tuple[str, str, int]]:
    """(type, value, position) with type in quoted|op|word."""
    out = []
    pos = 0
    for m in TOKEN_RE.finditer(q):
        gap = q[pos : m.start()]
        if gap.strip().startswith('"'):
            raise QueryError("unterminated quote", pos + gap.index('"'))
        if gap.strip():
            raise QueryError(
                f"unexpected character {gap.strip()[0]!r}", pos + gap.index(gap.strip()[0])
            )
        if m.group(1) is not None:
            out.append(("quoted", m.group(1), m.start()))
        elif m.group(2):
            out.append(("op", m.group(2), m.start()))
        else:
            out.append(("word", m.group(3), m.start()))
        pos = m.end()
    rest = q[pos:]
    if rest.strip():
        ch = rest.strip()[0]
        msg = "unterminated quote" if ch == '"' else f"unexpected character {ch!r}"
        raise QueryError(msg, pos + rest.index(ch))
    return out


def _time(tok, label) -> time:
    m = TIME_RE.match(tok[1]) if tok and tok[0] == "word" else None
    if not m:
        raise QueryError(
            f"{label}: expected a time HH:MM or HH:MM:SS",
            tok[2] if tok else None,
            tok[1] if tok else None,
        )
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if h > 23 or mi > 59 or s > 59:
        raise QueryError(f"{label}: {tok[1]} is not a valid time of day", tok[2], tok[1])
    return time(h, mi, s)


def _int(tok, label) -> int:
    if not tok or tok[0] != "word" or not tok[1].isdigit():
        raise QueryError(
            f"{label}: expected a whole number", tok[2] if tok else None, tok[1] if tok else None
        )
    return int(tok[1])


def _class_of(word: str) -> set[str] | None:
    w = word.lower()
    if w in GROUPS:
        return set(GROUPS[w])
    if w in CLASSES:
        return {w}
    for suffix in ("es", "s"):
        stem = w[: -len(suffix)]
        if w.endswith(suffix) and stem in GROUPS:
            return set(GROUPS[stem])
        if w.endswith(suffix) and stem in CLASSES:
            return {stem}
    return None


def parse(q: str) -> Query:
    if len(q) > 500:
        raise QueryError("query longer than 500 characters")
    toks = tokenize(q)
    out = Query()
    i = 0

    def nxt(k=1):
        return toks[i + k] if i + k < len(toks) else None

    while i < len(toks):
        typ, val, pos = toks[i]
        low = val.lower()
        if typ == "quoted":
            from app.events.fts import terms

            words = terms(val)
            if not words:
                raise QueryError("empty quoted text", pos, val)
            out.text += words
            i += 1
            continue
        if typ == "op":
            raise QueryError(f"operator {val!r} must follow 'confidence'", pos, val)
        if low in ("camera", "cam", "channel", "ch"):
            out.cameras.add(_int(nxt(), low))
            i += 2
        elif low == "clip":
            out.clips.add(_int(nxt(), "clip"))
            i += 2
        elif low == "evidence":
            out.evidence.add(_int(nxt(), "evidence"))
            i += 2
        elif low == "kind":
            t = nxt()
            if not t or t[1].lower() not in KINDS:
                raise QueryError(
                    "kind: expected motion, objects or faces",
                    t[2] if t else None,
                    t[1] if t else None,
                )
            out.kinds.add(t[1].lower())
            i += 2
        elif low == "between":
            if out.tod_start or out.tod_end:
                raise QueryError("only one time-of-day window per query", pos, val)
            out.tod_start = _time(nxt(), "between")
            t = nxt(2)
            if not t or t[1].lower() != "and":
                raise QueryError(
                    "between: expected 'and' after the first time",
                    t[2] if t else None,
                    t[1] if t else None,
                )
            out.tod_end = _time(nxt(3), "between ... and")
            i += 4
        elif low in ("after", "from", "before", "until"):
            t = _time(nxt(), low)
            if low in ("after", "from"):
                if out.tod_start:
                    raise QueryError("only one time-of-day window per query", pos, val)
                out.tod_start = t
            else:
                if out.tod_end:
                    raise QueryError("only one time-of-day window per query", pos, val)
                out.tod_end = t
            i += 2
        elif low == "on":
            t = nxt()
            m = DATE_RE.match(t[1]) if t and t[0] == "word" else None
            if not m:
                if t and t[0] == "word" and re.match(r"^\d", t[1]):
                    raise QueryError("on: expected a date YYYY-MM-DD", t[2], t[1])
                i += 1  # plain English 'on' (e.g. 'person on camera 2')
                continue
            try:
                out.on_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError as e:
                raise QueryError(f"on: {e}", t[2], t[1]) from e
            i += 2
        elif low == "utc":
            out.zone = "UTC"
            i += 1
        elif low in ("tz", "timezone"):
            t = nxt()
            if not t or t[0] != "word":
                raise QueryError(
                    "tz: expected an IANA zone name such as Asia/Kolkata",
                    t[2] if t else None,
                    t[1] if t else None,
                )
            try:
                get_zone(t[1])
            except TzError as e:
                raise QueryError(str(e), t[2], t[1]) from e
            out.zone = t[1]
            i += 2
        elif low in ("confidence", "conf"):
            op, num = nxt(), nxt(2)
            if not op or op[0] != "op":
                raise QueryError(
                    "confidence: expected an operator > >= < <= = !=",
                    op[2] if op else None,
                    op[1] if op else None,
                )
            if not num or num[0] != "word" or not NUM_RE.match(num[1]):
                raise QueryError(
                    "confidence: expected a number between 0 and 1",
                    num[2] if num else None,
                    num[1] if num else None,
                )
            v = float(num[1])
            if not 0 <= v <= 1:
                raise QueryError("confidence: value must be between 0 and 1", num[2], num[1])
            out.confidence.append((op[1], v))
            i += 3
        elif low in ("placed", "unplaceable", "unplaced"):
            p = "placed" if low == "placed" else "unplaceable"
            if out.placement and out.placement != p:
                raise QueryError("placed and unplaceable cannot both be required", pos, val)
            out.placement = p
            i += 1
        elif low in STOPWORDS:
            i += 1
        else:
            cls = _class_of(low)
            if cls is None and nxt() and nxt()[0] == "word":
                cls = _class_of(f"{low}_{nxt()[1].lower()}")
                if cls:
                    i += 1
            if cls is None:
                raise QueryError(
                    f"unknown word {val!r}: not a clause keyword or detection class "
                    '(quote it for full-text search, e.g. "' + val + '")',
                    pos,
                    val,
                )
            out.classes |= cls
            i += 1
    if out.placement == "unplaceable" and out.has_time:
        raise QueryError("time-of-day/date clauses need placed clips; drop 'unplaceable'")
    return out


def match_time(q: Query, lo: datetime, hi: datetime, zone_name: str) -> str | None:
    """'within' | 'overlaps_boundary' | None for an event UTC interval [lo, hi] against the
    query's time-of-day / date window read in `zone_name` (wall clock, naive comparison)."""
    from datetime import timedelta

    zone = get_zone(zone_name)
    llo = lo.astimezone(zone).replace(tzinfo=None)
    lhi = hi.astimezone(zone).replace(tzinfo=None)
    s = q.tod_start or time(0, 0)
    e = q.tod_end or time(23, 59, 59, 999999)
    best = None
    d = llo.date() - timedelta(days=1)
    while d <= lhi.date():
        if q.on_date is None or d == q.on_date:
            ws = datetime.combine(d, s)
            we = datetime.combine(d if e >= s else d + timedelta(days=1), e)
            if ws <= lhi and llo <= we:
                if ws <= llo and lhi <= we:
                    return "within"
                best = "overlaps_boundary"
        d += timedelta(days=1)
    return best
