"""Validation Center API under /api/validation/*. The lead registers `router` in app.main.

All read endpoints answer {"available": false, "reason": ...} when the committed results are
missing; nothing is substituted.
"""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.routes import DbSession, Examiner
from app.validation_center import rerun
from app.validation_center import results as vres
from app.validation_center.models import ValidationRerun

router = APIRouter(prefix="/api")


def _loaded() -> tuple[dict | None, dict]:
    res, info = vres.load()
    return res, info


def _unavailable(info: dict) -> dict:
    return {"available": False, "reason": info["reason"], "path": info["path"], "basis": vres.BASIS}


@router.get("/validation/summary")
def validation_summary():
    res, info = _loaded()
    return vres.summary(res, info) if res else _unavailable(info)


@router.get("/validation/scorecards")
def validation_scorecards():
    res, info = _loaded()
    if not res:
        return _unavailable(info)
    return {
        "available": True,
        "results_digest": info["results_digest"],
        "digest_verified": info["digest_verified"],
        "vendors": vres.scorecards(res),
        "basis": vres.BASIS,
    }


@router.get("/validation/regression")
def validation_regression():
    res, info = _loaded()
    if not res:
        return _unavailable(info)
    return {"available": True, "results_digest": info["results_digest"], **vres.regression(res)}


@router.get("/validation/false-rates")
def validation_false_rates():
    res, info = _loaded()
    if not res:
        return _unavailable(info)
    return {"available": True, "results_digest": info["results_digest"], **vres.false_rates(res)}


@router.get("/validation/crosscheck")
def validation_crosscheck():
    res, info = _loaded()
    if not res:
        return _unavailable(info)
    return {"available": True, "results_digest": info["results_digest"], **vres.crosscheck(res)}


class RerunIn(BaseModel):
    trials: int | None = Field(default=None, ge=1, le=50)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    export: bool = True
    scenarios: list[str] | None = Field(default=None, max_length=100)

    @field_validator("scenarios")
    @classmethod
    def _known(cls, v):
        if not v:
            return None
        from app.validation.scenarios import SCENARIOS

        known = {s.id for s in SCENARIOS}
        bad = sorted(set(v) - known)
        if bad:
            raise ValueError(f"unknown scenario id(s): {bad}")
        return sorted(set(v))


def _rerun_out(r: ValidationRerun) -> dict:
    status = r.status
    if status in ("queued", "running") and not rerun.is_active(r.id):
        status = "interrupted"  # the process that owned it is gone (restart)
    return {
        "id": r.id,
        "status": status,
        "params": json.loads(r.params_json),
        "command": json.loads(r.command_json),
        "out_dir": r.out_dir,
        "baseline_path": r.baseline_path,
        "baseline_sha256_before": r.baseline_sha256_before or None,
        "baseline_sha256_after": r.baseline_sha256_after or None,
        "baseline_unchanged": (
            r.baseline_sha256_before == r.baseline_sha256_after if r.baseline_sha256_after else None
        ),
        "baseline_digest": r.baseline_digest or None,
        "rerun_digest": r.rerun_digest or None,
        "comparison": json.loads(r.comparison_json),
        "exit_code": r.exit_code,
        "log_tail": r.log_tail,
        "error": r.error or None,
        "examiner": r.examiner,
        "created_at": r.created_at,
        "started_at": r.started_at or None,
        "finished_at": r.finished_at or None,
        "timeout_s": rerun.timeout_s(),
        "basis": vres.BASIS,
    }


@router.post("/validation/reruns", status_code=202)
def start_rerun(body: RerunIn, db: DbSession, examiner: Examiner):
    baseline, _info = vres.load()
    params = {
        "seed": body.seed if body.seed is not None else (baseline or {}).get("seed", 20260101),
        "trials": body.trials if body.trials is not None else (baseline or {}).get("trials", 20),
        "export": body.export,
        "scenarios": body.scenarios,
    }
    try:
        row = rerun.start(db, params, examiner)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return _rerun_out(row)


@router.get("/validation/reruns")
def list_reruns(db: DbSession):
    rows = db.scalars(select(ValidationRerun).order_by(ValidationRerun.id.desc()).limit(50))
    return [_rerun_out(r) for r in rows]


@router.get("/validation/reruns/{rerun_id}")
def get_rerun(rerun_id: int, db: DbSession):
    r = db.get(ValidationRerun, rerun_id)
    if r is None:
        raise HTTPException(404, "Validation re-run not found")
    db.refresh(r)
    return _rerun_out(r)
