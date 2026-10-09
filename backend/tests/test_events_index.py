"""AI event index, query grammar, search and summaries (reference test data only)."""

import json

import pytest
from sqlalchemy import select

from app.analytics import TRIAGE_LABEL
from app.custody import verify_chain
from app.events import SUMMARY_LABEL, fts, grammar
from app.events.models import IndexedEvent
from app.models import CustodyEntry
from tests import stream3  # noqa: F401  (mounts routers, registers tables)
from tests.events_support import add_clip, add_detections, add_motion, new_case, set_tz


@pytest.fixture
def seeded(client, image, session):
    """Evidence 0 (Asia/Kolkata assumed): clip A ch1, clip B ch2. Evidence 1 (no timezone): C."""
    c, (ev0, ev1) = new_case(client, image, n_evidence=2)
    set_tz(client, ev0["id"])
    a = add_clip(session, c["id"], ev0["id"], 1, (2025, 6, 1, 10, 0, 0), offset=1000)
    b = add_clip(session, c["id"], ev0["id"], 2, (2025, 6, 1, 10, 0, 20), offset=9000)
    u = add_clip(session, c["id"], ev1["id"], 2, (2025, 6, 1, 10, 0, 0), offset=5000)
    add_detections(session, a, "objects", [(125, 5.0, "person", 0.9), (130, 5.2, "car", 0.4)])
    add_detections(session, b, "objects", [(50, 2.0, "person", 0.8), (75, 3.0, "person", 0.3)])
    add_detections(session, u, "objects", [(10, 0.4, "person", 0.95)])
    add_detections(session, a, "faces", [(125, 5.0, "face", 0.7)])
    add_motion(session, a, [(100, 200, 4.0, 8.0, 12.5)])
    r = client.post(f"/api/cases/{c['id']}/events/reindex")
    assert r.status_code == 200, r.text
    return c, a, b, u, r.json()


def search(client, case_id, q, **kw):
    return client.get(f"/api/cases/{case_id}/events/search", params={"q": q, **kw})


def test_reindex_counts_custody_and_idempotent(client, seeded, session):
    c, a, b, u, out = seeded
    assert out["events"] == 7
    assert out["by_kind"] == {"motion": 1, "objects": 5, "faces": 1}
    assert out["placed_events"] == 6 and out["unplaceable_events"] == 1
    assert out["fulltext_backend"] == "sqlite-fts5" and out["label"] == TRIAGE_LABEL
    ids = sorted(e.id for e in session.scalars(select(IndexedEvent)))
    again = client.post(f"/api/cases/{c['id']}/events/reindex").json()
    assert again["events"] == 7 and again["removed_stale"] == 0
    session.expire_all()
    assert sorted(e.id for e in session.scalars(select(IndexedEvent))) == ids  # stable ids
    log = [e for e in session.scalars(select(CustodyEntry)) if e.action == "ai_events_indexed"]
    assert len(log) == 2 and json.loads(log[0].details_json)["events"] == 7
    assert verify_chain(session, c["id"])["ok"]
    st = client.get(f"/api/cases/{c['id']}/events/status").json()
    assert st["events"] == 7 and st["indexed_at"]


def test_event_fields_utc_hashes_and_links(client, seeded):
    c, a, *_ = seeded
    res = search(client, c["id"], f"person clip {a.id}").json()
    assert res["total"] == 1
    h = res["hits"][0]
    # 10:00:00 Asia/Kolkata = 04:30:00Z; resolution 1 s; detection at nominal 5.0 s
    assert h["utc"]["lo"] == "2025-06-01T04:30:05.000000Z"
    assert h["utc"]["hi"] == "2025-06-01T04:30:06.000000Z"
    assert h["assumed_timezone"] == "Asia/Kolkata" and h["tz_status"] == "examiner_assumed"
    assert h["frame_index"] == 125 and h["confidence"] == 0.9 and h["camera"] == 1
    assert len(h["model"]["sha256"]) == 64 and h["clip_hashes"]["bitstream_sha256"] == "ab" * 32
    assert h["source"]["clip_start_offset"] == 1000 and h["source"]["extents"] == [[1000, 5096]]
    assert h["source"]["frame_byte_offset"]["available"] is False
    assert h["links"]["video_at"] == f"/api/clips/{a.id}/video#t=5.000"
    assert h["links"]["analytics_run"].startswith("/api/analytics/")
    assert h["label"] == TRIAGE_LABEL
    assert "x1" not in h and "bbox" not in h  # the index carries no appearance data


