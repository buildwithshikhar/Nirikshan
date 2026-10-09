"""Performance analytics: computed from stored rows only; no baseline -> not available."""

import json

import pytest
from sqlalchemy import select

from app.models import CarveRun, Clip, CustodyEntry
from app.perf.analysis import DOMINANT_SHARE, run_breakdown
from tests.test_analyze import acquire, make_image
from tests.test_jobs import wait_for


@pytest.fixture
def case(client):
    return client.post("/api/cases", json={"case_number": "PERF-1", "title": "perf"}).json()


def perf(client, case):
    r = client.get(f"/api/cases/{case['id']}/performance")
    assert r.status_code == 200, r.text
    return r.json()


def test_empty_case_reports_not_available(client, case):
    p = perf(client, case)
    assert p["runs"] == [] and p["baseline_comparisons"] == []
    assert p["success_rates"] == {"available": False, "reason": "no completed runs in this case"}
    for task in ("analyze", "analytics"):
        assert p["time_saved"][task] == {"available": False, "reason": "no manual baseline entered"}


def test_breakdown_comparison_rates_and_time_saved(client, case, streams, tmp_path, session):
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    sync = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    job = wait_for(client, client.post(f"/api/evidence/{ev['id']}/jobs/analyze").json()["id"])
    assert job["status"] == "completed"
    p = perf(client, case)
    assert [r["run_id"] for r in p["runs"]] == [sync["id"], job["run_id"]]
    for r in p["runs"]:
        total = r["total_seconds"]
        assert total > 0 and r["stage_sum_exceeds_total"] is False
        assert abs(sum(s["seconds"] for s in r["stages"].values()) - total) < 1e-3
        name = max(r["stages"], key=lambda k: r["stages"][k]["seconds"])
        b = r["bottleneck"]
        assert b["stage"] == name and b["dominant"] == (b["share"] >= DOMINANT_SHARE)
        assert r["throughput_mib_per_s"] > 0
    iso = p["runs"][1]
    assert iso["isolated_worker"] is True and "worker_startup_hash_and_transfer" in iso["stages"]
    # baseline comparison: same evidence and same params -> one group, baseline = first run
    (g,) = p["baseline_comparisons"]
    assert g["baseline_run_id"] == sync["id"] and g["runs"][0]["run_id"] == job["run_id"]
    assert g["runs"][0]["ratio_to_baseline"] == pytest.approx(
        iso["total_seconds"] / p["runs"][0]["total_seconds"], rel=1e-3
    )
    # success rates equal a direct count of stored rows
    rows = session.scalars(select(Clip).where(Clip.run_id.in_([sync["id"], job["run_id"]]))).all()
    clips = [c for c in rows if c.kind == "clip"]
    orphans = [c for c in rows if c.kind == "orphan"]
    sr = p["success_rates"]
    assert sr["segment_recovery"]["numerator"] == len(clips)
    assert sr["segment_recovery"]["denominator"] == len(clips) + len(orphans)
    ok = sum(c.decode_status == "ok" for c in clips)
    assert sr["extraction_clean"]["numerator"] == ok
    assert sr["analytics_completed"]["available"] is False  # no analytics runs
    assert "not accuracy" in sr["note"]
    # time saved only once a manual baseline exists, and only against it
    assert p["time_saved"]["analyze"]["available"] is False
    r = client.post(
        f"/api/cases/{case['id']}/performance/baselines",
        json={
            "task": "analyze",
            "manual_seconds": 5400,
            "basis": "measured",
            "note": "SOP-07 timing",
        },
    )
    assert r.status_code == 201
    ts = perf(client, case)["time_saved"]
    latest = session.get(CarveRun, job["run_id"])  # latest completed run of the only evidence
    session.refresh(latest)
    from datetime import datetime

    tool = (
        datetime.fromisoformat(latest.finished_at) - datetime.fromisoformat(latest.started_at)
    ).total_seconds()
    a = ts["analyze"]
    assert a["available"] and a["tool_runs_counted"] == 1
    assert a["tool_seconds"] == pytest.approx(tool, abs=1e-5)
    assert a["time_saved_seconds"] == pytest.approx(5400 - tool, abs=1e-5)
    assert "upper bound" in a["limits"]
    assert ts["analytics"] == {"available": False, "reason": "no manual baseline entered"}
    entry = session.scalars(select(CustodyEntry).order_by(CustodyEntry.id.desc())).first()
    assert (
        entry.action == "manual_baseline_recorded"
        and json.loads(entry.details_json)["manual_seconds"] == 5400
    )


def test_baseline_validation(client, case):
    url = f"/api/cases/{case['id']}/performance/baselines"
    assert client.post(url, json={"task": "analyze", "manual_seconds": 0}).status_code == 422
    assert client.post(url, json={"task": "report", "manual_seconds": 10}).status_code == 422
    assert client.post(url, json={"task": "analytics", "manual_seconds": 10}).status_code == 201
    hist = client.get(url).json()
    assert len(hist) == 1 and hist[0]["basis"] == "estimate"
    ts = perf(client, case)["time_saved"]["analytics"]
    assert ts["available"] is False and "no completed analytics run" in ts["reason"]


def test_bottleneck_rule_on_stored_timings(client, case, session):
    """Unit check of the documented rule with explicit timings (test fixture rows)."""
    run = CarveRun(
        case_id=case["id"], evidence_id=1, status="completed", examiner="t",
        started_at="2026-10-09T00:00:00+00:00", finished_at="2026-10-09T00:00:10+00:00",
        ident_seconds=1.0, carve_seconds=6.0, stats_json=json.dumps({"parse_seconds": 2.0}),
    )  # fmt: skip
    b = run_breakdown(session, run)
    assert b["bottleneck"] == {
        "available": True, "stage": "generic_carve_and_export", "seconds": 6.0, "share": 0.6,
        "dominant": True,
    }  # fmt: skip
    assert b["stages"]["other (image verification, database, custody signing)"]["seconds"] == 1.0
    run.carve_seconds = 4.0
    b = run_breakdown(session, run)
    assert (
        b["bottleneck"]["stage"] == "generic_carve_and_export" and not b["bottleneck"]["dominant"]
    )
    run.finished_at = ""
    assert run_breakdown(session, run)["bottleneck"]["available"] is False
