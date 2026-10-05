"""Analytics API. The lead registers `router` in app.main (prefix /api is built in)."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analytics import TRIAGE_LABEL, error_rates, runner
from app.analytics.models import AnalyticsRun, Detection, MotionInterval
from app.analytics.registry import ModelMissing, model_status
from app.models import Clip
from app.routes import DbSession, Examiner

router = APIRouter(prefix="/api")


class AnalyticsIn(BaseModel):
    kind: str = Field(description="motion | objects | faces")
    params: dict[str, Any] = Field(default_factory=dict)


def _run_summary(r: AnalyticsRun) -> dict:
    return {
        "id": r.id,
        "clip_id": r.clip_id,
        "case_id": r.case_id,
        "kind": r.kind,
        "status": r.status,
        "label": r.label,
        "examiner": r.examiner,
        "bitstream_sha256": r.bitstream_sha256,
        "mp4_sha256": r.mp4_sha256,
        "params": json.loads(r.params_json),
        "model": json.loads(r.model_json),
        "error_rates": json.loads(r.error_rates_json),
        "tool": json.loads(r.tool_json),
        "frames_analysed": r.frames_analysed,
        "result_count": r.result_count,
        "ms_per_frame": r.ms_per_frame,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "error": r.error,
    }


def _detail(db, r: AnalyticsRun) -> dict:
    out = _run_summary(r)
    if r.kind == "motion":
        rows = db.scalars(
            select(MotionInterval)
            .where(MotionInterval.run_id == r.id)
            .order_by(MotionInterval.start_frame)
        ).all()
        out["intervals"] = [
            {
                "id": m.id,
                "start_frame": m.start_frame,
                "end_frame": m.end_frame,
                "start_time_s": m.start_time_s,
                "end_time_s": m.end_time_s,
                "n_samples": m.n_samples,
                "score_peak": m.score_peak,
                "score_mean": m.score_mean,
                "label": m.label,
            }
            for m in rows
        ]
    else:
        rows = db.scalars(
            select(Detection)
            .where(Detection.run_id == r.id)
            .order_by(Detection.frame_index, Detection.confidence.desc(), Detection.id)
        ).all()
        out["detections"] = [
            {
                "id": d.id,
                "frame_index": d.frame_index,
                "nominal_time_s": d.nominal_time_s,
                "class_name": d.class_name,
                "confidence": d.confidence,
                "bbox": [d.x1, d.y1, d.x2, d.y2],
                "label": d.label,
            }
            for d in rows
        ]
    return out


@router.get("/analytics/models")
def analytics_models():
    """Model cards (licence, hash, input size, labels), install status and error rates."""
    return {
        "label": TRIAGE_LABEL,
        "models": model_status(),
        "error_rates": error_rates.load(),
    }


@router.post("/clips/{clip_id}/analytics", status_code=201)
def run_clip_analytics(clip_id: int, body: AnalyticsIn, db: DbSession, examiner: Examiner):
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    try:
        run = runner.run_analytics(db, clip, body.kind, body.params, examiner)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except ModelMissing as e:
        raise HTTPException(503, str(e)) from e
    except runner.ClipNotAnalysable as e:
        raise HTTPException(409, str(e)) from e
    return _detail(db, run)


@router.get("/clips/{clip_id}/analytics")
def list_clip_analytics(clip_id: int, db: DbSession, kind: Annotated[str | None, Query()] = None):
    if db.get(Clip, clip_id) is None:
        raise HTTPException(404, "Clip not found")
    q = select(AnalyticsRun).where(AnalyticsRun.clip_id == clip_id).order_by(AnalyticsRun.id.desc())
    if kind:
        q = q.where(AnalyticsRun.kind == kind)
    return [_run_summary(r) for r in db.scalars(q)]


@router.get("/analytics/{run_id}")
def get_analytics_run(run_id: int, db: DbSession):
    run = db.get(AnalyticsRun, run_id)
    if run is None:
        raise HTTPException(404, "Analytics run not found")
    return _detail(db, run)