def test_unplaced_clip_has_no_absolute_time(client, seeded):
    c, a, b, u, _ = seeded
    h = search(client, c["id"], f"clip {u.id}").json()["hits"][0]
    assert h["placement"] == "unplaceable" and h["utc"] is None
    assert "timezone" in h["unplaceable_reason"]


def test_example_query_and_unplaceable_exclusion(client, seeded):
    c, a, b, u, _ = seeded
    res = search(client, c["id"], "person camera 2 between 10:00 and 11:00 confidence>0.5").json()
    assert [h["clip_id"] for h in res["hits"]] == [b.id]
    assert res["hits"][0]["confidence"] == 0.8 and res["hits"][0]["time_match"] == "within"
    assert res["excluded_unplaceable_clips"] == 1 and res["excluded_unplaceable_clip_ids"] == [u.id]
    assert any("excluded as unplaceable" in n for n in res["notes"])
    assert any("device-local" in i for i in res["interpreted"])
    # same window read as UTC matches nothing (10:00 IST = 04:30Z)
    assert search(client, c["id"], "person between 10:00 and 11:00 utc").json()["total"] == 0
    assert search(client, c["id"], "person between 04:00 and 05:00 utc").json()["total"] == 3
    # without time clauses the unplaced clip is included and nothing is excluded
    res = search(client, c["id"], "person").json()
    assert res["total"] == 4 and res["excluded_unplaceable_clips"] == 0


def test_time_window_edges_dates_and_midnight(client, seeded):
    c, *_ = seeded
    q = search(client, c["id"], "person between 10:00:07 and 10:00:30").json()
    assert q["total"] == 2  # clip B persons at 10:00:22/23 only
    q = search(client, c["id"], "person between 10:00:06 and 10:00:30").json()
    assert q["total"] == 3  # A's person interval 10:00:05-06 touches the edge (inclusive)
    assert [h["time_match"] for h in q["hits"]].count("overlaps_boundary") == 1
    q = search(client, c["id"], "car between 10:00:06 and 10:00:07").json()
    assert q["total"] == 1 and q["hits"][0]["time_match"] == "overlaps_boundary"
    assert search(client, c["id"], "person on 2025-06-01").json()["total"] == 3
    assert search(client, c["id"], "person on 2025-06-02").json()["total"] == 0
    assert search(client, c["id"], "person between 23:00 and 10:30").json()["total"] == 3
    assert search(client, c["id"], "person after 10:01").json()["total"] == 0
    assert search(client, c["id"], "tz Europe/London person before 06:00").json()["total"] == 3


def test_classes_kinds_motion_and_fulltext(client, seeded):
    c, a, *_ = seeded
    assert search(client, c["id"], "faces").json()["total"] == 1
    assert search(client, c["id"], "kind faces").json()["hits"][0]["class_name"] == "face"
    m = search(client, c["id"], "motion").json()["hits"][0]
    assert m["confidence"] is None and m["motion_score_peak"] == 12.5
    assert m["end_frame_index"] == 200 and m["utc"]["end_hi"] == "2025-06-01T04:30:09.000000Z"
    assert search(client, c["id"], "motion confidence>0").json()["total"] == 0
    assert search(client, c["id"], "vehicles").json()["total"] == 1
    assert search(client, c["id"], 'show all "yolox"').json()["total"] == 5
    assert search(client, c["id"], '"face detection"').json()["total"] == 1
    assert search(client, c["id"], "unplaceable").json()["total"] == 1
    assert search(client, c["id"], "person conf >= 0.8 camera 1 camera 2").json()["total"] == 3
    page = search(client, c["id"], "", limit=3, offset=3).json()
    assert page["total"] == 7 and len(page["hits"]) == 3


