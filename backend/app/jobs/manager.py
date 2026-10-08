"""In-process job manager: bounded thread pool, cooperative cancel, crash recovery.

Single process only (no broker, no multi-worker coordination): see docs/jobs.md. All state
transitions are conditional UPDATEs so a cancel request and a finishing worker cannot overwrite
each other. Nothing here may raise through a worker thread: every path ends in a terminal state.
"""

import hashlib
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import analyze, custody
from app.carving.carve import CarveParams
from app.clock import utc_now_iso
from app.config import data_dir
from app.db import SessionLocal
from app.jobs.models import ACTIVE, Job
from app.models import CarveRun, Clip, Evidence

log = logging.getLogger("nirikshan.jobs")

PROGRESS_MIN_STEP = 0.005
PROGRESS_MIN_INTERVAL_S = 0.25


class JobError(Exception):
    """Caller-correctable problem (maps to HTTP 409)."""


def worker_count() -> int:
    try:
        return max(1, int(os.getenv("NIRIKSHAN_JOB_WORKERS", "2")))
    except ValueError:
        return 2


def idempotency_key(kind: str, evidence_id: int, params: dict) -> str:
    blob = json.dumps(
        {"kind": kind, "evidence_id": evidence_id, "params": params},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _carve_params(p: dict) -> CarveParams:
    return CarveParams(
        max_pad=p["max_pad"],
        h264_continuity=p["h264_continuity"],
        validate_params=p["validate_params"],
        join_gap=p["join_gap"],
    )


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pool: ThreadPoolExecutor | None = None
        self._events: dict[int, threading.Event] = {}

    # ---- submission --------------------------------------------------------------------------
    def submit(self, db: Session, ev: Evidence, examiner: str, params: dict) -> tuple[Job, bool]:
        """Create (or return the already active identical) job. Returns (job, created)."""
        if ev.status != "acquired":
            raise JobError(f"evidence {ev.id} is not acquired (status={ev.status})")
        key = idempotency_key("analyze", ev.id, params)
        with self._lock:
            existing = db.scalars(select(Job).where(Job.active_key == key)).first()
            if existing is not None:
                return existing, False
            job = Job(
                kind="analyze",
                case_id=ev.case_id,
                evidence_id=ev.id,
                params_json=json.dumps(params, sort_keys=True),
                examiner=examiner,
                idempotency_key=key,
                active_key=key,
            )
            db.add(job)
            try:
                db.commit()
            except IntegrityError:  # another process/thread won the race: return its job
                db.rollback()
                existing = db.scalars(select(Job).where(Job.active_key == key)).first()
                if existing is None:
                    raise
                return existing, False
            self._events[job.id] = threading.Event()
            self._executor().submit(self._run, job.id)
        return job, True

    def _executor(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=worker_count(), thread_name_prefix="nirikshan-job"
            )
        return self._pool

    # ---- cancellation ------------------------------------------------------------------------
    def cancel(self, db: Session, job_id: int, examiner: str) -> Job:
        with self._lock:
            job = db.get(Job, job_id)
            if job is None:
                raise KeyError(job_id)
            db.refresh(job)
            if job.status == "cancelling":
                return job
            if job.status not in ACTIVE:
                raise JobError(f"job {job_id} is already {job.status}")
            if job.status == "queued":
                n = db.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "queued")
                    .values(
                        status="cancelled",
                        active_key=None,
                        stage="Cancelled before start",
                        finished_at=utc_now_iso(),
                    )
                ).rowcount
                db.commit()
                if n:
                    self._event(job_id).set()
                    custody.append_entry(
                        db,
                        job.case_id,
                        "analysis_cancelled",
                        examiner,
                        {
                            "job_id": job_id,
                            "run_id": None,
                            "partial": False,
                            "completed_clips": 0,
                            "note": "cancelled while queued; no run was started",
                        },
                        job.evidence_id,
                    )
                    db.refresh(job)
                    return job
                db.refresh(job)  # the worker picked it up in between: fall through to running
            db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(status="cancelling", stage="Cancelling after the current step")
            )
            db.commit()
            self._event(job_id).set()
            db.refresh(job)
            return job

    def _event(self, job_id: int) -> threading.Event:
        with self._lock:
            return self._events.setdefault(job_id, threading.Event())

    # ---- worker ------------------------------------------------------------------------------
    def _run(self, job_id: int) -> None:
        try:
            self._run_inner(job_id)
        except Exception:  # last resort: never propagate out of the pool thread
            log.exception("job %s: unexpected failure in worker", job_id)
            self._fail(job_id, "internal error in worker (see server log)")
        finally:
            with self._lock:
                self._events.pop(job_id, None)

    def _run_inner(self, job_id: int) -> None:
        with SessionLocal() as db:
            started = db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "queued")
                .values(status="running", started_at=utc_now_iso(), stage="Starting")
            ).rowcount
            db.commit()
            if not started:
                return  # cancelled while queued
            job = db.get(Job, job_id)
            ev = db.get(Evidence, job.evidence_id)
            p = json.loads(job.params_json)
            event = self._event(job_id)
            last = {"f": 0.0, "t": 0.0, "stage": ""}

            def progress(stage: str, fraction: float) -> None:
                # monotonic, throttled; progress writes use their own short session
                now = time.monotonic()
                fraction = max(fraction, last["f"])
                if (
                    stage == last["stage"]
                    and fraction - last["f"] < PROGRESS_MIN_STEP
                    and now - last["t"] < PROGRESS_MIN_INTERVAL_S
                ):
                    return
                last.update(f=fraction, t=now, stage=stage)
                self._write_progress(job_id, stage, fraction)

            def on_run(run: CarveRun) -> None:
                with SessionLocal() as s2:
                    s2.execute(update(Job).where(Job.id == job_id).values(run_id=run.id))
                    s2.commit()

            try:
                run = analyze.analyze(
                    db,
                    ev,
                    job.examiner,
                    _carve_params(p),
                    p.get("parser_options") or {},
                    p.get("generic_scope", "uncovered"),
                    progress=progress,
                    should_cancel=event.is_set,
                    on_run=on_run,
                )
            except Exception as exc:
                db.rollback()
                self._fail(job_id, f"{type(exc).__name__}: {exc}")
                return
            status = "cancelled" if run.status == "cancelled" else "completed"
            self._finish(job_id, status, run.id, "Cancelled" if status == "cancelled" else "Done")

    def _write_progress(self, job_id: int, stage: str, fraction: float) -> None:
        try:
            with SessionLocal() as s2:
                s2.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status.in_(("running", "cancelling")))
                    .values(progress=fraction, stage=stage[:200])
                )
                s2.commit()
        except Exception:
            log.exception("job %s: progress write failed", job_id)

    def _finish(self, job_id: int, status: str, run_id: int | None, stage: str) -> None:
        with SessionLocal() as db:
            vals = {
                "status": status,
                "active_key": None,
                "finished_at": utc_now_iso(),
                "stage": stage,
            }
            if status == "completed":
                vals["progress"] = 1.0
            if run_id is not None:
                vals["run_id"] = run_id
            db.execute(update(Job).where(Job.id == job_id).values(**vals))
            db.commit()

    def _fail(self, job_id: int, message: str) -> None:
        """Mark failed + custody entry; swallows its own errors (never raises)."""
        try:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job is None or job.status not in ACTIVE:
                    return
                self._finish(job_id, "failed", None, "Failed")
                db.execute(update(Job).where(Job.id == job_id).values(error=message[:2000]))
                db.commit()
                custody.append_entry(
                    db,
                    job.case_id,
                    "analysis_job_failed",
                    job.examiner,
                    {"job_id": job_id, "run_id": job.run_id, "error": message[:2000]},
                    job.evidence_id,
                )
        except Exception:
            log.exception("job %s: could not record failure", job_id)

    # ---- startup recovery / shutdown ---------------------------------------------------------
    def recover(self, db: Session) -> list[int]:
        """At application startup nothing can be running: every job still queued/running/
        cancelling was lost with the previous process. Mark it failed (custody entry), mark its
        run failed and remove unrecorded files. Never raises."""
        recovered: list[int] = []
        try:
            jobs = db.scalars(select(Job).where(Job.status.in_(ACTIVE))).all()
            for job in jobs:
                try:
                    self._recover_one(db, job)
                    recovered.append(job.id)
                except Exception:
                    db.rollback()
                    log.exception("job %s: recovery failed", job.id)
            self._recover_runs(db)
        except Exception:
            db.rollback()
            log.exception("job recovery failed")
        return recovered

    def _recover_one(self, db: Session, job: Job) -> None:
        was = job.status
        msg = f"interrupted: the application restarted while the job was {was}; nothing resumed"
        job.status, job.active_key = "failed", None
        job.error, job.stage = msg, "Failed (interrupted)"
        job.finished_at = utc_now_iso()
        db.commit()
        custody.append_entry(
            db,
            job.case_id,
            "analysis_job_failed",
            job.examiner,
            {"job_id": job.id, "run_id": job.run_id, "was": was, "error": msg},
            job.evidence_id,
        )

    def _recover_runs(self, db: Session) -> None:
        for run in db.scalars(select(CarveRun).where(CarveRun.status == "running")).all():
            run.status = "failed"
            run.error = "interrupted: the application restarted during this run"
            run.finished_at = utc_now_iso()
            db.commit()
            removed = analyze.sweep_unrecorded(
                db, run, analyze.clips_dir(run.case_id, run.evidence_id, run.id)
            )
            recorded = db.scalars(
                select(Clip.id).where(Clip.run_id == run.id, Clip.kind == "clip")
            ).all()
            custody.append_entry(
                db,
                run.case_id,
                "carve_failed",
                run.examiner,
                {
                    "run_id": run.id,
                    "error": run.error,
                    "completed_clip_ids": list(recorded),
                    "unrecorded_files_removed": removed,
                },
                run.evidence_id,
            )

    def shutdown(self) -> None:
        """Ask running jobs to cancel, then wait for the pool (application shutdown)."""
        with self._lock:
            for ev in self._events.values():
                ev.set()
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


manager = JobManager()


def workspace_files(case_id: int) -> list[Path]:
    """All files under the case workspace clip tree (used by tests / diagnostics)."""
    root = data_dir() / "cases" / str(case_id) / "clips"
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []
