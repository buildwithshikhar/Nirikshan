import csv
import io
import json
from datetime import datetime, timedelta, timezone

from app.timeline import drift as D
from app.timeline import timeline as TL
from app.timeline.timestamps import TzAssumption, decode_timestamp

UTC = timezone.utc
DHAV = "DHAV date u32 LE bit-packed (dhav.c get_timeinfo)"


def pack(y, mo, d, h, mi, s) -> int:
    return s | mi << 6 | h << 12 | d << 17 | mo << 22 | (y - 2000) << 26


TZ = TzAssumption("UTC", None, "examiner_entered", "menu photo")


def recs(first, last, a=TZ, parser="Dahua"):
    out = [decode_timestamp(pack(*first), "first frame date", DHAV, 16, a, {"parser": parser})]
    if last:
        out.append(
            decode_timestamp(pack(*last), "last frame date", DHAV, 99, a, {"parser": parser})
        )
    return out


def item(cid, ev, ch, first, last, a=TZ, **kw):
    return {
        "clip_id": cid,
        "evidence_id": ev,
        "channel": ch,
        "engine": "Dahua",
        "records": recs(first, last, a),
        **kw,
    }


def test_ordering_ties_and_deterministic():
    same = (2025, 6, 1, 10, 0, 0)
    end = (2025, 6, 1, 10, 5, 0)
    items = [
        item(5, 2, 1, same, end),
        item(3, 1, 2, same, end),
        item(4, 1, 1, same, end),
        item(2, 1, None, same, end),
        item(1, 1, 1, (2025, 6, 1, 9, 0, 0), (2025, 6, 1, 9, 1, 0)),
    ]
    a = TL.build_timeline(items)
    order = [p["clip_id"] for p in a["placed"]]
    # earliest first; ties: evidence, then channel (None last), then clip id
    assert order == [1, 4, 3, 2, 5]
    assert [p["order"] for p in a["placed"]] == [1, 2, 3, 4, 5]
    assert order == [p["clip_id"] for p in TL.build_timeline(list(reversed(items)))["placed"]]
    assert 3 in a["placed"][1]["ambiguous_order_with"]  # tied bars: order not a claim


def test_gap_and_overlap_detection():
    items = [
        item(1, 1, 1, (2025, 6, 1, 10, 0, 0), (2025, 6, 1, 10, 5, 0)),
        item(2, 1, 1, (2025, 6, 1, 10, 20, 0), (2025, 6, 1, 10, 25, 0)),  # 15 min gap
        item(3, 1, 1, (2025, 6, 1, 10, 25, 0), (2025, 6, 1, 10, 30, 0)),  # contiguous
        item(4, 1, 2, (2025, 6, 1, 10, 3, 0), (2025, 6, 1, 10, 22, 0)),  # overlaps 1 and 2
        item(5, 2, 1, (2025, 6, 1, 10, 4, 0), (2025, 6, 1, 10, 6, 0)),  # other evidence
    ]
    tl = TL.build_timeline(items)
    assert len(tl["gaps"]) == 1
    g = tl["gaps"][0]
    assert (g["after_clip_id"], g["before_clip_id"], g["channel"]) == (1, 2, 1)
    assert g["gap_s_nominal"] == 900 + 0 and g["certain"] is True
    pairs = {(o["a_clip_id"], o["b_clip_id"]): o for o in tl["overlaps"]}
    assert (1, 4) in pairs and (4, 2) in pairs or (2, 4) in pairs
    assert pairs[(1, 4)]["type"] == "cross_channel" and pairs[(1, 4)]["certain"]
    assert (1, 5) in pairs or (5, 1) in pairs
    assert not any({o["a_clip_id"], o["b_clip_id"]} == {2, 3} for o in tl["overlaps"])  # touch


def test_same_channel_overlap_is_flagged_as_anomaly():
    items = [
        item(1, 1, 1, (2025, 6, 1, 10, 0, 0), (2025, 6, 1, 10, 10, 0)),
        item(2, 1, 1, (2025, 6, 1, 10, 5, 0), (2025, 6, 1, 10, 15, 0)),
    ]
    assert [o["type"] for o in TL.build_timeline(items)["overlaps"]] == ["same_channel"]