def test_like_fallback_matches_fts(client, seeded, monkeypatch):
    c, *_ = seeded
    want = {h["event_id"] for h in search(client, c["id"], '"yolox" "nano"').json()["hits"]}
    monkeypatch.setattr(fts, "ensure", lambda db: False)
    res = search(client, c["id"], '"yolox" "nano"').json()
    assert res["fulltext_backend"] == "like-fallback"
    assert {h["event_id"] for h in res["hits"]} == want and len(want) == 5


@pytest.mark.parametrize(
    "q,frag",
    [
        ("persn", "unknown word"),
        ("camera two", "whole number"),
        ("between 10:00 11:00", "expected 'and'"),
        ("between 25:00 and 26:00", "not a valid time"),
        ("confidence 0.5", "operator"),
        ("confidence > 2", "between 0 and 1"),
        ("tz Mars/Base person", "unknown IANA timezone"),
        ('"unterminated', "unterminated quote"),
        ("> 3", "must follow 'confidence'"),
        ("unplaceable between 10:00 and 11:00", "need placed clips"),
        ("on 2025-13-01", "on:"),
    ],
)
def test_parse_errors_list_grammar(client, seeded, q, frag):
    c, *_ = seeded
    r = search(client, c["id"], q)
    assert r.status_code == 422
    d = r.json()["detail"]
    assert frag in d["error"] and d["grammar"]["clauses"]


def test_grammar_is_deterministic_and_offline():
    a = grammar.parse("person camera 2 between 10:00 and 11:00 confidence>0.5")
    b = grammar.parse("person camera 2 between 10:00 and 11:00 confidence>0.5")
    assert a == b and a.classes == {"person"} and a.cameras == {2}
    assert a.confidence == [(">", 0.5)] and a.zone is None
    assert grammar.parse("traffic light").classes == {"traffic_light"}
    assert grammar.parse("person on camera 3").cameras == {3}
    src = open(grammar.__file__).read()
    for banned in ("http", "socket", "requests", "openai", "anthropic", "llm"):
        assert banned not in src.lower().replace("llm,", "")  # no network / model calls


def test_grammar_endpoint(client):
    g = client.get("/api/events/grammar").json()
    assert g["clauses"] and g["summary_label"] == SUMMARY_LABEL and g["label"] == TRIAGE_LABEL


def test_summaries_by_clip_and_camera(client, seeded):
    c, a, b, u, _ = seeded
    s = client.get(f"/api/cases/{c['id']}/summaries", params={"by": "clip"}).json()
    assert s["label"] == "automatic summary of triage detections"
    by = {x["group"]["clip_id"]: x for x in s["summaries"]}
    assert all(x["label"] == SUMMARY_LABEL for x in s["summaries"])
    ta = by[a.id]["text"]
    assert ta.startswith(f"Clip {a.id} (camera 1): ")
    assert "1 person detection between 5.00 s and 5.00 s of the clip" in ta
    assert "1 motion interval between 4.00 s and 8.00 s" in ta
    assert "UTC 2025-06-01T04:30:04.000000Z to 2025-06-01T04:30:09.000000Z" in ta
    assert "without absolute time" in by[u.id]["text"]
    cam = client.get(f"/api/cases/{c['id']}/summaries", params={"by": "camera"}).json()
    groups = {(x["group"]["evidence_id"], x["group"]["camera"]) for x in cam["summaries"]}
    assert len(groups) == 3
    person = next(
        k
        for x in cam["summaries"]
        if x["group"]["camera"] == 2
        for k in x["classes"]
        if k["class_name"] == "person" and k["count"] == 2
    )
    assert person["max_confidence"] == 0.8 and person["clips"] == 1


