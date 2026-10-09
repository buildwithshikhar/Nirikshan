"""Job manager: bounded thread pool driving isolated worker processes, cooperative cancel,
dependency chains, linked retries, batches and crash recovery.

Single process only (no broker, no multi-worker coordination): see docs/jobs.md and
docs/workers.md. All state transitions are conditional UPDATEs so a cancel request and a
finishing worker cannot overwrite each other. Nothing here may raise through a pool thread:
every path ends in a terminal state.

Kinds: analyze (one evidence item), analytics (one clip), analytics_run (every exported clip of
the run produced by the job it depends on). A job with `depends_on_id` waits in "queued" until
that job completes; if it fails or is cancelled, every job waiting on it (transitively) is
cancelled with the reason. A retry is a NEW job linked by `retry_of_id`; asking again returns
the same retry (idempotent), and analytics retries skip clips that already have a completed run
with identical parameters, so results are never duplicated.
"""

import hashlib
import json
import logging
import os
import threading
import time
import uuid
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


def idempotency_key(kind: str, evidence_id: int, params: dict, extra: dict | None = None) -> str:
    body = {"kind": kind, "evidence_id": evidence_id, "params": params}
    if extra:  # chains/targets; omitted for plain analyze jobs so old keys are unchanged
        body["extra"] = extra
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _carve_params(p: dict) -> CarveParams:
    return CarveParams(
        max_pad=p["max_pad"],
        h264_continuity=p["h264_continuity"],
        validate_params=p["validate_params"],
        join_gap=p["join_gap"],
    )


