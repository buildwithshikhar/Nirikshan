import json
from datetime import datetime

import pytest
from sqlalchemy import select

from app.custody import verify_chain
from app.main import app
from app.models import CarveRun, Clip, CustodyEntry
from app.timeline import models as tl_models  # noqa: F401  (registers tables before create_all)
from app.timeline import routes as tl_routes

if not any(getattr(r, "path", "") == "/api/cases/{case_id}/timeline" for r in app.routes):
    app.include_router(tl_routes.router)  # the lead registers this in app.main

DHAV = "DHAV date u32 LE bit-packed (dhav.c get_timeinfo)"


def pack(y, mo, d, h, mi, s) -> int:
    return s | mi << 6 | h << 12 | d << 17 | mo << 22 | (y - 2000) << 26


def ts(name, raw, fmt=DHAV, off=16):
    return {"field": name, "offset": off, "raw": raw, "format": fmt, "tz_basis": "not assumed"}


@pytest.fixture
def case_ev(client, image):
    c = client.post("/api/cases", json={"case_number": "T-1", "title": "tl"}).json()
    ev = client.post(
        f"/api/cases/{c['id']}/evidence",
        json={"source_path": str(image), "label": "HDD", "write_blocker": "no"},
    ).json()
    return c, ev


def add_clip(session, c, ev, channel, first, last, engine="Dahua", mp4=""):
    run = session.scalars(select(CarveRun)).first()
    if run is None:
        run = CarveRun(case_id=c["id"], evidence_id=ev["id"], status="completed", examiner="x")
        session.add(run)
        session.commit()
    stamps = [ts("first frame date", pack(*first))]
    if last:
        stamps.append(ts("last frame date", pack(*last), off=99))
    clip = Clip(
        run_id=run.id, evidence_id=ev["id"], case_id=c["id"], kind="clip", seq=1, codec="h264",
        start_offset=0, end_offset=10, size_bytes=10, engine=engine, channel=channel,
        parsed_json=json.dumps({"timestamps": stamps}), mp4_path=mp4, duration_s=60.0,
    )  # fmt: skip
    session.add(clip)
    session.commit()
    return clip


def test_assumption_get_put_validation_and_custody(client, case_ev, session):
    c, ev = case_ev
    url = f"/api/evidence/{ev['id']}/time-assumption"
    g = client.get(url).json()
    assert g["set"] is False and g["tz_status"] == "unknown" and "UNKNOWN" in g["warning"]
    assert client.put(url, json={"timezone": "Mars/X", "notes": "n"}).status_code == 422
    assert client.put(url, json={"timezone": "Asia/Kolkata", "notes": " "}).status_code == 422
    assert client.put(url, json={"epoch_basis": "device_local", "notes": "n"}).status_code == 422
    assert (
        client.put(
            url, json={"timezone": "UTC", "notes": "n"}, headers={"X-Examiner": " "}
        ).status_code
        == 400
    )
    r = client.put(
        url,
        json={"timezone": "Asia/Kolkata", "evidence_kind": "device_setting_note", "notes": "menu"},
    )
    assert r.status_code == 200 and r.json()["tz_status"] == "examiner_assumed"
    assert client.get(url).json()["timezone"] == "Asia/Kolkata"
    client.put(url, json={"timezone": "UTC", "notes": "changed after photo"})
    log = [e for e in session.scalars(select(CustodyEntry)) if e.action == "time_assumption_set"]
    assert len(log) == 2
    d = json.loads(log[1].details_json)
    assert d["before"]["timezone"] == "Asia/Kolkata" and d["after"]["timezone"] == "UTC"
    assert d["after"]["notes"] == "changed after photo" and log[1].examiner == "Insp. Test"
    assert client.put("/api/evidence/999/time-assumption", json={}).status_code == 404
    assert verify_chain(session, c["id"])["ok"]


