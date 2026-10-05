from datetime import datetime, timedelta, timezone

import pytest

from app.timeline import timestamps as T
from app.timeline.timestamps import TzAssumption, decode_timestamp

UTC = timezone.utc
DHAV = "DHAV date u32 LE bit-packed (dhav.c get_timeinfo)"
UNIX_S = "unix seconds (u32 LE)"
UNIX_US = "unix microseconds (u64 LE)"


def pack(y, mo, d, h, mi, s) -> int:
    return s | mi << 6 | h << 12 | d << 17 | mo << 22 | (y - 2000) << 26


def A(tz=None, basis=None):
    return (
        TzAssumption(tz, basis, "examiner_entered", "setup menu photo") if (tz or basis) else None
    )


def dh(raw, a=None, parser="Dahua"):
    return decode_timestamp(raw, "first frame date", DHAV, 16, a, {"parser": parser})


def test_unknown_timezone_never_defaulted_and_flagged():
    r = dh(pack(2025, 6, 1, 12, 0, 0))
    assert r.utc_lo is None and r.utc_hi is None
    assert T.TZ_UNKNOWN in r.flags and r.tz_status == "unknown" and r.assumed_timezone is None
    assert r.tz_evidence == "none"
    assert r.wall_clock_as_stored == "2025-06-01 12:00:00"
    d = r.to_dict()
    assert d["utc_lo"] is None and d["raw"] == pack(2025, 6, 1, 12, 0, 0) and d["offset"] == 16


def test_dhav_with_timezone_gives_one_second_interval_and_keeps_evidence():
    r = dh(pack(2025, 1, 15, 10, 30, 0), A("Asia/Kolkata"))
    assert r.utc_lo == datetime(2025, 1, 15, 5, 0, 0, tzinfo=UTC)
    assert r.utc_hi - r.utc_lo == timedelta(seconds=1)
    assert r.tz_status == "examiner_assumed" and "setup menu photo" in r.tz_evidence
    assert T.SOURCE_CONFLICT in r.flags and "inference" in r.conflict_note


def test_dst_ambiguous_hour_berlin_two_candidates():
    r = dh(pack(2025, 10, 26, 2, 30, 0), A("Europe/Berlin"))
    assert T.DST_AMBIGUOUS in r.flags
    assert r.candidates == [
        datetime(2025, 10, 26, 0, 30, tzinfo=UTC),  # CEST (+2)
        datetime(2025, 10, 26, 1, 30, tzinfo=UTC),  # CET (+1)
    ]
    assert r.utc_lo == r.candidates[0] and r.utc_hi == r.candidates[1] + timedelta(seconds=1)


def test_dst_gap_new_york_is_invalid_local_and_unplaced():
    r = dh(pack(2025, 3, 9, 2, 30, 0), A("America/New_York"))
    assert T.DST_GAP in r.flags and r.utc_lo is None and r.candidates == []
    assert T.TZ_UNKNOWN not in r.flags  # the zone is known; the local time is invalid


def test_unambiguous_time_next_to_dst_change():
    r = dh(pack(2025, 10, 26, 3, 30, 0), A("Europe/Berlin"))
    assert r.flags == [T.SOURCE_CONFLICT] and r.utc_lo == datetime(2025, 10, 26, 2, 30, tzinfo=UTC)


def test_leap_day_valid_and_invalid():
    ok = dh(pack(2024, 2, 29, 12, 0, 0), A("UTC"))
    assert T.INVALID_DATE not in ok.flags and ok.utc_lo == datetime(2024, 2, 29, 12, tzinfo=UTC)
    bad = dh(pack(2023, 2, 29, 12, 0, 0), A("UTC"))
    assert T.INVALID_DATE in bad.flags and bad.utc_lo is None
    T.validate_wall_clock(2024, 2, 29, 0, 0, 0)
    with pytest.raises(ValueError):
        T.validate_wall_clock(2100, 2, 29, 0, 0, 0)  # 2100 is not a leap year
    T.validate_wall_clock(2000, 2, 29, 0, 0, 0)  # 2000 is


@pytest.mark.parametrize(
    "fields",
    [(2025, 13, 1, 0, 0, 0), (2025, 0, 1, 0, 0, 0), (2025, 4, 31, 0, 0, 0), (2025, 4, 1, 24, 0, 0),
     (2025, 4, 1, 0, 60, 0), (2025, 4, 1, 0, 0, 60), (2025, 4, 0, 0, 0, 0)],
)  # fmt: skip
def test_dhav_range_validation(fields):
    r = dh(pack(*fields), A("UTC"))
    assert T.INVALID_DATE in r.flags and r.utc_lo is None and r.notes