def new_batch_id() -> str:
    return uuid.uuid4().hex


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pool: ThreadPoolExecutor | None = None
        self._events: dict[int, threading.Event] = {}

    # ---- submission --------------------------------------------------------------------------
    def submit(
        self,
        db: Session,
        ev: Evidence,
        examiner: str,
        params: dict,
        *,
        depends_on: int | None = None,
        batch_id: str = "",
    ) -> tuple[Job, bool]:
        """Analyze job: create (or return the already active identical) job -> (job, created)."""
        if ev.status != "acquired":
            raise JobError(f"evidence {ev.id} is not acquired (status={ev.status})")
        extra = {"depends_on": depends_on} if depends_on else None
        key = idempotency_key("analyze", ev.id, params, extra)
        return self._create(
            db,
            kind="analyze",
            case_id=ev.case_id,
            evidence_id=ev.id,
            clip_id=None,
            params=params,
            examiner=examiner,
            key=key,
            depends_on=depends_on,
            batch_id=batch_id,
        )

    def submit_analytics(
        self,
        db: Session,
        clip: Clip,
        examiner: str,
        kind: str,
        params: dict,
        *,
        depends_on: int | None = None,
        batch_id: str = "",
    ) -> tuple[Job, bool]:
        if clip.kind != "clip" or not clip.mp4_path:
            raise JobError(f"clip {clip.id} has no exported MP4 to analyse")
        body = {"kind": kind, "params": params}
        key = idempotency_key(
            "analytics", clip.evidence_id, body, {"clip_id": clip.id, "depends_on": depends_on}
        )
        return self._create(
            db,
            kind="analytics",
            case_id=clip.case_id,
            evidence_id=clip.evidence_id,
            clip_id=clip.id,
            params=body,
            examiner=examiner,
            key=key,
            depends_on=depends_on,
            batch_id=batch_id,
        )

    def submit_analytics_run(
        self, db: Session, parent: Job, examiner: str, kind: str, params: dict, batch_id: str = ""
    ) -> tuple[Job, bool]:
        """Analytics over every exported clip of the run `parent` (an analyze job) produces."""
        if parent.kind != "analyze":
            raise JobError(f"job {parent.id} is a {parent.kind} job; analytics_run needs analyze")
        body = {"kind": kind, "params": params}
        key = idempotency_key("analytics_run", parent.evidence_id, body, {"depends_on": parent.id})
        return self._create(
            db,
            kind="analytics_run",
            case_id=parent.case_id,
            evidence_id=parent.evidence_id,
            clip_id=None,
            params=body,
            examiner=examiner,
            key=key,
            depends_on=parent.id,
            batch_id=batch_id or parent.batch_id,
        )

    def _create(
        self,
        db: Session,
        *,
        kind: str,
        case_id: int,
        evidence_id: int,
        clip_id: int | None,
        params: dict,
        examiner: str,
        key: str,
        depends_on: int | None,
        batch_id: str,
        retry_of: int | None = None,
        attempt: int = 1,
    ) -> tuple[Job, bool]:
        with self._lock:
            existing = db.scalars(select(Job).where(Job.active_key == key)).first()
            if existing is not None:
                return existing, False
            runnable, stage = True, "Queued"
            if depends_on is not None:
                parent = db.get(Job, depends_on)
                if parent is None or parent.case_id != case_id:
                    raise KeyError(depends_on)
                db.refresh(parent)
                if parent.status in ("failed", "cancelled"):
                    raise JobError(
                        f"dependency job {parent.id} is {parent.status}; retry it first "
                        f"(POST /api/jobs/{parent.id}/retry)"
                    )
                if parent.status != "completed":
                    runnable, stage = False, f"Waiting for job {parent.id}"
            job = Job(
                kind=kind,
                case_id=case_id,
                evidence_id=evidence_id,
                clip_id=clip_id,
                params_json=json.dumps(params, sort_keys=True),
                examiner=examiner,
                idempotency_key=key,
                active_key=key,
                depends_on_id=depends_on,
                retry_of_id=retry_of,
                attempt=attempt,
                batch_id=batch_id,
                stage=stage,
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
            if runnable:
                self._executor().submit(self._run, job.id)
        return job, True

    def retry(self, db: Session, job_id: int, examiner: str) -> tuple[Job, bool]:
        """Linked retry of a failed/cancelled job. Idempotent: an existing retry that is active
        or completed is returned instead of creating another."""
        with self._lock:
            job = db.get(Job, job_id)
            if job is None:
                raise KeyError(job_id)
            db.refresh(job)
            if job.status not in ("failed", "cancelled"):
                raise JobError(f"job {job_id} is {job.status}; only failed or cancelled jobs retry")
            prior = db.scalars(
                select(Job)
                .where(Job.retry_of_id == job_id, Job.status.not_in(("failed", "cancelled")))
                .order_by(Job.id.desc())
            ).first()
            if prior is not None:
                return prior, False
            depends_on = job.depends_on_id
            if depends_on is not None:
                depends_on = self._effective_parent(db, depends_on)
            params = json.loads(job.params_json)
            if job.kind == "analyze":
                extra = {"depends_on": depends_on} if depends_on else None
                key = idempotency_key("analyze", job.evidence_id, params, extra)
            elif job.kind == "analytics":
                extra = {"clip_id": job.clip_id, "depends_on": depends_on}
                key = idempotency_key("analytics", job.evidence_id, params, extra)
            else:
                key = idempotency_key(
                    "analytics_run", job.evidence_id, params, {"depends_on": depends_on}
                )
            return self._create(
                db,
                kind=job.kind,
                case_id=job.case_id,
                evidence_id=job.evidence_id,
                clip_id=job.clip_id,
                params=params,
                examiner=examiner,
                key=key,
                depends_on=depends_on,
                batch_id=job.batch_id,
                retry_of=job.id,
                attempt=job.attempt + 1,
            )

    def _effective_parent(self, db: Session, parent_id: int) -> int:
        """The latest attempt in the retry chain of `parent_id` (so a dependent's retry follows
        a retried dependency). _create then refuses it if that attempt failed too."""
        cur = parent_id
        while True:
            nxt = db.scalars(
                select(Job.id).where(Job.retry_of_id == cur).order_by(Job.id.desc())
            ).first()
            if nxt is None:
                return cur
            cur = nxt

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
                        "analysis_cancelled" if job.kind == "analyze" else "job_cancelled",
                        examiner,
                        {
                            "job_id": job_id,
                            "kind": job.kind,
                            "run_id": None,
                            "partial": False,
                            "completed_clips": 0,
                            "note": "cancelled while queued; no run was started",
                        },
                        job.evidence_id,
                    )
                    db.refresh(job)
                    self._after_terminal(job_id)
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

    # ---- dependencies ------------------------------------------------------------------------
    def _after_terminal(self, job_id: int) -> None:
        """Start (parent completed) or cancel (parent failed/cancelled) the jobs waiting on
        `job_id`. Never raises."""
        try:
            with self._lock, SessionLocal() as db:
                parent = db.get(Job, job_id)
                if parent is None:
                    return
                waiting = db.scalars(
                    select(Job)
                    .where(Job.depends_on_id == job_id, Job.status == "queued")
                    .order_by(Job.id)
                ).all()
                if parent.status == "completed":
                    for w in waiting:
                        db.execute(update(Job).where(Job.id == w.id).values(stage="Queued"))
                        db.commit()
                        self._events.setdefault(w.id, threading.Event())
                        self._executor().submit(self._run, w.id)
                    return
                reason = f"dependency job {parent.id} {parent.status}" + (
                    f": {parent.error[:300]}" if parent.error else ""
                )
                for w in waiting:
                    n = db.execute(
                        update(Job)
                        .where(Job.id == w.id, Job.status == "queued")
                        .values(
                            status="cancelled",
                            active_key=None,
                            stage="Cancelled: dependency did not complete",
                            error=reason[:2000],
                            finished_at=utc_now_iso(),
                        )
                    ).rowcount
                    db.commit()
                    if n:
                        custody.append_entry(
                            db,
                            w.case_id,
                            "job_cancelled",
                            w.examiner,
                            {"job_id": w.id, "kind": w.kind, "reason": reason[:2000]},
                            w.evidence_id,
                        )
                        self._after_terminal(w.id)  # transitively
        except Exception:
            log.exception("job %s: dependency handling failed", job_id)

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
            self._after_terminal(job_id)

    def _start(self, db: Session, job_id: int) -> bool:
        started = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", started_at=utc_now_iso(), stage="Starting")
        ).rowcount
        db.commit()
        return bool(started)

    def _progress_fn(self, job_id: int):
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

        return progress

    def _run_inner(self, job_id: int) -> None:
        from app.workers.isolate import isolation_enabled

        with SessionLocal() as db:
            if not self._start(db, job_id):
                return  # cancelled while queued
            job = db.get(Job, job_id)
            isolated = isolation_enabled()
            db.execute(update(Job).where(Job.id == job_id).values(isolated=isolated))
            db.commit()
            if job.kind == "analyze":
                self._run_analyze(db, job, isolated)
            elif job.kind == "analytics":
                self._run_analytics(db, job, isolated)
            elif job.kind == "analytics_run":
                self._run_analytics_run(db, job, isolated)
            else:
                self._fail(job_id, f"unknown job kind {job.kind!r}")

    def _run_analyze(self, db: Session, job: Job, isolated: bool) -> None:
        job_id = job.id
        ev = db.get(Evidence, job.evidence_id)
        p = json.loads(job.params_json)
        event = self._event(job_id)
        record: dict = {"isolated": isolated}
        t0 = time.perf_counter()

        def on_run(run: CarveRun) -> None:
            with SessionLocal() as s2:
                s2.execute(update(Job).where(Job.id == job_id).values(run_id=run.id))
                s2.commit()

        planner = None
        if isolated:
            from app.workers.pipeline import analyze_planner

            planner = analyze_planner(
                ev, p, p.get("parser_options") or {}, p.get("generic_scope", "uncovered"), record
            )
        try:
            run = analyze.analyze(
                db,
                ev,
                job.examiner,
                _carve_params(p),
                p.get("parser_options") or {},
                p.get("generic_scope", "uncovered"),
                progress=self._progress_fn(job_id),
                should_cancel=event.is_set,
                on_run=on_run,
                planner=planner,
            )
        except Exception as exc:
            db.rollback()
            record["total_s"] = round(time.perf_counter() - t0, 6)
            self._save_timings(job_id, record)
            self._fail(job_id, f"{type(exc).__name__}: {exc}")
            return
        record["total_s"] = round(time.perf_counter() - t0, 6)
        self._save_timings(job_id, record)
        status = "cancelled" if run.status == "cancelled" else "completed"
        self._finish(job_id, status, run.id, "Cancelled" if status == "cancelled" else "Done")

    def _analytics_one(self, db: Session, clip: Clip, job: Job, isolated: bool, record: dict):
        from app.analytics import runner

        body = json.loads(job.params_json)
        compute, extra = None, None
        if isolated:
            from app.workers.pipeline import analytics_compute

            compute = analytics_compute(record, should_cancel=self._event(job.id).is_set)
            extra = {"isolated_worker": True}
        return runner.run_analytics(
            db, clip, body["kind"], body.get("params"), job.examiner, compute, extra
        )

    def _run_analytics(self, db: Session, job: Job, isolated: bool) -> None:
        record: dict = {"isolated": isolated}
        t0 = time.perf_counter()
        clip = db.get(Clip, job.clip_id)
        self._write_progress(job.id, "Analysing clip", 0.05)
        try:
            run = self._analytics_one(db, clip, job, isolated, record)
        except Exception as exc:
            db.rollback()
            self._save_timings(job.id, {**record, "total_s": round(time.perf_counter() - t0, 6)})
            self._fail(job.id, f"{type(exc).__name__}: {exc}")
            return
        record["total_s"] = round(time.perf_counter() - t0, 6)
        self._save_timings(job.id, record, {"analytics_run_ids": [run.id]})
        if self._event(job.id).is_set():
            self._finish(job.id, "cancelled", None, "Cancelled")
        elif run.status != "completed":
            self._fail(job.id, f"analytics run {run.id} failed: {run.error}")
        else:
            self._finish(job.id, "completed", None, "Done")

    def _run_analytics_run(self, db: Session, job: Job, isolated: bool) -> None:
        from app.analytics.models import AnalyticsRun
        from app.analytics.runner import parse_params

        record: dict = {"isolated": isolated}
        t0 = time.perf_counter()
        parent = db.get(Job, job.depends_on_id) if job.depends_on_id else None
        if parent is None or parent.run_id is None:
            self._fail(job.id, "the analyze job this depends on produced no run")
            return
        body = json.loads(job.params_json)
        try:
            canon = json.dumps(
                parse_params(body["kind"], body.get("params")).to_dict(), sort_keys=True
            )
        except ValueError as exc:
            self._fail(job.id, f"invalid analytics parameters: {exc}")
            return
        clips = db.scalars(
            select(Clip)
            .where(Clip.run_id == parent.run_id, Clip.kind == "clip", Clip.mp4_path != "")
            .order_by(Clip.id)
        ).all()
        done_ids, skipped, failed = [], [], []
        for i, clip in enumerate(clips):
            if self._event(job.id).is_set():
                break
            already = db.scalars(
                select(AnalyticsRun.id).where(
                    AnalyticsRun.clip_id == clip.id,
                    AnalyticsRun.kind == body["kind"],
                    AnalyticsRun.params_json == canon,
                    AnalyticsRun.status == "completed",
                )
            ).first()
            if already is not None:
                skipped.append({"clip_id": clip.id, "analytics_run_id": already})
                continue
            self._write_progress(
                job.id, f"Analysing clip {i + 1} of {len(clips)}", i / max(1, len(clips))
            )
            try:
                run = self._analytics_one(db, clip, job, isolated, record)
            except Exception as exc:
                db.rollback()
                failed.append({"clip_id": clip.id, "error": f"{type(exc).__name__}: {exc}"[:500]})
                continue
            if run.status == "completed":
                done_ids.append(run.id)
            else:
                failed.append({"clip_id": clip.id, "analytics_run_id": run.id, "error": run.error})
        record["total_s"] = round(time.perf_counter() - t0, 6)
        result = {
            "analytics_run_ids": done_ids,
            "skipped_existing": skipped,
            "failed": failed,
            "clips": len(clips),
        }
        self._save_timings(job.id, record, result)
        if self._event(job.id).is_set():
            self._finish(job.id, "cancelled", None, "Cancelled")
        elif failed:
            self._fail(
                job.id, f"{len(failed)} of {len(clips)} clip analyses failed: {failed[0]['error']}"
            )
        else:
            self._finish(job.id, "completed", None, "Done")

    def _save_timings(self, job_id: int, record: dict, result: dict | None = None) -> None:
        try:
            with SessionLocal() as s2:
                vals = {"timings_json": json.dumps(record, sort_keys=True)}
                if result is not None:
                    vals["result_json"] = json.dumps(result, sort_keys=True)
                s2.execute(update(Job).where(Job.id == job_id).values(**vals))
                s2.commit()
        except Exception:
            log.exception("job %s: timing write failed", job_id)

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
                # Custody entry first, then status + error in one update, so a poller that sees
                # "failed" also finds the error and the custody entry.
                try:
                    custody.append_entry(
                        db,
                        job.case_id,
                        "analysis_job_failed" if job.kind == "analyze" else "job_failed",
                        job.examiner,
                        {
                            "job_id": job_id,
                            "kind": job.kind,
                            "run_id": job.run_id,
                            "error": message[:2000],
                        },
                        job.evidence_id,
                    )
                except Exception:
                    db.rollback()
                    log.exception("job %s: could not write the failure custody entry", job_id)
                db.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(
                        status="failed",
                        active_key=None,
                        finished_at=utc_now_iso(),
                        stage="Failed",
                        error=message[:2000],
                    )
                )
                db.commit()
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
            "analysis_job_failed" if job.kind == "analyze" else "job_failed",
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
