"""Job API. The lead registers `router` in app.main (prefix /api is built in).

POST /api/evidence/{id}/jobs/analyze -> 202 (job; `existing: true` if an identical job is active;
                                        ?depends_on=<job id> waits for that job)
POST /api/clips/{id}/jobs/analytics  -> 202 analytics job for one clip (?depends_on=)
POST /api/jobs/{id}/then/analytics   -> 202 analytics over every clip the analyze job produces
POST /api/jobs/{id}/retry            -> 202 linked retry of a failed/cancelled job (idempotent)
POST /api/cases/{id}/jobs/batch      -> 202 analyze (+ optional analytics) for several evidence
GET  /api/cases/{id}/batches/{batch} -> batch summary
GET  /api/jobs/{id}                  -> job (poll)
GET  /api/cases/{id}/jobs            -> jobs of a case (?evidence_id=, ?active=, ?batch_id=)
POST /api/jobs/{id}/cancel           -> 202 (cooperative; kills an isolated worker at once)
"""

import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.carving.export import FfmpegMissing, tool
from app.jobs.manager import JobError, manager, new_batch_id
from app.jobs.models import ACTIVE, Job
from app.models import Case, Clip, Evidence
from app.routes import DbSession, Examiner

router = APIRouter(prefix="/api")


def job_out(db: Session, job: Job, existing: bool | None = None) -> dict:
    clips = 0
    if job.run_id is not None:
        clips = db.scalar(
            select(func.count())
            .select_from(Clip)
            .where(Clip.run_id == job.run_id, Clip.kind == "clip")
        )
    out = {
        "id": job.id,
        "kind": job.kind,
        "case_id": job.case_id,
        "evidence_id": job.evidence_id,
        "params": json.loads(job.params_json),
        "status": job.status,
        "active": job.status in ACTIVE,
        "cancel_requested": job.status == "cancelling",
        "progress": round(job.progress, 4),
        "stage": job.stage,
        "run_id": job.run_id,
        "clips_recorded": clips,
        "error": job.error,
        "examiner": job.examiner,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
    out.update(
        {
            "clip_id": job.clip_id,
            "depends_on": job.depends_on_id,
            "retry_of": job.retry_of_id,
            "attempt": job.attempt,
            "batch_id": job.batch_id,
            "isolated": bool(job.isolated),
            "waiting": job.status == "queued" and job.stage.startswith("Waiting for job"),
            "timings": json.loads(job.timings_json or "{}"),
            "result": json.loads(job.result_json or "{}"),
            "dependents": list(
                db.scalars(select(Job.id).where(Job.depends_on_id == job.id).order_by(Job.id))
            ),
            "retries": list(
                db.scalars(select(Job.id).where(Job.retry_of_id == job.id).order_by(Job.id))
            ),
        }
    )
    if existing is not None:
        out["existing"] = existing
    return out


ANALYTICS_KINDS = ("motion", "objects", "faces")


class AnalyticsJobIn(BaseModel):
    kind: str = Field(description="motion | objects | faces")
    params: dict = Field(default_factory=dict)


class BatchIn(BaseModel):
    evidence_ids: list[int] = Field(min_length=1, max_length=200)
    analyze: schemas.AnalyzeIn = Field(default_factory=schemas.AnalyzeIn)
    analytics: list[AnalyticsJobIn] = Field(default_factory=list, max_length=3)


def _check_analytics_params(kind: str, params: dict) -> None:
    from app.analytics.runner import parse_params

    if kind not in ANALYTICS_KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(ANALYTICS_KINDS)}")
    try:
        parse_params(kind, params)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None


def _dependency(db: Session, depends_on: int | None, case_id: int) -> int | None:
    """A dependency must be a job of the same case (else it does not exist for this caller)."""
    if depends_on is None:
        return None
    dep = db.get(Job, depends_on)
    if dep is None or dep.case_id != case_id:
        raise HTTPException(404, "Dependency job not found")
    return dep.id


@router.post("/evidence/{evidence_id}/jobs/analyze", status_code=202)
def submit_analyze(
    evidence_id: int,
    db: DbSession,
    examiner: Examiner,
    body: schemas.AnalyzeIn | None = None,
    depends_on: Annotated[int | None, Query()] = None,
):
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    try:
        tool("ffmpeg")
        tool("ffprobe")
    except FfmpegMissing as exc:
        raise HTTPException(503, str(exc)) from exc
    params = (body or schemas.AnalyzeIn()).model_dump()
    dep = _dependency(db, depends_on, ev.case_id)
    try:
        job, created = manager.submit(db, ev, examiner, params, depends_on=dep)
    except JobError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job_out(db, job, existing=not created)


