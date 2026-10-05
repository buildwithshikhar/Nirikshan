import json
import re
import subprocess
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError as DbIntegrityError
from sqlalchemy.orm import Session

from app import __version__, analyze, custody, evidence, schema, schemas, signing
from app.carving.carve import CarveParams
from app.carving.export import FfmpegMissing, find_tool
from app.clock import ntp_status
from app.config import allow_block_devices, evidence_roots
from app.db import get_db
from app.hashing import hash_file
from app.models import AuditEntry, CarveRun, Case, Clip, CustodyEntry, Evidence

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]


def examiner_name(x_examiner: Annotated[str, Header()] = "") -> str:
    """Examiner attestation for mutating calls. There is no authentication in P1."""
    name = x_examiner.strip()
    if not name:
        raise HTTPException(400, "X-Examiner header is required")
    return name


Examiner = Annotated[str, Depends(examiner_name)]


def _case(db: Session, case_id: int) -> Case:
    row = db.get(Case, case_id)
    if row is None:
        raise HTTPException(404, "Case not found")
    return row


def _evidence(db: Session, evidence_id: int) -> Evidence:
    row = db.get(Evidence, evidence_id)
    if row is None:
        raise HTTPException(404, "Evidence not found")
    return row


@router.get("/system")
def system() -> dict:
    ffmpeg = find_tool("ffmpeg")
    version = None
    if ffmpeg:
        try:
            out = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=5)
            version = out.stdout.splitlines()[0] if out.stdout else None
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "tool_version": __version__,
        "schema_version": schema.SCHEMA_VERSION,
        "ffmpeg": {"available": ffmpeg is not None, "version": version},
        "mode": "full" if ffmpeg else "degraded (no ffmpeg: MP4 export unavailable)",
        "ntp_status": ntp_status(),
        "evidence_roots": [str(r) for r in evidence_roots()],
        "block_devices_allowed": allow_block_devices(),
        "signing_key_id": signing.key_id(signing.public_key()),
    }


@router.get("/signing-key")
def signing_key() -> dict:
    """Public half only, for external verification of custody signatures."""
    return {
        "algorithm": "Ed25519",
        "key_id": signing.key_id(signing.public_key()),
        "public_key_hex": signing.public_key_hex(),
    }


@router.post("/cases", response_model=schemas.CaseOut, status_code=201)
def create_case(body: schemas.CaseIn, db: DbSession, examiner: Examiner):
    row = Case(**body.model_dump(), examiner=examiner)
    db.add(row)
    try:
        db.commit()
    except DbIntegrityError:
        db.rollback()
        raise HTTPException(409, "case_number already exists") from None
    custody.append_entry(
        db, row.id, "case_created", examiner, {"case_number": row.case_number, "title": row.title}
    )
    return row


@router.get("/cases", response_model=list[schemas.CaseOut])
def list_cases(db: DbSession):
    return db.scalars(select(Case).order_by(Case.id.desc())).all()


@router.get("/cases/{case_id}", response_model=schemas.CaseOut)
def get_case(case_id: int, db: DbSession):
    return _case(db, case_id)


@router.post("/cases/{case_id}/evidence", response_model=schemas.EvidenceOut, status_code=201)
def acquire_evidence(case_id: int, body: schemas.AcquireIn, db: DbSession, examiner: Examiner):
    _case(db, case_id)
    try:
        return evidence.acquire(
            db, case_id, body.source_path, body.label, body.write_blocker, examiner
        )
    except evidence.PathNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except evidence.AcquisitionError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/cases/{case_id}/evidence", response_model=list[schemas.EvidenceOut])
def list_evidence(case_id: int, db: DbSession):
    _case(db, case_id)
    return db.scalars(
        select(Evidence).where(Evidence.case_id == case_id).order_by(Evidence.id)
    ).all()


@router.post("/evidence/{evidence_id}/verify")
def verify_evidence(evidence_id: int, db: DbSession, examiner: Examiner):
    return evidence.verify_evidence(db, _evidence(db, evidence_id), examiner)


@router.get("/cases/{case_id}/custody", response_model=list[schemas.CustodyOut])
def list_custody(case_id: int, db: DbSession):
    _case(db, case_id)
    return db.scalars(
        select(CustodyEntry).where(CustodyEntry.case_id == case_id).order_by(CustodyEntry.seq)
    ).all()


