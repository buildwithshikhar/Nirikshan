"""Background jobs: progress, cooperative cancel, crash safety, idempotent restart, recovery."""

import json
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app import analyze as analyze_mod
from app import custody
from app.config import data_dir
from app.jobs import manager as manager_mod
from app.jobs.manager import manager
from app.jobs.models import Job
from app.models import CarveRun, Clip, CustodyEntry, Evidence
from tests.test_analyze import make_image

TERMINAL = {"completed", "cancelled", "failed"}


@pytest.fixture
def ev(client, streams, tmp_path):
    case = client.post("/api/cases", json={"case_number": "JOB-1", "title": "jobs"}).json()
    path, _ = make_image(streams, tmp_path)
    r = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"source_path": str(path), "label": "synthetic", "write_blocker": "yes"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def submit(client, ev, **body):
    r = client.post(f"/api/evidence/{ev['id']}/jobs/analyze", json=body)
    assert r.status_code == 202, r.text
    return r.json()


def wait_for(client, job_id, statuses=TERMINAL, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in statuses:
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {statuses}: {j}")


class Gate:
    """Pauses the pipeline after its first exported clip (a deterministic 'slow stage')."""

    def __init__(self, monkeypatch, stray=False):
        self.first_done, self.release = threading.Event(), threading.Event()
        self.calls = 0
        self.stray = stray
        real = analyze_mod.export_clip

        def slow(f, extents, codec, out_dir, name):
            res = real(f, extents, codec, out_dir, name)
            self.calls += 1
            if self.calls == 1:
                if self.stray:  # a half-written file of the cancelled run
                    (Path(out_dir) / "generic_9999.h264").write_bytes(b"\x00\x00\x01half")
                self.first_done.set()
                assert self.release.wait(30), "test never released the gate"
            return res

        monkeypatch.setattr(analyze_mod, "export_clip", slow)

    def open(self):
        self.release.set()


def workspace(case_id) -> list[Path]:
    root = data_dir() / "cases" / str(case_id) / "clips"
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def actions(session, case_id):
    session.expire_all()
    return [
        e.action
        for e in session.scalars(
            select(CustodyEntry).where(CustodyEntry.case_id == case_id).order_by(CustodyEntry.seq)
        )
    ]


def test_job_completes_with_monotonic_progress(client, ev, monkeypatch):
    seen: list[tuple[str, float]] = []
    real = manager_mod.JobManager._write_progress

    def spy(self, job_id, stage, fraction):
        seen.append((stage, fraction))
        return real(self, job_id, stage, fraction)

    monkeypatch.setattr(manager_mod.JobManager, "_write_progress", spy)
    job = submit(client, ev)
    assert job["status"] in ("queued", "running") and job["existing"] is False
    done = wait_for(client, job["id"])
    assert done["status"] == "completed" and done["progress"] == 1.0
    assert done["run_id"] and done["clips_recorded"] == 2 and done["finished_at"]
    fractions = [f for _, f in seen]
    assert fractions == sorted(fractions) and len(fractions) >= 4
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert {s for s, _ in seen} >= {"Identifying vendor", "Finalizing run"}
    run = client.get(f"/api/runs/{done['run_id']}").json()
    assert run["status"] == "completed" and len(run["clips"]) == 2
    # the finished job stays listed; the active key is released
    listed = client.get(f"/api/cases/{ev['case_id']}/jobs").json()
    assert [j["id"] for j in listed] == [job["id"]]
    assert client.get(f"/api/cases/{ev['case_id']}/jobs?active=true").json() == []


def test_cancel_mid_run_keeps_custody_consistent_and_leaves_no_orphans(
    client, ev, monkeypatch, session
):
    gate = Gate(monkeypatch, stray=True)
    job = submit(client, ev)
    assert gate.first_done.wait(30)
    r = client.post(f"/api/jobs/{job['id']}/cancel")
    assert r.status_code == 202 and r.json()["status"] == "cancelling"
    assert r.json()["cancel_requested"] is True
    gate.open()
    done = wait_for(client, job["id"])
    assert done["status"] == "cancelled" and done["run_id"]
    assert done["clips_recorded"] == 1

    session.expire_all()
    run = session.get(CarveRun, done["run_id"])
    assert run.status == "cancelled" and run.finished_at and "cancelled" in run.error
    rows = session.scalars(select(Clip).where(Clip.run_id == run.id)).all()
    assert len(rows) == 1 and rows[0].kind == "clip" and rows[0].decode_status == "ok"
    # no orphan files: the case workspace holds exactly the recorded MP4, nothing half-written
    assert workspace(ev["case_id"]) == [Path(rows[0].mp4_path)]
    assert client.get(f"/api/clips/{rows[0].id}/video").status_code == 200
    assert client.post(f"/api/clips/{rows[0].id}/verify").json()["ok"] is True

    # custody: one analysis_cancelled entry naming the run and what completed; chain verifies
    entry = session.scalars(
        select(CustodyEntry).where(CustodyEntry.action == "analysis_cancelled")
    ).one()
    d = json.loads(entry.details_json)
    assert d["run_id"] == run.id and d["partial"] is True
    assert d["completed_clip_ids"] == [rows[0].id] and d["completed_clips"] == 1
    assert d["unrecorded_files_removed"] == ["generic_9999.h264"]
    acts = actions(session, ev["case_id"])
    assert "carve_completed" not in acts and "carve_failed" not in acts
    assert custody.verify_chain(session, ev["case_id"])["ok"] is True
    # cancelling again is refused
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 409


def test_cancel_queued_job_never_starts_a_run(client, ev, monkeypatch, session):
    monkeypatch.setenv("NIRIKSHAN_JOB_WORKERS", "1")
    gate = Gate(monkeypatch)
    first = submit(client, ev)
    assert gate.first_done.wait(30)
    second = submit(client, ev, join_gap=7)  # different request: queued behind the first
    assert second["id"] != first["id"]
    assert client.get(f"/api/jobs/{second['id']}").json()["status"] == "queued"
    r = client.post(f"/api/jobs/{second['id']}/cancel")
    assert r.json()["status"] == "cancelled" and r.json()["run_id"] is None
    gate.open()
    assert wait_for(client, first["id"])["status"] == "completed"
    time.sleep(0.2)
    assert client.get(f"/api/jobs/{second['id']}").json()["status"] == "cancelled"
    assert session.scalars(select(CarveRun)).all().__len__() == 1
    entry = session.scalars(
        select(CustodyEntry).where(CustodyEntry.action == "analysis_cancelled")
    ).one()
    assert json.loads(entry.details_json)["run_id"] is None
    assert custody.verify_chain(session, ev["case_id"])["ok"] is True


def test_identical_request_returns_active_job_and_restart_makes_a_fresh_run(
    client, ev, monkeypatch, session
):
    gate = Gate(monkeypatch)
    a = submit(client, ev)
    assert gate.first_done.wait(30)
    b = submit(client, ev)
    assert b["id"] == a["id"] and b["existing"] is True
    assert len(client.get(f"/api/cases/{ev['case_id']}/jobs").json()) == 1
    client.post(f"/api/jobs/{a['id']}/cancel")
    gate.open()
    cancelled = wait_for(client, a["id"])
    assert cancelled["status"] == "cancelled"
    old_clip_ids = {
        c.id for c in session.scalars(select(Clip).where(Clip.run_id == cancelled["run_id"]))
    }
    assert len(old_clip_ids) == 1

    # restart: fresh job, fresh run, the old partial run is left as it was (never re-used)
    c = submit(client, ev)
    assert c["id"] != a["id"] and c["existing"] is False
    done = wait_for(client, c["id"])
    assert done["status"] == "completed" and done["run_id"] != cancelled["run_id"]
    session.expire_all()
    new = session.scalars(select(Clip).where(Clip.run_id == done["run_id"])).all()
    old = session.scalars(select(Clip).where(Clip.run_id == cancelled["run_id"])).all()
    assert len(new) == 2 and {x.id for x in old} == old_clip_ids
    assert not {x.id for x in new} & old_clip_ids
    assert len({x.mp4_path for x in new} | {x.mp4_path for x in old}) == 3
    assert sorted(workspace(ev["case_id"])) == sorted(Path(x.mp4_path) for x in new + old)
    assert custody.verify_chain(session, ev["case_id"])["ok"] is True
    assert actions(session, ev["case_id"]).count("analysis_cancelled") == 1


def test_crash_marks_job_failed_and_chain_verifies(client, ev, monkeypatch, session):
    def boom(*a, **k):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(analyze_mod, "export_clip", boom)
    job = submit(client, ev)
    done = wait_for(client, job["id"])
    assert done["status"] == "failed" and "simulated crash" in done["error"]
    session.expire_all()
    run = session.get(CarveRun, done["run_id"])
    assert run.status == "failed"
    acts = actions(session, ev["case_id"])
    assert "carve_failed" in acts and "analysis_job_failed" in acts
    assert workspace(ev["case_id"]) == []
    assert custody.verify_chain(session, ev["case_id"])["ok"] is True
    # failed -> restart allowed and produces a new run
    monkeypatch.undo()
    again = wait_for(client, submit(client, ev)["id"])
    assert again["status"] == "completed" and again["run_id"] != done["run_id"]


def test_failure_path_never_raises_even_if_custody_write_fails(client, ev, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(analyze_mod, "export_clip", boom)
    real = custody.append_entry

    def flaky(db, case_id, action, *a, **k):
        if action == "analysis_job_failed":
            raise OSError("disk full")
        return real(db, case_id, action, *a, **k)

    monkeypatch.setattr(manager_mod.custody, "append_entry", flaky)
    job = submit(client, ev)
    done = wait_for(client, job["id"])
    assert done["status"] == "failed" and "simulated crash" in done["error"]


def test_startup_recovery_marks_running_jobs_failed(client, ev, session):
    run = CarveRun(case_id=ev["case_id"], evidence_id=ev["id"], status="running", examiner="x")
    session.add(run)
    session.commit()
    out = analyze_mod.clips_dir(ev["case_id"], ev["id"], run.id)
    out.mkdir(parents=True)
    kept = out / "generic_0001.mp4"
    kept.write_bytes(b"recorded")
    (out / "generic_0002.h264").write_bytes(b"half written")
    session.add(
        Clip(
            run_id=run.id, evidence_id=ev["id"], case_id=ev["case_id"], kind="clip", seq=1,
            codec="h264", start_offset=0, end_offset=1, size_bytes=1, mp4_path=str(kept),
        )
    )  # fmt: skip
    jobs = []
    for status in ("running", "cancelling", "queued"):
        key = f"k-{status}"
        j = Job(
            kind="analyze", case_id=ev["case_id"], evidence_id=ev["id"], status=status,
            examiner="Insp. Test", idempotency_key=key, active_key=key, run_id=run.id,
        )  # fmt: skip
        session.add(j)
        jobs.append(j)
    done = Job(
        kind="analyze", case_id=ev["case_id"], evidence_id=ev["id"], status="completed",
        examiner="x", idempotency_key="old", active_key=None,
    )  # fmt: skip
    session.add(done)
    session.commit()

    recovered = manager.recover(session)
    assert sorted(recovered) == sorted(j.id for j in jobs)
    session.expire_all()
    for j in jobs:
        row = session.get(Job, j.id)
        assert row.status == "failed" and row.active_key is None
        assert "restarted" in row.error and row.finished_at
    assert session.get(Job, done.id).status == "completed"
    assert session.get(CarveRun, run.id).status == "failed"
    assert [p.name for p in out.iterdir()] == ["generic_0001.mp4"]
    acts = actions(session, ev["case_id"])
    assert acts.count("analysis_job_failed") == 3 and acts.count("carve_failed") == 1
    assert custody.verify_chain(session, ev["case_id"])["ok"] is True
    assert manager.recover(session) == []  # idempotent
    # the same request can be submitted again now that the stuck job no longer blocks it
    assert wait_for(client, submit(client, ev)["id"])["status"] == "completed"


def test_startup_lifespan_runs_recovery(client, ev, session):
    from fastapi.testclient import TestClient

    from app.main import app

    key = "stuck"
    session.add(
        Job(
            kind="analyze", case_id=ev["case_id"], evidence_id=ev["id"], status="running",
            examiner="Insp. Test", idempotency_key=key, active_key=key,
        )
    )  # fmt: skip
    session.commit()
    with TestClient(app, headers={"X-Examiner": "Insp. Test"}) as c:  # runs lifespan again
        jobs = c.get(f"/api/cases/{ev['case_id']}/jobs").json()
    assert [j["status"] for j in jobs] == ["failed"]


def test_job_api_validation(client, ev, session):
    url = f"/api/evidence/{ev['id']}/jobs/analyze"
    assert client.post(url, headers={"X-Examiner": ""}).status_code == 400
    assert client.post("/api/evidence/999/jobs/analyze").status_code == 404
    assert client.post(url, json={"join_gap": -1}).status_code == 422
    assert client.get("/api/jobs/999").status_code == 404
    assert client.post("/api/jobs/999/cancel").status_code == 404
    assert client.post("/api/jobs/999/cancel", headers={"X-Examiner": ""}).status_code == 400
    assert client.get("/api/cases/999/jobs").status_code == 404
    bad = Evidence(
        case_id=ev["case_id"], label="x", source_path="/x", source_type="file",
        write_blocker="no", status="failed", examiner="x",
    )  # fmt: skip
    session.add(bad)
    session.commit()
    assert client.post(f"/api/evidence/{bad.id}/jobs/analyze").status_code == 409
    job = submit(client, ev)
    wait_for(client, job["id"])
    by_ev = client.get(f"/api/cases/{ev['case_id']}/jobs?evidence_id={ev['id']}").json()
    assert [j["id"] for j in by_ev] == [job["id"]]
    assert client.get(f"/api/cases/{ev['case_id']}/jobs?evidence_id=999").json() == []
    assert client.get(f"/api/cases/{ev['case_id']}/jobs?active=false").json()[0]["id"] == job["id"]
    # the audit log records mutations with the examiner attestation
    audit = client.get("/api/audit").json()
    assert any(a["path"].endswith("/jobs/analyze") and a["status_code"] == 202 for a in audit)


def test_sync_analyze_without_callbacks_is_unchanged(client, ev):
    r = client.post(f"/api/evidence/{ev['id']}/analyze")
    assert r.status_code == 201 and r.json()["status"] == "completed"
    assert len(r.json()["clips"]) == 2
