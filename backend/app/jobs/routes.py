"""Job API. The lead registers `router` in app.main (prefix /api is built in).

POST /api/evidence/{id}/jobs/analyze -> 202 (job; `existing: true` if an identical job is active)
GET  /api/jobs/{id}                  -> job (poll)
GET  /api/cases/{id}/jobs            -> jobs of a case (?evidence_id=, ?active=true)
POST /api/jobs/{id}/cancel           -> 202 (cooperative; stops at the next checkpoint)
"""

import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.carving.export import FfmpegMissing, tool
from app.jobs.manager import JobError, manager
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
    if existing is not None:
        out["existing"] = existing
    return out


@router.post("/evidence/{evidence_id}/jobs/analyze", status_code=202)
def submit_analyze(
    evidence_id: int, db: DbSession, examiner: Examiner, body: schemas.AnalyzeIn | None = None
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
    try:
        job, created = manager.submit(db, ev, examiner, params)
    except JobError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job_out(db, job, existing=not created)


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
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    q = select(Job).where(Job.case_id == case_id).order_by(Job.id.desc()).limit(limit)
    if evidence_id is not None:
        q = q.where(Job.evidence_id == evidence_id)
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