@router.get("/cases/{case_id}/custody/verify")
def verify_custody(case_id: int, db: DbSession):
    _case(db, case_id)
    return custody.verify_chain(db, case_id)


def _clip_out(row: Clip) -> schemas.ClipOut:
    out = schemas.ClipOut.model_validate(row)
    out.has_video = bool(row.mp4_path) and Path(row.mp4_path).is_file()
    return out


def _run_detail(db: Session, run: CarveRun) -> dict:
    clips = db.scalars(
        select(Clip).where(Clip.run_id == run.id).order_by(Clip.kind, Clip.seq)
    ).all()
    return {
        "id": run.id,
        "case_id": run.case_id,
        "evidence_id": run.evidence_id,
        "status": run.status,
        "examiner": run.examiner,
        "params": json.loads(run.params_json),
        "vendor_matches": json.loads(run.vendor_json),
        "parsers": json.loads(run.parse_json),
        "stats": json.loads(run.stats_json),
        "tool_version": run.tool_version,
        "ffmpeg_version": run.ffmpeg_version,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "identify_seconds": run.ident_seconds,
        "carve_seconds": run.carve_seconds,
        "error": run.error,
        "clips": [_clip_out(c) for c in clips],
    }


@router.post("/evidence/{evidence_id}/analyze", status_code=201)
def analyze_evidence(
    evidence_id: int, db: DbSession, examiner: Examiner, body: schemas.AnalyzeIn | None = None
):
    """Identify the vendor and carve clips. Synchronous in P2 (large images block the request)."""
    ev = _evidence(db, evidence_id)
    p = body or schemas.AnalyzeIn()
    params = CarveParams(
        max_pad=p.max_pad,
        h264_continuity=p.h264_continuity,
        validate_params=p.validate_params,
        join_gap=p.join_gap,
    )
    try:
        run = analyze.analyze(db, ev, examiner, params, p.parser_options, p.generic_scope)
    except FfmpegMissing as exc:
        raise HTTPException(503, str(exc)) from exc
    except evidence.IntegrityError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _run_detail(db, run)


@router.get("/evidence/{evidence_id}/runs")
def list_runs(evidence_id: int, db: DbSession):
    _evidence(db, evidence_id)
    runs = db.scalars(
        select(CarveRun).where(CarveRun.evidence_id == evidence_id).order_by(CarveRun.id.desc())
    ).all()
    return [_run_detail(db, r) for r in runs]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: DbSession):
    run = db.get(CarveRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return _run_detail(db, run)


def _clip(db: Session, clip_id: int) -> Clip:
    row = db.get(Clip, clip_id)
    if row is None:
        raise HTTPException(404, "Clip not found")
    return row


@router.get("/clips/{clip_id}/video")
def clip_video(clip_id: int, db: DbSession):
    row = _clip(db, clip_id)
    if not row.mp4_path or not Path(row.mp4_path).is_file():
        raise HTTPException(404, "No exported video for this clip")
    return FileResponse(row.mp4_path, media_type="video/mp4", filename=f"clip_{row.id}.mp4")


@router.post("/clips/{clip_id}/verify")
def verify_clip(clip_id: int, db: DbSession, examiner: Examiner):
    """Re-hash the exported MP4 and compare with the hash recorded at carve time."""
    row = _clip(db, clip_id)
    if not row.mp4_path:
        raise HTTPException(404, "No exported video for this clip")
    try:
        observed = hash_file(row.mp4_path).sha256
    except OSError:
        observed = ""
    ok = observed == row.mp4_sha256
    custody.append_entry(
        db,
        row.case_id,
        "clip_verified",
        examiner,
        {"clip_id": row.id, "ok": ok, "expected": row.mp4_sha256, "observed": observed},
        row.evidence_id,
    )
    return {"ok": ok, "expected": row.mp4_sha256, "observed": observed}


@router.get("/audit", response_model=list[schemas.AuditOut])
def list_audit(
    db: DbSession, case_id: int | None = None, limit: Annotated[int, Query(le=1000)] = 200
):
    q = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
    if case_id is not None:
        q = q.where(AuditEntry.case_id == case_id)
    return db.scalars(q).all()


CASE_PATH = re.compile(r"^/api/cases/(\d+)")


def audit_case_id(path: str) -> int | None:
    m = CASE_PATH.match(path)
    return int(m.group(1)) if m else None
