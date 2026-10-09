"""Isolated worker processes: limits, scrubbed environment, network guard, crash/timeout/cancel
handling, plan validation, and equivalence with the in-process pipeline."""

import json
import sys
import time

import pytest
from sqlalchemy import select

from app.jobs.models import Job
from app.models import CarveRun, Clip
from app.workers import isolate
from app.workers.plan import PlanInvalid, PlannedSource
from tests.test_analyze import acquire, make_image
from tests.test_jobs import wait_for, workspace
from tests.test_pipeline_parser_first import dhav_bytes, pool  # noqa: F401  (fixture)

L = isolate.Limits(timeout_s=20, cpu_s=10, mem_mb=512)


def test_environment_is_scrubbed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@db/x")
    monkeypatch.setenv("NIRIKSHAN_KEY_PASSPHRASE", "do not leak")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:3128")
    out = isolate.run_task("selftest_echo", {"value": 42}, limits=L)
    assert out["result"]["echo"] == 42
    keys = set(out["result"]["env_keys"])
    assert not keys & {"DATABASE_URL", "NIRIKSHAN_KEY_PASSPHRASE", "HTTPS_PROXY"}
    applied = out["limits_applied"]
    assert applied["RLIMIT_CPU"] == "10" and applied["RLIMIT_FSIZE"] == "0"
    assert applied["RLIMIT_CORE"] == "0" and "best effort" in applied["network"]
    if sys.platform.startswith("linux"):
        assert applied["RLIMIT_AS"] == str(512 * 1024 * 1024)
    else:
        assert applied["RLIMIT_AS"] == "not enforced on this platform"


def test_network_api_is_refused_in_the_worker():
    res = isolate.run_task("selftest_socket", {}, limits=L)["result"]
    assert all(v.startswith("refused") for v in res.values()), res


def test_file_writes_are_refused_in_the_worker():
    assert isolate.run_task("selftest_write", {}, limits=L)["result"]["write"].startswith("refused")


def test_crash_raise_timeout_and_cpu_limit_are_reported():
    with pytest.raises(isolate.WorkerCrashed, match="exited with status 9"):
        isolate.run_task("selftest_crash", {"code": 9}, limits=L)
    with pytest.raises(isolate.WorkerError, match="deliberate failure"):
        isolate.run_task("selftest_raise", {}, limits=L)
    t0 = time.monotonic()
    with pytest.raises(isolate.WorkerTimeout, match="wall-clock limit of 1 s"):
        isolate.run_task("selftest_sleep", {"seconds": 30}, limits=isolate.Limits(1, 10, 512))
    assert time.monotonic() - t0 < 10
    with pytest.raises(isolate.WorkerCrashed, match="SIGXCPU|SIGKILL"):
        isolate.run_task("selftest_cpu", {}, limits=isolate.Limits(30, 1, 512))
    with pytest.raises(isolate.WorkerError, match="unknown worker task"):
        isolate.run_task("no_such_task", {}, limits=L)


def test_memory_limit_is_enforced():
    """Linux: RLIMIT_AS (MemoryError inside the worker). macOS: the parent's RSS watchdog."""
    lim = isolate.Limits(timeout_s=30, cpu_s=30, mem_mb=200)
    try:
        out = isolate.run_task("selftest_alloc", {"mb": 700, "hold": 3}, limits=lim)
    except isolate.WorkerCrashed as exc:
        assert "memory limit" in str(exc) or "SIGKILL" in str(exc)
    else:
        assert out["result"]["alloc"].startswith("refused"), out


def test_cancel_kills_the_worker_promptly():
    flag = {"stop": False}
    t0 = time.monotonic()

    def cancel():
        if time.monotonic() - t0 > 0.5:
            flag["stop"] = True
        return flag["stop"]

    with pytest.raises(isolate.WorkerCancelled):
        isolate.run_task("selftest_sleep", {"seconds": 30}, limits=L, should_cancel=cancel)
    assert time.monotonic() - t0 < 5


# ---- plan validation ------------------------------------------------------------------------
def _plan(**over):
    base = {
        "size": 1000,
        "sha256": "a" * 64,
        "matches": [],
        "parsed": [],
        "ranges": [[0, 1000]],
        "generic": [{"type": "clip", "codec": "h264", "extents": [[10, 20]]}],
        "full_generic": [],
        "timings": {},
    }
    return {**base, **over}


def test_plan_validation_rejects_bad_worker_output():
    PlannedSource(_plan(), 1000, "a" * 64)  # well-formed
    with pytest.raises(PlanInvalid, match="different bytes"):
        PlannedSource(_plan(), 1000, "b" * 64)
    with pytest.raises(PlanInvalid, match="outside the image"):
        PlannedSource(
            _plan(generic=[{"type": "clip", "codec": "h264", "extents": [[990, 2000]]}]),
            1000,
            "a" * 64,
        )
    with pytest.raises(PlanInvalid, match="unknown codec"):
        PlannedSource(
            _plan(generic=[{"type": "clip", "codec": "evil", "extents": [[1, 2]]}]), 1000, "a" * 64
        )
    with pytest.raises(PlanInvalid, match="extents"):
        PlannedSource(
            _plan(generic=[{"type": "clip", "codec": "h264", "extents": "x"}]), 1000, "a" * 64
        )
    with pytest.raises(PlanInvalid, match="line up"):
        PlannedSource(_plan(parsed=[None]), 1000, "a" * 64)
    src = PlannedSource(_plan(), 1000, "a" * 64)
    with pytest.raises(PlanInvalid, match="different ranges"):
        src.generic([(0, 500)])