def test_reindex_follows_timezone_change_and_removed_rows(client, seeded, session):
    c, a, b, u, _ = seeded
    set_tz(client, u.evidence_id, "UTC")
    out = client.post(f"/api/cases/{c['id']}/events/reindex").json()
    assert out["unplaceable_events"] == 0
    h = search(client, c["id"], f"clip {u.id}").json()["hits"][0]
    assert h["utc"]["lo"] == "2025-06-01T10:00:00.400000Z"
    from app.analytics.models import Detection

    session.query(Detection).filter(Detection.clip_id == u.id).delete()
    session.commit()
    out = client.post(f"/api/cases/{c['id']}/events/reindex").json()
    assert out["removed_stale"] == 1 and out["events"] == 6


def test_errors_404(client):
    assert client.post("/api/cases/999/events/reindex").status_code == 404
    assert client.get("/api/cases/999/events/search").status_code == 404
    assert client.get("/api/cases/999/summaries").status_code == 404


def test_end_to_end_real_motion_run_then_index(client, image, session, tmp_path):
    """Real analytics runner (motion, no model needed) on a SYNTHETIC clip, then the hook."""
    from app.analytics import frames, runner
    from app.events import indexer
    from app.hashing import hash_file
    from tests.analytics_media import motion_clip

    mp4 = tmp_path / "m.mp4"
    motion_clip(mp4, [(20, 39), (60, 74)], n_frames=100, size=(352, 288))
    c, (ev,) = new_case(client, image, number="EV-E2E")
    set_tz(client, ev["id"], "UTC")
    clip = add_clip(session, c["id"], ev["id"], 4, (2025, 1, 2, 3, 4, 5))
    info = frames.probe(mp4)
    clip.mp4_path, clip.mp4_sha256, clip.fps = str(mp4), hash_file(mp4).sha256, info.fps_text
    clip.decode_status = "ok"
    session.commit()
    run = runner.run_analytics(session, clip, "motion", {}, "Insp. Test")
    assert run.status == "completed" and run.result_count >= 1
    out = indexer.index_after_run(session, run)
    assert out["by_kind"]["motion"] == run.result_count and out["unplaceable_events"] == 0
    hits = search(client, c["id"], "motion camera 4 between 03:04 and 03:05 utc").json()["hits"]
    assert len(hits) == run.result_count
    assert hits[0]["utc"]["lo"].startswith("2025-01-02T03:04:0")
    assert hits[0]["clip_hashes"]["mp4_sha256"] == clip.mp4_sha256


def test_analytics_endpoint_indexes_automatically(client, image, session, tmp_path):
    """POST /clips/{id}/analytics keeps the event index current without a manual reindex."""
    from app.analytics import frames
    from app.hashing import hash_file
    from tests.analytics_media import motion_clip

    mp4 = tmp_path / "auto.mp4"
    motion_clip(mp4, [(20, 39)], n_frames=100, size=(352, 288))
    c, (ev,) = new_case(client, image, number="EV-AUTO")
    set_tz(client, ev["id"], "UTC")
    clip = add_clip(session, c["id"], ev["id"], 2, (2025, 1, 2, 3, 4, 5))
    info = frames.probe(mp4)
    clip.mp4_path, clip.mp4_sha256, clip.fps = str(mp4), hash_file(mp4).sha256, info.fps_text
    clip.decode_status = "ok"
    session.commit()
    r = client.post(f"/api/clips/{clip.id}/analytics", json={"kind": "motion"})
    assert r.status_code == 201, r.text
    hits = search(client, c["id"], "motion camera 2").json()["hits"]
    assert len(hits) >= 1  # no reindex call was made