@router.post("/clips/{clip_id}/jobs/analytics", status_code=202)
def submit_clip_analytics(
    clip_id: int,
    body: AnalyticsJobIn,
    db: DbSession,
    examiner: Examiner,
    depends_on: Annotated[int | None, Query()] = None,
):
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    _check_analytics_params(body.kind, body.params)
    dep = _dependency(db, depends_on, clip.case_id)
    try:
        job, created = manager.submit_analytics(
            db, clip, examiner, body.kind, body.params, depends_on=dep
        )
    except JobError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job_out(db, job, existing=not created)


@router.post("/jobs/{job_id}/then/analytics", status_code=202)
def chain_analytics(job_id: int, body: AnalyticsJobIn, db: DbSession, examiner: Examiner):
    parent = db.get(Job, job_id)
    if parent is None:
        raise HTTPException(404, "Job not found")
    _check_analytics_params(body.kind, body.params)
    try:
        job, created = manager.submit_analytics_run(db, parent, examiner, body.kind, body.params)
    except JobError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job_out(db, job, existing=not created)


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: int, db: DbSession, examiner: Examiner):
    try:
        job, created = manager.retry(db, job_id, examiner)
    except KeyError:
        raise HTTPException(404, "Job not found") from None
    except JobError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job_out(db, job, existing=not created)


@router.post("/cases/{case_id}/jobs/batch", status_code=202)
def submit_batch(case_id: int, body: BatchIn, db: DbSession, examiner: Examiner):
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    evs = []
    for eid in dict.fromkeys(body.evidence_ids):  # de-duplicated, order kept
        ev = db.get(Evidence, eid)
        if ev is None or ev.case_id != case_id:
            raise HTTPException(404, "Evidence not found")
        if ev.status != "acquired":
            raise HTTPException(409, f"evidence {ev.id} is not acquired (status={ev.status})")
        evs.append(ev)
    for a in body.analytics:
        _check_analytics_params(a.kind, a.params)
    try:
        tool("ffmpeg")
        tool("ffprobe")
    except FfmpegMissing as exc:
        raise HTTPException(503, str(exc)) from exc
    batch = new_batch_id()
    params = body.analyze.model_dump()
    jobs = []
    try:
        for ev in evs:
            job, created = manager.submit(db, ev, examiner, params, batch_id=batch)
            jobs.append(job)
            for a in body.analytics:
                child, _ = manager.submit_analytics_run(
                    db, job, examiner, a.kind, a.params, batch_id=batch
                )
                jobs.append(child)
    except JobError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"batch_id": batch, "jobs": [job_out(db, j) for j in jobs]}


@router.get("/cases/{case_id}/batches/{batch_id}")
def batch_summary(case_id: int, batch_id: str, db: DbSession):
    jobs = db.scalars(
        select(Job).where(Job.case_id == case_id, Job.batch_id == batch_id).order_by(Job.id)
    ).all()
    if not jobs or not batch_id:
        raise HTTPException(404, "Batch not found")
    counts: dict[str, int] = {}
    for j in jobs:
        counts[j.status] = counts.get(j.status, 0) + 1
    return {
        "batch_id": batch_id,
        "case_id": case_id,
        "jobs": len(jobs),
        "by_status": counts,
        "done": all(j.status not in ACTIVE for j in jobs),
        "ok": all(j.status == "completed" for j in jobs),
        "evidence_ids": sorted({j.evidence_id for j in jobs}),
        "job_ids": [j.id for j in jobs],
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: DbSession):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job_out(db, job)


@router.get("/cases/{case_id}/jobs")
def list_case_jobs(
    case_id: int,
    db: DbSession,
    evidence_id: Annotated[int | None, Query()] = None,
    active: Annotated[bool | None, Query()] = None,
    batch_id: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    q = select(Job).where(Job.case_id == case_id).order_by(Job.id.desc()).limit(limit)
    if evidence_id is not None:
        q = q.where(Job.evidence_id == evidence_id)
    if batch_id:
        q = q.where(Job.batch_id == batch_id)
    if active is True:
        q = q.where(Job.status.in_(ACTIVE))
    elif active is False:
        q = q.where(Job.status.not_in(ACTIVE))
    return [job_out(db, j) for j in db.scalars(q)]


@router.post("/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: int, db: DbSession, examiner: Examiner):
    try:
        job = manager.cancel(db, job_id, examiner)
    except KeyError:
        raise HTTPException(404, "Job not found") from None
    except JobError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job_out(db, job)
