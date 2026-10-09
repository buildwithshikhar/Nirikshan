"""Dependency-aware job chains, linked idempotent retries and batches (isolated workers on)."""

import pytest
from sqlalchemy import func, select

from app import analyze as analyze_mod
from app.analytics.models import AnalyticsRun
from app.models import CustodyEntry
from tests.test_analyze import acquire, make_image
from tests.test_jobs import wait_for

MOTION = {"kind": "motion", "params": {}}


@pytest.fixture
def case(client):
    return client.post("/api/cases", json={"case_number": "CH-1", "title": "chains"}).json()


@pytest.fixture
def ev(client, case, streams, tmp_path):
    path, _ = make_image(streams, tmp_path)
    return acquire(client, case, path)


@pytest.fixture
def ev2(client, case, streams, tmp_path):
    d = tmp_path / "second"
    d.mkdir()
    path, _ = make_image(streams, d, extra_prefix=b"\x07" * 512)
    return acquire(client, case, path)


def _analyze(client, ev, **query):
    q = "&".join(f"{k}={v}" for k, v in query.items())
    r = client.post(f"/api/evidence/{ev['id']}/jobs/analyze" + (f"?{q}" if q else ""))
    assert r.status_code == 202, r.text
    return r.json()


def _runs(session, kind="motion"):
    return session.scalar(
        select(func.count()).select_from(AnalyticsRun).where(AnalyticsRun.kind == kind)
    )


def test_chain_runs_dependent_after_parent(client, ev, session):
    a = _analyze(client, ev)
    r = client.post(f"/api/jobs/{a['id']}/then/analytics", json=MOTION)
    assert r.status_code == 202
    b = r.json()
    assert b["depends_on"] == a["id"] and b["kind"] == "analytics_run"
    done_a = wait_for(client, a["id"])
    done_b = wait_for(client, b["id"], timeout=120)
    assert done_a["status"] == "completed" and done_b["status"] == "completed", done_b
    assert b["id"] in client.get(f"/api/jobs/{a['id']}").json()["dependents"]
    assert done_b["started_at"] >= done_a["finished_at"]
    assert len(done_b["result"]["analytics_run_ids"]) == 2 and done_b["isolated"] is True
    session.expire_all()
    assert _runs(session) == 2
    # the same chain again: nothing is analysed twice (results are never duplicated)
    again = client.post(f"/api/jobs/{a['id']}/then/analytics", json=MOTION).json()
    done = wait_for(client, again["id"], timeout=120)
    assert done["status"] == "completed" and done["result"]["analytics_run_ids"] == []
    assert len(done["result"]["skipped_existing"]) == 2
    session.expire_all()
    assert _runs(session) == 2


