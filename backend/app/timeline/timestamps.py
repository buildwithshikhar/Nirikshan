"""Timestamp records and decoders (P5, RESEARCH section 6).

Rules:
  * A record ALWAYS keeps the raw value, field name, format, byte offset and source, plus the
    timezone assumption used and the evidence for it.
  * The timezone is NEVER defaulted. With no examiner assumption the UTC interval is None and
    the record carries the `tz_unknown` flag (tz_status "unknown").
  * Decoding is flagged, not silent: DST ambiguity/gap, 32-bit epoch edges, invalid dates and
    the documented source conflicts per vendor are all flags on the record.
  * The UTC interval is [utc_lo, utc_hi]: the stored value has a resolution (1 s for DHAV and
    unix seconds, 1 us for Honeywell), so the instant lies in [value, value + resolution). For a
    DST-ambiguous local time the interval is the ENVELOPE of both candidate instants
    (`candidates` lists them; times strictly between the two windows are not possible).
  * Clock error (offset/drift against a reference) is NOT applied here; see drift.py, which adds
    corrected_utc_lo/hi next to the uncorrected values.

Epoch basis: Hikvision documents conflict on whether a stored unix-seconds value is true UTC
(Han 2015) or the recorder's local wall clock expressed as seconds (Dragonas, logs). The
examiner therefore states `epoch_basis`: "utc" (value is a true unix time) or "device_local"
(value = wall clock as if UTC; the device timezone is then required). With epoch_basis unset an
epoch value is only placed when the assumed timezone is exactly "UTC" (both readings agree).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1)
MAX_U32 = 0xFFFFFFFF
INT32_MAX = 0x7FFFFFFF

# Flags (stable strings; the UI and export use them verbatim).
TZ_UNKNOWN = "tz_unknown"
DST_AMBIGUOUS = "dst_ambiguous"
DST_GAP = "dst_gap"
EPOCH32_SIGNED_OVERFLOW = "epoch32_signed_overflow"
EPOCH32_U32_WRAP = "epoch32_u32_wrap"
INVALID_DATE = "invalid_date"
SOURCE_CONFLICT = "source_conflict"
UNSUPPORTED_FORMAT = "unsupported_format"
IMPLAUSIBLE_DATE = "implausible_date"

FLAG_HELP = {
    TZ_UNKNOWN: "No timezone/epoch-basis assumption entered: no UTC value is computed.",
    DST_AMBIGUOUS: "Local time occurs twice (DST fall-back): both candidate instants are kept.",
    DST_GAP: "Local time does not exist (DST spring-forward): no UTC value is computed.",
    EPOCH32_SIGNED_OVERFLOW: "Value >= 2^31: a signed 32-bit reader would see a negative time "
    "(2038 overflow). Decoded here as unsigned.",
    EPOCH32_U32_WRAP: "Value does not fit unsigned 32 bits (2106 wrap) or is the 0xFFFFFFFF "
    "sentinel/maximum.",
    INVALID_DATE: "Fields do not form a valid calendar date/time.",
    SOURCE_CONFLICT: "The public sources disagree or are silent on the time basis for this field.",
    UNSUPPORTED_FORMAT: "Format string not understood by the decoder.",
    IMPLAUSIBLE_DATE: "Decoded year is outside 1995-2100 (plausibility check only).",
}

# Documented conflicts / gaps per vendor (RESEARCH sections 2 and 6, docs/parsers/*.md).
VENDOR_CONFLICTS = {
    "hikvision": (
        "Han 2015 states Master Sector init and HIKBTREE times are UTC; Dragonas states log "
        "times are the recorder's local time zone (and his tool comments say the opposite). "
        "No single device was tested for both."
    ),
    "dahua": (
        "DHAV has no timezone field. Treating the packed date as a local wall clock is an "
        "inference from ffmpeg dhav.c (av_timegm), not a documented statement."
    ),
    "honeywell": (
        "The Honeywell paper (arXiv 2605.07430) never states whether times are UTC or local."
    ),
}

IANA_HELP = "IANA name such as 'Europe/Berlin' or 'UTC'"


class TzError(ValueError):
    pass


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise TzError(f"unknown IANA timezone {name!r} ({IANA_HELP})") from exc


def iso(dt: datetime | None) -> str | None:
    """UTC ISO-8601 with microseconds and 'Z'."""
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_iso_utc(s: str) -> datetime:
    """Parse an ISO-8601 instant; a value without an offset is rejected (never assume UTC)."""
    s = s.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError("true time must carry an explicit UTC offset (e.g. ...Z)")
    return dt.astimezone(UTC)


WALL_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?\s*$")


def parse_wall_clock(s: str) -> datetime:
    """'YYYY-MM-DD HH:MM:SS[.ffffff]' -> naive datetime. Raises ValueError on invalid dates."""
    m = WALL_RE.match(s)
    if not m:
        raise ValueError("expected wall clock 'YYYY-MM-DD HH:MM:SS' (no timezone)")
    y, mo, d, h, mi, sec = (int(m.group(i)) for i in range(1, 7))
    frac = int((m.group(7) or "0").ljust(6, "0"))
    validate_wall_clock(y, mo, d, h, mi, sec)
    return datetime(y, mo, d, h, mi, sec, frac)


def is_leap(y: int) -> bool:
    return calendar.isleap(y)  # Gregorian: 2024 leap, 2100 not


def validate_wall_clock(y: int, mo: int, d: int, h: int, mi: int, s: int) -> None:
    """Raise ValueError when the fields are not a real calendar date/time (leap days included)."""
    if not 1 <= mo <= 12:
        raise ValueError(f"month {mo} out of range")
    dim = calendar.monthrange(y, mo)[1] if 1 <= y <= 9999 else 0
    if not 1 <= d <= dim:
        raise ValueError(f"day {d} invalid for {y:04d}-{mo:02d}")
    if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59):
        raise ValueError(f"time {h:02d}:{mi:02d}:{s:02d} out of range")


@dataclass
class TzAssumption:
    """What the examiner entered for one evidence item. Nothing here is ever defaulted."""

    timezone: str | None = None  # IANA name or None
    epoch_basis: str | None = None  # "utc" | "device_local" | None
    evidence_kind: str | None = None  # "examiner_entered" | "device_setting_note"
    notes: str = ""

    @property
    def evidence_text(self) -> str:
        if not (self.timezone or self.epoch_basis):
            return "none"
        return f"{self.evidence_kind or 'examiner_entered'}: {self.notes}".strip()

    @property
    def status(self) -> str:
        return "examiner_assumed" if (self.timezone or self.epoch_basis) else "unknown"


@dataclass
class Resolution:
    """Result of localising a naive wall clock in a zone."""

    candidates: list[datetime]  # UTC instants of the start of the resolution window
    flags: list[str]


def localize(naive: datetime, tzname: str) -> Resolution:
    """Wall clock -> UTC candidate instants. 0 candidates = DST gap, 2 = ambiguous hour."""
    zone = get_zone(tzname)
    out: list[datetime] = []
    for fold in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold)
        off = local.utcoffset()
        if off is None:
            continue
        utc = (naive - off).replace(tzinfo=UTC)
        back = utc.astimezone(zone).replace(tzinfo=None)
        if back == naive and utc not in out:
            out.append(utc)
    out.sort()
    flags = []
    if len(out) == 2:
        flags.append(DST_AMBIGUOUS)
    elif not out:
        flags.append(DST_GAP)
    return Resolution(out, flags)


@dataclass
class TimestampRecord:
    raw: object
    field: str
    format: str
    offset: int
    source: dict
    wall_clock_as_stored: str = ""  # plain decode, no timezone claim
    assumed_timezone: str | None = None
    tz_evidence: str = "none"
    tz_status: str = "unknown"  # unknown | examiner_assumed
    epoch_basis: str | None = None
    resolution_s: float = 1.0
    utc_lo: datetime | None = None
    utc_hi: datetime | None = None
    candidates: list[datetime] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    conflict_note: str = ""
    # drift correction (drift.apply_correction); the uncorrected interval above is never replaced
    corrected_utc_lo: datetime | None = None
    corrected_utc_hi: datetime | None = None
    drift_model_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "field": self.field,
            "format": self.format,
            "offset": self.offset,
            "source": self.source,
            "wall_clock_as_stored": self.wall_clock_as_stored,
            "assumed_timezone": self.assumed_timezone,
            "tz_evidence": self.tz_evidence,
            "tz_status": self.tz_status,
            "epoch_basis": self.epoch_basis,
            "resolution_s": self.resolution_s,
            "utc_lo": iso(self.utc_lo),
            "utc_hi": iso(self.utc_hi),
            "candidates": [iso(c) for c in self.candidates],
            "flags": list(self.flags),
            "notes": list(self.notes),
            "conflict_note": self.conflict_note,
            "corrected_utc_lo": iso(self.corrected_utc_lo),
            "corrected_utc_hi": iso(self.corrected_utc_hi),
            "drift_model_id": self.drift_model_id,
        }

    @property
    def placeable(self) -> bool:
        return self.utc_lo is not None and self.utc_hi is not None


def decode_dhav(raw: int) -> tuple[tuple[int, ...], str]:
    """Bit fields as in dhav.c get_timeinfo: sec[0:6] min[6:12] hour[12:17] day[17:22]
    month[22:26] (year-2000)[26:32]. Returns ((y, mo, d, h, mi, s), error or '')."""
    s, mi, h = raw & 0x3F, (raw >> 6) & 0x3F, (raw >> 12) & 0x1F
    d, mo, y = (raw >> 17) & 0x1F, (raw >> 22) & 0x0F, ((raw >> 26) & 0x3F) + 2000
    try:
        validate_wall_clock(y, mo, d, h, mi, s)
        return (y, mo, d, h, mi, s), ""
    except ValueError as exc:
        return (y, mo, d, h, mi, s), str(exc)


def _kind(fmt: str) -> str:
    f = fmt.lower()
    if "dhav" in f:
        return "dhav"
    if "microsecond" in f:
        return "unix_us"
    if "unix seconds" in f:
        return "unix_s"
    return "unknown"


def _vendor_key(parser: str) -> str:
    p = (parser or "").lower()
    for key in VENDOR_CONFLICTS:
        if key in p:
            return key
    return ""


def decode_timestamp(
    raw: int,
    field_name: str,
    fmt: str,
    offset: int,
    assumption: TzAssumption | None = None,
    source: dict | None = None,
) -> TimestampRecord:
    """Decode one raw parser timestamp into a TimestampRecord (see module docstring)."""
    a = assumption or TzAssumption()
    src = dict(source or {})
    rec = TimestampRecord(
        raw=raw,
        field=field_name,
        format=fmt,
        offset=offset,
        source=src,
        assumed_timezone=a.timezone,
        tz_evidence=a.evidence_text,
        tz_status=a.status,
        epoch_basis=a.epoch_basis,
    )
    vk = _vendor_key(str(src.get("parser", "")))
    if vk:
        rec.flags.append(SOURCE_CONFLICT)
        rec.conflict_note = VENDOR_CONFLICTS[vk]
    kind = _kind(fmt)
    naive: datetime | None = None  # wall clock to localise
    instant: datetime | None = None  # true UTC instant (epoch basis utc)

    if kind == "dhav":
        fields, err = decode_dhav(int(raw))
        y, mo, d, h, mi, s = fields
        rec.wall_clock_as_stored = f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
        if err:
            rec.flags.append(INVALID_DATE)
            rec.notes.append(f"invalid DHAV date: {err}")
        else:
            naive = datetime(y, mo, d, h, mi, s)
        rec.notes.append("DHAV packed date is a wall clock (no tz field); local basis is inferred")
    elif kind in ("unix_s", "unix_us"):
        r = int(raw)
        if kind == "unix_s":
            if r > MAX_U32 or r < 0:
                rec.flags += [EPOCH32_U32_WRAP, INVALID_DATE]
                rec.notes.append("value does not fit an unsigned 32-bit seconds field")
            else:
                if r > INT32_MAX:
                    rec.flags.append(EPOCH32_SIGNED_OVERFLOW)
                    rec.notes.append(
                        "value >= 2^31 (after 2038-01-19 03:14:07 UTC if a true epoch)"
                    )
                if r == MAX_U32:
                    rec.flags.append(EPOCH32_U32_WRAP)
                    rec.notes.append(
                        "0xFFFFFFFF = max u32 (2106-02-07 06:28:15); may be a sentinel"
                    )
            secs, micros = r, 0
        else:
            rec.resolution_s = 1e-6
            secs, micros = divmod(r, 1_000_000)
        try:
            as_stored = EPOCH + timedelta(seconds=secs, microseconds=micros)
            rec.wall_clock_as_stored = as_stored.isoformat(sep=" ", timespec="seconds")
            if INVALID_DATE not in rec.flags:
                basis = a.epoch_basis
                if basis == "utc" or (basis is None and a.timezone == "UTC"):
                    instant = as_stored.replace(tzinfo=UTC)
                elif basis == "device_local" and a.timezone:
                    naive = as_stored
        except OverflowError:
            rec.flags.append(INVALID_DATE)
            rec.notes.append("value outside the representable date range")
    else:
        rec.flags.append(UNSUPPORTED_FORMAT)
        rec.notes.append(f"format {fmt!r} is not decoded")

    if INVALID_DATE in rec.flags or UNSUPPORTED_FORMAT in rec.flags:
        return rec

    plaus = naive or (instant.replace(tzinfo=None) if instant else None)
    if plaus is None:
        plaus = EPOCH + timedelta(seconds=int(raw) // (1_000_000 if kind == "unix_us" else 1))
    if not 1995 <= plaus.year <= 2100:
        rec.flags.append(IMPLAUSIBLE_DATE)

    res = timedelta(seconds=rec.resolution_s)
    if instant is not None:
        rec.utc_lo, rec.utc_hi = instant, instant + res
        if rec.assumed_timezone is None:
            rec.notes.append("epoch_basis=utc: placed on the UTC axis without a device timezone")
    elif naive is not None and a.timezone:
        try:
            r = localize(naive, a.timezone)
        except TzError as exc:
            rec.flags.append(TZ_UNKNOWN)
            rec.notes.append(str(exc))
            rec.tz_status = "unknown"
            return rec
        rec.flags += r.flags
        rec.candidates = r.candidates
        if r.candidates:
            rec.utc_lo, rec.utc_hi = r.candidates[0], r.candidates[-1] + res
        else:
            rec.notes.append("local time falls in a DST gap (nonexistent): no UTC value")
    else:
        rec.flags.append(TZ_UNKNOWN)
        rec.tz_status = "unknown"
        if kind == "unix_s" or kind == "unix_us":
            rec.notes.append(
                "epoch value not placed: set epoch_basis (utc | device_local + timezone); "
                "the sources conflict on the basis"
            )
    return rec


def decode_raw_dict(
    t: dict, assumption: TzAssumption | None, source: dict | None = None
) -> TimestampRecord:
    """Decode an `asdict(RawTimestamp)` as stored in Clip.parsed_json / CarveRun.parse_json."""
    return decode_timestamp(
        t.get("raw", 0),
        t.get("field", ""),
        t.get("format", ""),
        int(t.get("offset", 0)),
        assumption,
        source,
    )
