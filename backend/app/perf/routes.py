"""Performance analytics API (prefix /api). Method and limits: docs/performance.md.

GET  /api/cases/{case_id}/performance              stage breakdown, bottleneck, baseline
                                                   comparison, success rates, time saved
GET  /api/cases/{case_id}/performance/baselines    manual baseline history
POST /api/cases/{case_id}/performance/baselines    {task, manual_seconds, basis, note}
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import custody
from app.auth.deps import CurrentPrincipal
from app.models import Case
from app.perf.analysis import case_performance
from app.perf.models import ManualBaseline
from app.routes import DbSession, Examiner

router = APIRouter(prefix="/api")


class BaselineIn(BaseModel):
    task: Literal["analyze", "analytics"]
    manual_seconds: float = Field(gt=0, le=1e8, description="time the task takes by hand")
    basis: Literal["measured", "estimate"] = "estimate"
    note: str = Field(default="", max_length=2000)


def _case(db, case_id: int) -> Case:
    c = db.get(Case, case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    return c


def baseline_out(b: ManualBaseline) -> dict:
    return {
        "id": b.id,
        "task": b.task,
        "manual_seconds": b.manual_seconds,
        "basis": b.basis,
        "note": b.note,
        "entered_by": b.entered_by,
        "entered_at": b.entered_at,
        "custody_seq": b.custody_seq,
    }


@router.get("/cases/{case_id}/performance")
def get_performance(case_id: int, db: DbSession):
    _case(db, case_id)
    return case_performance(db, case_id)


@router.get("/cases/{case_id}/performance/baselines")
def list_baselines(case_id: int, db: DbSession):
    _case(db, case_id)
    rows = db.scalars(
        select(ManualBaseline).where(ManualBaseline.case_id == case_id).order_by(ManualBaseline.id)
    )
    return [baseline_out(b) for b in rows]


@router.post("/cases/{case_id}/performance/baselines", status_code=201)
def add_baseline(
    case_id: int, body: BaselineIn, db: DbSession, examiner: Examiner, p: CurrentPrincipal
):
    _case(db, case_id)
    entry = custody.append_entry(
        db,
        case_id,
        "manual_baseline_recorded",
        examiner,
        {
            "task": body.task,
            "manual_seconds": body.manual_seconds,
            "basis": body.basis,
            "note": body.note,
            "purpose": "input of the time-saved metric only (docs/performance.md)",
        },
    )
    b = ManualBaseline(
        case_id=case_id,
        task=body.task,
        manual_seconds=body.manual_seconds,
        basis=body.basis,
        note=body.note,
        entered_by=examiner,
        entered_by_user_id=p.user_id,
        entered_at=entry.timestamp_utc,
        custody_seq=entry.seq,
    )
    db.add(b)
    db.commit()
    return baseline_out(b)