def test_unix_seconds_epoch_basis_required_unless_utc_zone():
    raw = 1_750_000_000
    none = decode_timestamp(raw, "t", UNIX_S, 0, None, {"parser": "Hikvision"})
    assert none.utc_lo is None and T.TZ_UNKNOWN in none.flags
    assert T.SOURCE_CONFLICT in none.flags and "Dragonas" in none.conflict_note
    tz_only = decode_timestamp(raw, "t", UNIX_S, 0, A("Asia/Kolkata"), {})
    assert tz_only.utc_lo is None and T.TZ_UNKNOWN in tz_only.flags  # basis not stated
    as_utc = decode_timestamp(raw, "t", UNIX_S, 0, A(None, "utc"), {})
    assert as_utc.utc_lo == datetime.fromtimestamp(raw, UTC)
    local = decode_timestamp(raw, "t", UNIX_S, 0, A("Asia/Kolkata", "device_local"), {})
    assert local.utc_lo == datetime.fromtimestamp(raw, UTC) - timedelta(hours=5, minutes=30)
    utc_zone = decode_timestamp(raw, "t", UNIX_S, 0, A("UTC"), {})
    assert utc_zone.utc_lo == as_utc.utc_lo


def test_epoch32_edges():
    def d(v):
        return decode_timestamp(v, "t", UNIX_S, 0, A(None, "utc"), {})

    last_signed = d(0x7FFFFFFF)
    assert last_signed.utc_lo == datetime(2038, 1, 19, 3, 14, 7, tzinfo=UTC)
    assert T.EPOCH32_SIGNED_OVERFLOW not in last_signed.flags
    over = d(0x80000000)
    assert over.utc_lo == datetime(2038, 1, 19, 3, 14, 8, tzinfo=UTC)  # unsigned decode
    assert T.EPOCH32_SIGNED_OVERFLOW in over.flags
    top = d(0xFFFFFFFF)
    assert top.utc_lo == datetime(2106, 2, 7, 6, 28, 15, tzinfo=UTC)
    assert T.EPOCH32_U32_WRAP in top.flags and T.EPOCH32_SIGNED_OVERFLOW in top.flags
    wrapped = d(0x1_0000_0000)
    assert T.EPOCH32_U32_WRAP in wrapped.flags and wrapped.utc_lo is None
    assert T.INVALID_DATE in wrapped.flags


def test_honeywell_microseconds_resolution_and_conflict():
    raw = 1_750_000_000_123_456
    r = decode_timestamp(raw, "frame time", UNIX_US, 8, A(None, "utc"), {"parser": "Honeywell"})
    assert r.utc_lo == datetime.fromtimestamp(1_750_000_000, UTC) + timedelta(microseconds=123456)
    assert r.utc_hi - r.utc_lo == timedelta(microseconds=1)
    assert T.SOURCE_CONFLICT in r.flags and "never states" in r.conflict_note
    huge = decode_timestamp(2**63, "x", UNIX_US, 0, A(None, "utc"), {})
    assert T.INVALID_DATE in huge.flags and huge.utc_lo is None


def test_unsupported_format_and_implausible_year():
    r = decode_timestamp(5, "x", "mystery", 0, A("UTC"), {})
    assert T.UNSUPPORTED_FORMAT in r.flags and r.utc_lo is None
    old = decode_timestamp(100, "x", UNIX_S, 0, A(None, "utc"), {})
    assert T.IMPLAUSIBLE_DATE in old.flags and old.utc_lo is not None


def test_bad_timezone_name_is_flagged_not_defaulted():
    r = dh(pack(2025, 6, 1, 0, 0, 0), TzAssumption("Mars/Olympus", None, "examiner_entered", "x"))
    assert r.utc_lo is None and T.TZ_UNKNOWN in r.flags and r.tz_status == "unknown"
    with pytest.raises(T.TzError):
        T.get_zone("Mars/Olympus")


def test_wall_clock_and_iso_parsers():
    assert T.parse_wall_clock("2025-03-09 02:30:00.5") == datetime(2025, 3, 9, 2, 30, 0, 500000)
    with pytest.raises(ValueError):
        T.parse_wall_clock("2025-02-30 00:00:00")
    with pytest.raises(ValueError):
        T.parse_wall_clock("09/03/2025 02:30")
    assert T.parse_iso_utc("2025-01-01T00:00:00Z") == datetime(2025, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        T.parse_iso_utc("2025-01-01T00:00:00")  # no offset: never assume UTC