def test_references_validation_custody_and_fit(client, case_ev, session):
    c, ev = case_ev
    base = f"/api/evidence/{ev['id']}"
    ref = {
        "device_time_raw": "2025-06-01 10:00:00",
        "true_time_utc": "2025-06-01T10:01:00Z",
        "method": "photo_dvr_clock",
        "notes": "photo IMG_1 vs NTP phone",
        "photo_path": "/evidence/IMG_1.jpg",
    }
    assert client.post(f"{base}/time-model/fit").status_code == 409  # nothing recorded
    assert (
        client.post(
            f"{base}/time-references", json={**ref, "true_time_utc": "2025-06-01T10:01:00"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{base}/time-references", json={**ref, "device_time_raw": "01/06/2025"}
        ).status_code
        == 422
    )
    assert client.post(f"{base}/time-references", json={**ref, "notes": ""}).status_code == 422
    r = client.post(f"{base}/time-references", json=ref)
    assert r.status_code == 201 and r.json()["true_time_utc"].endswith("Z")
    assert client.post(f"{base}/time-model/fit").status_code == 409  # timezone not assumed
    client.put(f"{base}/time-assumption", json={"timezone": "UTC", "notes": "menu"})
    m = client.post(f"{base}/time-model/fit").json()
    assert m["method"] == "offset_only" and m["offset_s"] == 60 and m["drift_assumed_zero"]
    assert m["id"] and any("single observation" in w for w in m["warnings"])
    ref2 = {
        **ref,
        "device_time_raw": "2025-06-11 10:00:00",
        "true_time_utc": "2025-06-11T10:01:00.864Z",
    }
    client.post(f"{base}/time-references", json=ref2)
    m2 = client.post(f"{base}/time-model/fit", json={"reading_uncertainty_s": 0.5}).json()
    assert m2["method"] == "linear" and abs(m2["drift_ppm"] - 1.0) < 1e-6 and m2["id"] > m["id"]
    assert client.get(f"{base}/time-model").json()["id"] == m2["id"]
    assert len(client.get(f"{base}/time-references").json()) == 2
    actions = [e.action for e in session.scalars(select(CustodyEntry))]
    assert actions.count("time_reference_added") == 2 and actions.count("time_model_fitted") == 2
    ent = [e for e in session.scalars(select(CustodyEntry)) if e.action == "time_reference_added"][
        0
    ]
    assert json.loads(ent.details_json)["notes"] == "photo IMG_1 vs NTP phone"
    assert verify_chain(session, c["id"])["ok"]


def test_fit_refuses_ambiguous_local_reference(client, case_ev):
    c, ev = case_ev
    base = f"/api/evidence/{ev['id']}"
    client.put(f"{base}/time-assumption", json={"timezone": "Europe/Berlin", "notes": "menu"})
    client.post(
        f"{base}/time-references",
        json={"device_time_raw": "2025-10-26 02:30:00", "true_time_utc": "2025-10-26T00:30:00Z",
              "method": "known_event", "notes": "event"},
    )  # fmt: skip
    r = client.post(f"{base}/time-model/fit")
    assert r.status_code == 409 and "ambiguous" in r.json()["detail"]


def test_timeline_unknown_tz_unplaceable_then_placed_with_correction(client, case_ev, session):
    c, ev = case_ev
    add_clip(session, c, ev, 1, (2025, 6, 1, 10, 0, 0), (2025, 6, 1, 10, 5, 0))
    add_clip(session, c, ev, 2, (2025, 6, 1, 10, 3, 0), (2025, 6, 1, 10, 8, 0))
    tl = client.get(f"/api/cases/{c['id']}/timeline").json()
    assert tl["counts"]["placed"] == 0 and tl["counts"]["unplaceable"] == 2
    assert (
        tl["evidence_without_timezone"] == [ev["id"]]
        and "never defaulted" in tl["unplaceable"][0]["reason"]
    )
    assert "flags" in tl["unplaceable"][0] and "tz_unknown" in tl["unplaceable"][0]["flags"]
    assert "Synthetic-validated" in tl["disclaimer"]
    base = f"/api/evidence/{ev['id']}"
    client.put(f"{base}/time-assumption", json={"timezone": "Asia/Kolkata", "notes": "menu"})
    client.post(
        f"{base}/time-references",
        json={"device_time_raw": "2025-06-01 10:00:00", "true_time_utc": "2025-06-01T04:31:00Z",
              "method": "ntp_phone", "notes": "phone"},
    )  # fmt: skip
    mid = client.post(f"{base}/time-model/fit").json()["id"]
    tl = client.get(f"/api/cases/{c['id']}/timeline").json()
    assert tl["counts"]["placed"] == 2 and tl["evidence_without_timezone"] == []
    p = tl["placed"][0]
    assert p["start_record"]["utc_lo"] == "2025-06-01T04:30:00.000000Z"
    assert p["start_record"]["corrected_utc_lo"] > p["start_record"]["utc_lo"]
    assert p["drift_model_id"] == mid and "source_conflict" in p["flags"]
    assert tl["overlaps"] and tl["overlaps"][0]["type"] == "cross_channel"
    csvr = client.get(f"/api/cases/{c['id']}/timeline/export?format=csv")
    assert csvr.headers["content-type"].startswith("text/csv")
    head = csvr.text.splitlines()[0].split(",")
    for col in ("start_utc_lo", "start_corrected_utc_lo", "start_tz_evidence", "drift_model_id"):
        assert col in head
    js = client.get(f"/api/cases/{c['id']}/timeline/export?format=json").json()
    assert js["placed"][0]["start_record"]["tz_evidence"].startswith("examiner_entered")
    assert client.get(f"/api/cases/{c['id']}/timeline/export?format=xml").status_code == 422
    assert client.get("/api/cases/999/timeline").status_code == 404


def test_osd_check_endpoint(client, case_ev, session, tmp_path):
    from tests.test_timeline_osd import make_overlay_clip

    c, ev = case_ev
    start = datetime(2025, 6, 1, 10, 0, 0)
    mp4 = tmp_path / "ov.mp4"
    make_overlay_clip(mp4, start)
    clip = add_clip(session, c, ev, 1, (2025, 6, 1, 10, 0, 0), None, mp4=str(mp4))
    clip.duration_s = 6.0
    session.commit()
    url = f"/api/clips/{clip.id}/osd-check"
    r = client.post(url, json={"n_samples": 5, "tolerance_s": 2.0})
    assert r.status_code == 200, r.text
    # DHAV is a wall clock: comparison needs no timezone
    assert r.json()["summary"]["status"] == "pass" and r.json()["ocr"]["licence"] == "Apache-2.0"
    assert client.post(url, json={"roi": [0.0, 0.0, 2.0, 0.2]}).status_code == 422
    assert client.post(url, headers={"X-Examiner": " "}).status_code == 400
    tl = client.get(f"/api/cases/{c['id']}/timeline").json()
    assert tl["unplaceable"][0]["osd"]["status"] == "pass"  # summary joins the export rows
    assert "osd_check" in [e.action for e in session.scalars(select(CustodyEntry))]
    assert client.post("/api/clips/999/osd-check").status_code == 404
    clip2 = add_clip(session, c, ev, 2, (2025, 6, 1, 10, 0, 0), None)
    assert client.post(f"/api/clips/{clip2.id}/osd-check").status_code == 404  # no mp4