# ---- jobs through isolated workers ------------------------------------------------------------
@pytest.fixture
def case(client):
    return client.post("/api/cases", json={"case_number": "W-1", "title": "workers"}).json()


def _clip_signature(session, run_id):
    rows = session.scalars(
        select(Clip).where(Clip.run_id == run_id).order_by(Clip.kind, Clip.engine, Clip.seq)
    ).all()
    return [
        (
            c.kind,
            c.engine,
            c.seq,
            c.codec,
            c.extents_json,
            c.bitstream_sha256,
            c.decode_status,
            c.parsed_json,
        )
        for c in rows
    ]


def test_isolated_job_equals_in_process_run(client, case, streams, pool, tmp_path, session):  # noqa: F811
    """Parser + generic image: the isolated plan stores exactly what the in-process run stores."""
    from tests.media import filler

    img = filler(2000, 1) + dhav_bytes(pool.get("h264_base_320"), channel=4) + b"\x00" * 128
    img += streams["h264_high"] + b"\x00" * 128
    p = tmp_path / "mixed.dd"
    p.write_bytes(img)
    ev = acquire(client, case, p)
    sync = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    job = client.post(f"/api/evidence/{ev['id']}/jobs/analyze").json()
    done = wait_for(client, job["id"])
    assert done["status"] == "completed" and done["isolated"] is True, done
    session.expire_all()
    assert _clip_signature(session, sync["id"]) == _clip_signature(session, done["run_id"])
    a, b = session.get(CarveRun, sync["id"]), session.get(CarveRun, done["run_id"])
    pa, pb = json.loads(a.parse_json), json.loads(b.parse_json)
    assert pa == pb and pa  # parser output and cross-check identical
    sa, sb = json.loads(a.stats_json), json.loads(b.stats_json)
    assert sb["isolated_worker"] is True and sa["isolated_worker"] is False
    assert set(sb["worker_timings"]) >= {"worker_hash", "identify", "parse", "carve"}
    assert {k: sa[k] for k in ("clips", "orphans", "ok")} == {
        k: sb[k] for k in ("clips", "orphans", "ok")
    }
    assert done["timings"]["worker_wall_s"] > 0 and done["timings"]["limits_applied"]


def _swap_task(monkeypatch, task, payload=None, limits=None):
    real = isolate.run_task

    def fake(_task, _payload, **kw):
        if limits is not None:
            kw["limits"] = limits
        return real(task, payload or {}, **kw)

    monkeypatch.setattr(isolate, "run_task", fake)


@pytest.mark.parametrize(
    "task,payload,limits,expect",
    [
        ("selftest_crash", {"code": 7}, None, "WorkerCrashed: worker exited with status 7"),
        ("selftest_sleep", {"seconds": 30}, isolate.Limits(1, 10, 512), "WorkerTimeout"),
        (
            "selftest_raise",
            {"message": "parser blew up"},
            None,
            "WorkerError: ValueError: parser blew up",
        ),
    ],
)
def test_worker_failure_fails_job_cleanly_with_no_partial_rows(
    client, case, streams, tmp_path, session, monkeypatch, task, payload, limits, expect
):
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    _swap_task(monkeypatch, task, payload, limits)
    job = client.post(f"/api/evidence/{ev['id']}/jobs/analyze").json()
    done = wait_for(client, job["id"])
    assert done["status"] == "failed" and expect in done["error"], done
    session.expire_all()
    run = session.get(CarveRun, done["run_id"])
    assert run.status == "failed" and expect.split(":")[0] in run.error
    assert session.scalars(select(Clip).where(Clip.run_id == run.id)).all() == []
    assert workspace(case["id"]) == []
    assert client.get(f"/api/cases/{case['id']}/custody/verify").json()["ok"]


def test_cancel_during_worker_phase(client, case, streams, tmp_path, session, monkeypatch):
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    _swap_task(monkeypatch, "selftest_sleep", {"seconds": 60})
    job = client.post(f"/api/evidence/{ev['id']}/jobs/analyze").json()
    deadline = time.monotonic() + 20
    while client.get(f"/api/jobs/{job['id']}").json()["status"] != "running":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    time.sleep(0.3)
    t0 = time.monotonic()
    client.post(f"/api/jobs/{job['id']}/cancel")
    done = wait_for(client, job["id"])
    assert done["status"] == "cancelled" and time.monotonic() - t0 < 10
    session.expire_all()
    assert session.get(Job, job["id"]).run_id is not None
    assert session.scalars(select(Clip).where(Clip.run_id == done["run_id"])).all() == []


def test_isolation_can_be_disabled(client, case, streams, tmp_path, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_ISOLATE_JOBS", "0")
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    done = wait_for(client, client.post(f"/api/evidence/{ev['id']}/jobs/analyze").json()["id"])
    assert done["status"] == "completed" and done["isolated"] is False


def test_worker_selftest_cli(capsys):
    from app import cli

    assert cli.main(["worker-selftest"]) == 0
    out = capsys.readouterr().out
    assert "network" in out and "RLIMIT_FSIZE" in out
