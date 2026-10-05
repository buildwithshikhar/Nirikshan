"""Run one analytics pass over an exported clip and persist it (DB rows + custody entry)."""

import json
import time
from dataclasses import fields
from pathlib import Path

from sqlalchemy.orm import Session

from app import __version__, custody
from app.analytics import ANALYTICS_VERSION, TRIAGE_LABEL, detect, error_rates, motion
from app.analytics.models import AnalyticsRun, Detection, MotionInterval
from app.analytics.registry import MODELS, ModelMissing
from app.carving.export import ffmpeg_version
from app.clock import utc_now_iso
from app.hashing import hash_file
from app.models import Clip

KINDS = ("motion", "objects", "faces")


class ClipNotAnalysable(RuntimeError):
    pass


def parse_params(kind: str, raw: dict | None):
    """Build and validate params; unknown keys are rejected (ValueError)."""
    cls = motion.MotionParams if kind == "motion" else detect.DetectParams
    raw = dict(raw or {})
    allowed = {f.name for f in fields(cls)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(unknown)}")
    return cls(**raw).validate()


def tool_info() -> dict:
    import numpy
    import onnxruntime

    return {
        "nirikshan": __version__,
        "analytics": ANALYTICS_VERSION,
        "ffmpeg": ffmpeg_version(),
        "onnxruntime": onnxruntime.__version__,
        "numpy": numpy.__version__,
        "execution_provider": "CPUExecutionProvider",
    }


def run_analytics(
    db: Session, clip: Clip, kind: str, raw_params: dict | None, examiner: str
) -> AnalyticsRun:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    params = parse_params(kind, raw_params)
    if clip.kind != "clip" or not clip.mp4_path or not Path(clip.mp4_path).is_file():
        raise ClipNotAnalysable("This clip has no exported MP4 to analyse")
    observed = hash_file(clip.mp4_path).sha256
    if clip.mp4_sha256 and observed != clip.mp4_sha256:
        raise ClipNotAnalysable(
            "Exported MP4 no longer matches its recorded SHA-256; refusing to analyse "
            f"(expected {clip.mp4_sha256}, observed {observed})"
        )
    spec = MODELS.get(kind)
    if spec is not None:
        from app.analytics.registry import verified_model_path

        verified_model_path(spec)  # ModelMissing (actionable) before any row is created
    model = spec.run_info() if spec else None
    rates = error_rates.for_kind(kind, params.to_dict())
    run = AnalyticsRun(
        case_id=clip.case_id,
        evidence_id=clip.evidence_id,
        clip_id=clip.id,
        kind=kind,
        status="running",
        examiner=examiner,
        label=TRIAGE_LABEL,
        bitstream_sha256=clip.bitstream_sha256,
        mp4_sha256=observed,
        params_json=json.dumps(params.to_dict(), sort_keys=True),
        model_json=json.dumps(model, sort_keys=True),
        error_rates_json=json.dumps(rates, sort_keys=True),
    )
    db.add(run)
    db.commit()
    t0 = time.perf_counter()
    try:
        run.tool_json = json.dumps(tool_info(), sort_keys=True)
        if kind == "motion":
            res = motion.analyse_motion(clip.mp4_path, params)
            for iv in res["intervals"]:
                db.add(
                    MotionInterval(
                        run_id=run.id,
                        clip_id=clip.id,
                        **{k: iv[k] for k in MOTION_FIELDS},
                    )
                )
            run.result_count = len(res["intervals"])
        else:
            res = detect.analyse_detections(clip.mp4_path, kind, params)
            for d in res["detections"]:
                x1, y1, x2, y2 = d["bbox"]
                db.add(
                    Detection(
                        run_id=run.id,
                        clip_id=clip.id,
                        kind=kind,
                        frame_index=d["frame_index"],
                        nominal_time_s=d["nominal_time_s"],
                        class_name=d["class_name"],
                        confidence=d["confidence"],
                        x1=x1,
                        y1=y1,
                        x2=x2,
                        y2=y2,
                    )
                )
            run.result_count = len(res["detections"])
        run.frames_analysed = res["frames_analysed"]
        run.ms_per_frame = round(
            (time.perf_counter() - t0) * 1000 / max(1, res["frames_analysed"]), 3
        )
        run.status = "completed"
    except ModelMissing:
        db.rollback()
        raise
    except Exception as e:  # noqa: BLE001 - recorded on the run, re-raised as failed status
        db.rollback()
        run = db.get(AnalyticsRun, run.id)
        run.status, run.error = "failed", f"{type(e).__name__}: {e}"[:500]
    run.finished_at = utc_now_iso()
    db.commit()
    custody.append_entry(
        db,
        clip.case_id,
        "analytics_run",
        examiner,
        {
            "run_id": run.id,
            "clip_id": clip.id,
            "kind": kind,
            "status": run.status,
            "label": TRIAGE_LABEL,
            "bitstream_sha256": clip.bitstream_sha256,
            "mp4_sha256": observed,
            "params": params.to_dict(),
            "models": [model] if model else [],
            "result_count": run.result_count,
            "frames_analysed": run.frames_analysed,
            "tool": json.loads(run.tool_json or "{}"),
            "error": run.error,
        },
        clip.evidence_id,
    )
    return run


MOTION_FIELDS = (
    "start_frame",
    "end_frame",
    "start_time_s",
    "end_time_s",
    "n_samples",
    "score_peak",
    "score_mean",
)