def test_failure_cancels_dependents_transitively_with_reason(client, ev, ev2, session, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated export crash")

    monkeypatch.setattr(analyze_mod, "export_clip", boom)
    a = _analyze(client, ev)
    b = _analyze(client, ev2, depends_on=a["id"])
    c = client.post(f"/api/jobs/{b['id']}/then/analytics", json=MOTION).json()
    assert b["waiting"] is True and c["waiting"] is True
    assert wait_for(client, a["id"])["status"] == "failed"
    db_ = wait_for(client, b["id"])
    dc = wait_for(client, c["id"])
    assert db_["status"] == "cancelled" and f"dependency job {a['id']} failed" in db_["error"]
    assert dc["status"] == "cancelled" and f"dependency job {b['id']} cancelled" in dc["error"]
    assert db_["run_id"] is None  # never started
    acts = [e.action for e in session.scalars(select(CustodyEntry).order_by(CustodyEntry.id))]
    assert acts.count("job_cancelled") == 2
    # a dependent cannot be attached to a failed job
    r = client.post(f"/api/evidence/{ev2['id']}/jobs/analyze?depends_on={a['id']}")
    assert r.status_code == 409 and "retry it first" in r.json()["detail"]


def test_retry_is_linked_idempotent_and_unblocks_dependents(client, ev, ev2, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated export crash")

    monkeypatch.setattr(analyze_mod, "export_clip", boom)
    a = _analyze(client, ev)
    b = _analyze(client, ev2, depends_on=a["id"])
    wait_for(client, a["id"])
    wait_for(client, b["id"])
    monkeypatch.undo()
    monkeypatch.setenv("NIRIKSHAN_DEV_HEADER_AUTH", "1")
    r1 = client.post(f"/api/jobs/{a['id']}/retry")
    assert r1.status_code == 202
    a2 = r1.json()
    assert a2["retry_of"] == a["id"] and a2["attempt"] == 2 and a2["existing"] is False
    again = client.post(f"/api/jobs/{a['id']}/retry").json()
    assert again["id"] == a2["id"] and again["existing"] is True
    assert wait_for(client, a2["id"])["status"] == "completed"
    assert client.post(f"/api/jobs/{a2['id']}/retry").status_code == 409  # completed
    b2 = client.post(f"/api/jobs/{b['id']}/retry").json()
    assert b2["depends_on"] == a2["id"]  # follows the retried dependency
    assert wait_for(client, b2["id"])["status"] == "completed"
    assert client.get(f"/api/jobs/{a['id']}").json()["retries"] == [a2["id"]]


def test_clip_analytics_job_and_dependency_validation(client, case, ev, session):
    a = wait_for(client, _analyze(client, ev)["id"])
    clip = client.get(f"/api/runs/{a['run_id']}").json()["clips"][0]
    r = client.post(f"/api/clips/{clip['id']}/jobs/analytics", json={"kind": "motion"})
    assert r.status_code == 202
    done = wait_for(client, r.json()["id"], timeout=120)
    assert done["status"] == "completed" and len(done["result"]["analytics_run_ids"]) == 1
    run = session.get(AnalyticsRun, done["result"]["analytics_run_ids"][0])
    assert run.status == "completed" and '"isolated_worker": true' in run.tool_json
    assert (
        client.post(f"/api/clips/{clip['id']}/jobs/analytics", json={"kind": "x"}).status_code
        == 422
    )
    r = client.post(
        f"/api/clips/{clip['id']}/jobs/analytics", json={"kind": "motion", "params": {"nope": 1}}
    )
    assert r.status_code == 422
    assert client.post(f"/api/evidence/{ev['id']}/jobs/analyze?depends_on=99999").status_code == 404
    other = client.post("/api/cases", json={"case_number": "CH-2", "title": "other"}).json()
    assert other["id"] != case["id"]


def test_batch_across_evidence_items(client, case, ev, ev2, session):
    r = client.post(
        f"/api/cases/{case['id']}/jobs/batch",
        json={"evidence_ids": [ev["id"], ev2["id"], ev["id"]], "analytics": [MOTION]},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    batch = body["batch_id"]
    kinds = [j["kind"] for j in body["jobs"]]
    assert kinds == ["analyze", "analytics_run", "analyze", "analytics_run"]
    for j in body["jobs"]:
        d = wait_for(client, j["id"], timeout=180)
        assert d["status"] == "completed", d["error"]
    s = client.get(f"/api/cases/{case['id']}/batches/{batch}").json()
    assert (
        s["done"]
        and s["ok"]
        and s["jobs"] == 4
        and s["evidence_ids"] == sorted([ev["id"], ev2["id"]])
    )
    listed = client.get(f"/api/cases/{case['id']}/jobs?batch_id={batch}").json()
    assert {j["id"] for j in listed} == {j["id"] for j in body["jobs"]}
    assert client.get(f"/api/cases/{case['id']}/batches/nope").status_code == 404
    r = client.post(f"/api/cases/{case['id']}/jobs/batch", json={"evidence_ids": [99999]})
    assert r.status_code == 404
