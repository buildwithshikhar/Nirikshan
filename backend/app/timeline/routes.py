"""P5 API: timezone assumptions, reference observations, drift model, timeline, OSD check.

Every mutation requires X-Examiner and writes a custody entry with the full values.
"""

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import custody
from app.clock import utc_now_iso
from app.models import Case, Clip, Evidence
from app.routes import DbSession, Examiner
from app.timeline import drift, osd, timeline
from app.timeline.models import OsdCheck, ReferenceObservation, TimeAssumption, TimeModel
from app.timeline.timestamps import (
    TzAssumption,
    TzError,
    decode_raw_dict,
    get_zone,
    localize,
    parse_iso_utc,
    parse_wall_clock,
)

router = APIRouter(prefix="/api")

DISCLAIMER = (
    "Synthetic-validated only: nothing here was validated on a real DVR/NVR. Timezone and "
    "epoch basis are examiner assumptions, never defaults."
)


class AssumptionIn(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    epoch_basis: Literal["utc", "device_local"] | None = None
    evidence_kind: Literal["examiner_entered", "device_setting_note"] = "examiner_entered"
    notes: str = ""


class ReferenceIn(BaseModel):
    device_time_raw: str = Field(min_length=1, max_length=64)
    true_time_utc: str = Field(min_length=1, max_length=40)
    method: Literal["photo_dvr_clock", "known_event", "ntp_phone", "other"]
    notes: str = Field(min_length=1)
    photo_path: str = ""
    reading_uncertainty_s: float = Field(default=1.0, ge=0, le=3600)


class FitIn(BaseModel):
    reading_uncertainty_s: float | None = Field(default=None, ge=0, le=3600)
    assumed_max_drift_ppm: float = Field(default=100.0, ge=0, le=100000)


class OsdIn(BaseModel):
    roi: list[float] | None = None
    n_samples: int = Field(default=8, ge=1, le=60)
    tolerance_s: float = Field(default=osd.DEFAULT_TOLERANCE_S, gt=0, le=3600)


def _evidence(db: Session, evidence_id: int) -> Evidence:
    row = db.get(Evidence, evidence_id)
    if row is None:
        raise HTTPException(404, "Evidence not found")
    return row


def _assumption_row(db: Session, evidence_id: int) -> TimeAssumption | None:
    return db.scalars(
        select(TimeAssumption).where(TimeAssumption.evidence_id == evidence_id)
    ).first()


def assumption_of(row: TimeAssumption | None) -> TzAssumption:
    if row is None:
        return TzAssumption()
    return TzAssumption(row.timezone, row.epoch_basis, row.evidence_kind, row.notes)


def _assumption_out(evidence_id: int, row: TimeAssumption | None) -> dict:
    a = assumption_of(row)
    out = {
        "evidence_id": evidence_id,
        "set": row is not None,
        "timezone": a.timezone,
        "epoch_basis": a.epoch_basis,
        "evidence_kind": a.evidence_kind if row else None,
        "notes": a.notes,
        "tz_status": a.status,
        "examiner": row.examiner if row else None,
        "updated_at": row.updated_at if row else None,
        "warning": None,
    }
    if a.status == "unknown":
        out["warning"] = (
            "Timezone UNKNOWN: no UTC value is computed for this evidence; its clips are listed "
            "as unplaceable. Nothing is defaulted to UTC or local."
        )
    return out


@router.get("/evidence/{evidence_id}/time-assumption")
def get_time_assumption(evidence_id: int, db: DbSession):
    _evidence(db, evidence_id)
    return _assumption_out(evidence_id, _assumption_row(db, evidence_id))


@router.put("/evidence/{evidence_id}/time-assumption")
def put_time_assumption(evidence_id: int, body: AssumptionIn, db: DbSession, examiner: Examiner):
    ev = _evidence(db, evidence_id)
    tz = (body.timezone or "").strip() or None
    if tz:
        try:
            get_zone(tz)
        except TzError as exc:
            raise HTTPException(422, str(exc)) from exc
    if (tz or body.epoch_basis) and not body.notes.strip():
        raise HTTPException(
            422, "notes are required: record the evidence for the assumption (e.g. device menu)"
        )
    if body.epoch_basis == "device_local" and not tz:
        raise HTTPException(422, "epoch_basis device_local requires a timezone")
    row = _assumption_row(db, evidence_id)
    before = _assumption_out(evidence_id, row)
    if row is None:
        row = TimeAssumption(evidence_id=evidence_id, case_id=ev.case_id, examiner=examiner)
        db.add(row)
    row.timezone, row.epoch_basis = tz, body.epoch_basis
    row.evidence_kind, row.notes, row.examiner = body.evidence_kind, body.notes.strip(), examiner
    row.updated_at = utc_now_iso()
    db.commit()
    after = _assumption_out(evidence_id, row)
    custody.append_entry(
        db,
        ev.case_id,
        "time_assumption_set",
        examiner,
        {"before": before, "after": after},
        evidence_id,
    )
    return after


def _ref_out(r: ReferenceObservation) -> dict:
    return {
        "id": r.id,
        "evidence_id": r.evidence_id,
        "device_time_raw": r.device_time_raw,
        "true_time_utc": r.true_time_utc,
        "method": r.method,
        "notes": r.notes,
        "photo_path": r.photo_path,
        "reading_uncertainty_s": r.reading_uncertainty_s,
        "examiner": r.examiner,
        "created_at": r.created_at,
    }


@router.get("/evidence/{evidence_id}/time-references")
def list_time_references(evidence_id: int, db: DbSession):
    _evidence(db, evidence_id)
    rows = db.scalars(
        select(ReferenceObservation)
        .where(ReferenceObservation.evidence_id == evidence_id)
        .order_by(ReferenceObservation.id)
    ).all()
    return [_ref_out(r) for r in rows]


@router.post("/evidence/{evidence_id}/time-references", status_code=201)
def add_time_reference(evidence_id: int, body: ReferenceIn, db: DbSession, examiner: Examiner):
    ev = _evidence(db, evidence_id)
    try:
        parse_wall_clock(body.device_time_raw)
        true_utc = parse_iso_utc(body.true_time_utc)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = ReferenceObservation(
        evidence_id=evidence_id,
        case_id=ev.case_id,
        device_time_raw=body.device_time_raw.strip(),
        true_time_utc=true_utc.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        method=body.method,
        notes=body.notes.strip(),
        photo_path=body.photo_path,
        reading_uncertainty_s=body.reading_uncertainty_s,
        examiner=examiner,
    )
    db.add(row)
    db.commit()
    out = _ref_out(row)
    custody.append_entry(db, ev.case_id, "time_reference_added", examiner, out, evidence_id)
    return out


def _observations(db: Session, evidence_id: int, a: TzAssumption) -> list[drift.Observation]:
    if not a.timezone:
        raise HTTPException(
            409,
            "a device timezone assumption is required to convert the device clock readings to "
            "UTC; set it first (the fit does not default it)",
        )
    rows = db.scalars(
        select(ReferenceObservation)
        .where(ReferenceObservation.evidence_id == evidence_id)
        .order_by(ReferenceObservation.id)
    ).all()
    if not rows:
        raise HTTPException(409, "no reference observations recorded for this evidence")
    obs, bad = [], []
    for r in rows:
        res = localize(parse_wall_clock(r.device_time_raw), a.timezone)
        if len(res.candidates) != 1:
            bad.append(f"#{r.id} ({r.device_time_raw}: {', '.join(res.flags)})")
            continue
        obs.append(drift.Observation(res.candidates[0], parse_iso_utc(r.true_time_utc), r.id))
    if bad:
        raise HTTPException(
            409, "observations with an ambiguous or nonexistent local time: " + "; ".join(bad)
        )
    return obs


@router.post("/evidence/{evidence_id}/time-model/fit")
def fit_time_model(evidence_id: int, db: DbSession, examiner: Examiner, body: FitIn | None = None):
    ev = _evidence(db, evidence_id)
    p = body or FitIn()
    a = assumption_of(_assumption_row(db, evidence_id))
    obs = _observations(db, evidence_id, a)
    refs = {
        r.id: r.reading_uncertainty_s
        for r in db.scalars(
            select(ReferenceObservation).where(ReferenceObservation.evidence_id == evidence_id)
        )
    }
    u = p.reading_uncertainty_s
    if u is None:
        u = max(refs.values()) if refs else 1.0
    model = drift.fit(obs, u, p.assumed_max_drift_ppm)
    row = TimeModel(
        evidence_id=evidence_id,
        case_id=ev.case_id,
        model_json="{}",
        timezone_used=a.timezone or "",
        examiner=examiner,
    )
    db.add(row)
    db.flush()
    model.id = row.id
    out = model.to_dict()
    row.model_json = json.dumps(out)
    db.commit()
    out["timezone_used"] = a.timezone
    custody.append_entry(
        db, ev.case_id, "time_model_fitted", examiner, {"model": out, "params": p.model_dump()},
        evidence_id,
    )  # fmt: skip
    return out


def latest_model(db: Session, evidence_id: int) -> drift.DriftModel | None:
    row = db.scalars(
        select(TimeModel).where(TimeModel.evidence_id == evidence_id).order_by(TimeModel.id.desc())
    ).first()
    return drift.DriftModel.from_dict(json.loads(row.model_json)) if row else None


@router.get("/evidence/{evidence_id}/time-model")
def get_time_model(evidence_id: int, db: DbSession):
    _evidence(db, evidence_id)
    m = latest_model(db, evidence_id)
    return m.to_dict() if m else None


def _latest_osd(db: Session, clip_id: int) -> dict | None:
    row = db.scalars(
        select(OsdCheck).where(OsdCheck.clip_id == clip_id).order_by(OsdCheck.id.desc())
    ).first()
    return json.loads(row.result_json)["summary"] if row else None


def _clip_records(clip: Clip, a: TzAssumption, model: drift.DriftModel | None):
    try:
        parsed = json.loads(clip.parsed_json or "{}")
    except ValueError:
        parsed = {}
    src = {"evidence_id": clip.evidence_id, "clip_id": clip.id, "parser": clip.engine}
    out = []
    for t in parsed.get("timestamps", []) or []:
        rec = decode_raw_dict(t, a, src)
        drift.apply_correction(rec, model)
        out.append(rec)
    return out


def build_case_timeline(db: Session, case_id: int, min_gap_s: float) -> dict:
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    evs = db.scalars(
        select(Evidence).where(Evidence.case_id == case_id).order_by(Evidence.id)
    ).all()
    assumptions = {e.id: assumption_of(_assumption_row(db, e.id)) for e in evs}
    models = {e.id: latest_model(db, e.id) for e in evs}
    clips = db.scalars(
        select(Clip).where(Clip.case_id == case_id, Clip.kind == "clip").order_by(Clip.id)
    ).all()
    items = []
    for c in clips:
        a = assumptions.get(c.evidence_id, TzAssumption())
        m = models.get(c.evidence_id)
        items.append(
            {
                "clip_id": c.id,
                "evidence_id": c.evidence_id,
                "channel": c.channel,
                "engine": c.engine,
                "duration_s": c.duration_s,
                "records": _clip_records(c, a, m),
                "osd": _latest_osd(db, c.id),
                "drift_model_id": m.id if m and m.usable else None,
                "tz_status": a.status,
            }
        )
    tl = timeline.build_timeline(items, min_gap_s)
    tl["case_id"] = case_id
    tl["evidence"] = [
        {
            **_assumption_out(e.id, _assumption_row(db, e.id)),
            "label": e.label,
            "model": models[e.id].to_dict() if models[e.id] else None,
        }
        for e in evs
    ]
    tl["evidence_without_timezone"] = [e.id for e in evs if assumptions[e.id].status == "unknown"]
    tl["disclaimer"] = DISCLAIMER
    return tl


@router.get("/cases/{case_id}/timeline")
def get_timeline(case_id: int, db: DbSession, min_gap_s: float = timeline.DEFAULT_MIN_GAP_S):
    return build_case_timeline(db, case_id, min_gap_s)


@router.get("/cases/{case_id}/timeline/export")
def export_timeline(
    case_id: int,
    db: DbSession,
    format: Literal["csv", "json"] = "csv",
    min_gap_s: float = timeline.DEFAULT_MIN_GAP_S,
):
    tl = build_case_timeline(db, case_id, min_gap_s)
    if format == "json":
        body, mt = json.dumps(tl, indent=2), "application/json"
    else:
        body, mt = timeline.export_csv(tl), "text/csv"
    return Response(
        body,
        media_type=mt,
        headers={"Content-Disposition": f'attachment; filename="timeline_case{case_id}.{format}"'},
    )


@router.post("/clips/{clip_id}/osd-check")
def osd_check(clip_id: int, db: DbSession, examiner: Examiner, body: OsdIn | None = None):
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    if not clip.mp4_path or not Path(clip.mp4_path).is_file():
        raise HTTPException(404, "No exported video for this clip")
    p = body or OsdIn()
    roi = tuple(p.roi) if p.roi else osd.DEFAULT_ROI
    if len(roi) != 4:
        raise HTTPException(422, "roi must be [x, y, w, h] fractions")
    a = assumption_of(_assumption_row(db, clip.evidence_id))
    recs = _clip_records(clip, a, None)
    start_rec, _ = timeline.pick_start_end(recs)
    start_wall = osd.metadata_start_wall(start_rec) if start_rec else None
    try:
        result = osd.check_clip(
            clip.mp4_path,
            start_wall,
            roi=roi,  # type: ignore[arg-type]
            n_samples=p.n_samples,
            tolerance_s=p.tolerance_s,
            duration_s=clip.duration_s,
        )
    except osd.OcrUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    result["clip_id"] = clip.id
    db.add(
        OsdCheck(
            clip_id=clip.id, case_id=clip.case_id, result_json=json.dumps(result), examiner=examiner
        )
    )
    db.commit()
    custody.append_entry(
        db,
        clip.case_id,
        "osd_check",
        examiner,
        {"clip_id": clip.id, "roi": list(roi), "summary": result["summary"], "ocr": result["ocr"]},
        clip.evidence_id,
    )
    return result
