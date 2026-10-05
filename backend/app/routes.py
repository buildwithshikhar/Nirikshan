import re
import shutil
import subprocess
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError as DbIntegrityError
from sqlalchemy.orm import Session

from app import __version__, custody, evidence, schemas, signing
from app.clock import ntp_status
from app.db import get_db
from app.models import AuditEntry, Case, CustodyEntry, Evidence

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
    ffmpeg = shutil.which("ffmpeg")
    version = None
    if ffmpeg:
        try:
            out = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=5)
            version = out.stdout.splitlines()[0] if out.stdout else None
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "tool_version": __version__,
        "ffmpeg": {"available": ffmpeg is not None, "version": version},
        "mode": "full" if ffmpeg else "degraded (no ffmpeg: MP4 export unavailable)",
        "ntp_status": ntp_status(),
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