def test_unknown_timezone_is_never_placed_and_has_reason():
    items = [
        item(1, 1, 1, (2025, 6, 1, 10, 0, 0), (2025, 6, 1, 10, 5, 0), a=None),
        item(2, 2, 1, (2025, 6, 1, 10, 0, 0), (2025, 6, 1, 10, 5, 0)),
        {"clip_id": 3, "evidence_id": 2, "channel": None, "engine": "generic", "records": []},
        item(
            4,
            2,
            1,
            (2025, 3, 9, 2, 30, 0),
            None,
            a=TzAssumption("America/New_York", None, "x", "y"),
        ),
    ]
    tl = TL.build_timeline(items)
    assert [p["clip_id"] for p in tl["placed"]] == [2]
    reasons = {u["clip_id"]: u["reason"] for u in tl["unplaceable"]}
    assert "never defaulted" in reasons[1] and "no metadata timestamp" in reasons[3]
    assert "DST gap" in reasons[4]
    assert tl["counts"] == {"placed": 1, "unplaceable": 3, "gaps": 0, "overlaps": 0}


def test_dst_ambiguous_clip_gets_wide_bar_and_flag():
    a = TzAssumption("Europe/Berlin", None, "device_setting_note", "menu says CET/CEST")
    tl = TL.build_timeline([item(1, 1, 1, (2025, 10, 26, 2, 30, 0), None, a=a)])
    p = tl["placed"][0]
    assert "dst_ambiguous" in p["flags"] and "end unknown" in p["end_note"]
    lo = datetime.fromisoformat(p["start"]["lo"].replace("Z", "+00:00"))
    hi = datetime.fromisoformat(p["start"]["hi"].replace("Z", "+00:00"))
    assert hi - lo == timedelta(hours=1, seconds=1)  # envelope of both candidate instants


def test_end_from_duration_and_corrected_interval_used_on_axis():
    m = D.fit(
        [D.Observation(datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 1, 0, 1, tzinfo=UTC))]
    )
    m.id = 9
    r = recs((2025, 6, 1, 10, 0, 0), None)
    for x in r:
        D.apply_correction(x, m)
    tl = TL.build_timeline(
        [{"clip_id": 1, "evidence_id": 1, "channel": 1, "engine": "Dahua", "records": r,
          "duration_s": 60.0, "drift_model_id": 9}]
    )  # fmt: skip
    p = tl["placed"][0]
    assert p["start_record"]["utc_lo"] == "2025-06-01T10:00:00.000000Z"  # uncorrected kept
    assert p["start_record"]["corrected_utc_lo"] != p["start_record"]["utc_lo"]
    assert p["start"]["lo"] == p["start_record"]["corrected_utc_lo"]  # axis uses corrected
    assert "media duration" in p["end_note"] and p["drift_model_id"] == 9


def test_export_includes_uncertainty_columns_csv_and_json():
    m = D.fit(
        [D.Observation(datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 1, 0, 0, 5, tzinfo=UTC))]
    )
    m.id = 3
    r = recs((2025, 6, 1, 10, 0, 0), (2025, 6, 1, 10, 1, 0))
    for x in r:
        D.apply_correction(x, m)
    items = [
        {"clip_id": 1, "evidence_id": 1, "channel": 1, "engine": "Dahua", "records": r,
         "drift_model_id": 3, "osd": {"status": "pass", "median_delta_s": -0.5, "mad_s": 0.5,
                                      "readable": 6, "tolerance_s": 2.0}},
        item(2, 2, 1, (2025, 6, 1, 10, 0, 0), None, a=None),
    ]  # fmt: skip
    tl = TL.build_timeline(items)
    rows = list(csv.DictReader(io.StringIO(TL.export_csv(tl))))
    assert len(rows) == 2
    placed = next(x for x in rows if x["placement"] == "placed")
    for col in ("start_raw", "start_field", "start_format", "start_offset",
                "start_assumed_timezone", "start_tz_evidence", "tz_status", "flags",
                "start_utc_lo", "start_utc_hi",
                "start_corrected_utc_lo", "start_corrected_utc_hi", "end_corrected_utc_hi",
                "drift_model_id", "osd_median_delta_s", "osd_mad_s", "osd_status"):  # fmt: skip
        assert col in placed and placed[col] != "", col
    assert (
        placed["start_tz_evidence"].startswith("examiner_entered")
        and "source_conflict" in placed["flags"]
    )
    un = next(x for x in rows if x["placement"] == "unplaceable")
    assert "tz_unknown" in un["flags"] and un["tz_status"] == "unknown" and un["start_utc_lo"] == ""
    assert un["unplaceable_reason"]
    assert json.loads(json.dumps(tl))["placed"][0]["start_record"]["raw"] == pack(
        2025, 6, 1, 10, 0, 0
    )
