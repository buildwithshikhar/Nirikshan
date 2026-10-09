"""Acquisition API: resumable acquisition, bad-sector map, native-export ingest, capabilities."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.acquire import native, resumable
from app.acquire.models import AcquisitionSession, NativeExport
from app.carving.export import FfmpegMissing, find_tool
from app.config import allow_block_devices
from app.evidence import AcquisitionError, IntegrityError, PathNotAllowed
from app.models import Case, Evidence
from app.routes import DbSession, Examiner

router = APIRouter(prefix="/api")

EWF_REASON = (
    "E01/EWF ingest is deferred (docs/ROUND_D_DEFERRED.md). libewf/pyewf is LGPL-3.0-or-later, "
    "which is adoptable as an unmodified dynamically linked library (as psycopg is), but it is "
    "not a dependency of this build, needs a native libewf build, and no E01 test image can be "
    "produced in this environment to test it. Convert to raw (e.g. ewfexport) and acquire the "
    "raw image instead; the conversion is outside Nirikshan's custody."
)


class ResumableIn(BaseModel):
    source_path: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=300)
    write_blocker: Literal["yes", "no", "unknown"]
    chunk_size: int = resumable.DEFAULT_CHUNK
    retries: int = 1


class NativeIn(BaseModel):
    source_path: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=300)
    write_blocker: Literal["yes", "no", "unknown"] = "unknown"


def _case(db, case_id: int) -> Case:
    row = db.get(Case, case_id)
    if row is None:
        raise HTTPException(404, "Case not found")
    return row


def _session(db, sid: int) -> AcquisitionSession:
    row = db.get(AcquisitionSession, sid)
    if row is None:
        raise HTTPException(404, "Acquisition session not found")
    return row


def _map_errors(exc: Exception):
    if isinstance(exc, PathNotAllowed):
        return HTTPException(403, str(exc))
    if isinstance(exc, resumable.ResumeRefused | IntegrityError):
        return HTTPException(409, str(exc))
    return HTTPException(400, str(exc))


def _with_evidence(db, sess: AcquisitionSession) -> dict:
    ev = db.get(Evidence, sess.evidence_id)
    out = resumable.session_out(sess)
    out["evidence"] = {
        "id": ev.id,
        "status": ev.status,
        "size_bytes": ev.size_bytes,
        "md5": ev.md5,
        "sha256": ev.sha256,
        "synthetic": ev.synthetic,
    }
    return out


@router.get("/acquisition/capabilities")
def capabilities() -> dict:
    ffprobe = find_tool("ffprobe") is not None
    return {
        "resumable": {"available": True},
        "bad_sector_map": {
            "available": True,
            "note": "unreadable sectors are zero-filled in the copy; hashes cover the copy",
        },
        "native_export_ingest": {"available": ffprobe}
        | ({} if ffprobe else {"reason": "ffprobe not found on PATH"}),
        "ewf": {"available": False, "reason": EWF_REASON},
        "block_device": {
            "available": allow_block_devices(),
            "opt_in": "NIRIKSHAN_ALLOW_BLOCK_DEVICES=1",
            "verified_on_real_disks": False,
        },
    }


@router.post("/cases/{case_id}/acquisitions", status_code=201)
def start_acquisition(case_id: int, body: ResumableIn, db: DbSession, examiner: Examiner):
    _case(db, case_id)
    try:
        sess = resumable.start(
            db,
            case_id,
            body.source_path,
            body.label,
            body.write_blocker,
            examiner,
            chunk_size=body.chunk_size,
            retries=body.retries,
        )
    except (AcquisitionError, IntegrityError) as exc:
        raise _map_errors(exc) from exc
    return _with_evidence(db, sess)


@router.get("/acquisitions/{session_id}")
def get_acquisition(session_id: int, db: DbSession):
    return _with_evidence(db, _session(db, session_id))


@router.get("/cases/{case_id}/acquisitions")
def list_acquisitions(case_id: int, db: DbSession):
    _case(db, case_id)
    rows = db.scalars(
        select(AcquisitionSession)
        .where(AcquisitionSession.case_id == case_id)
        .order_by(AcquisitionSession.id)
    ).all()
    return [resumable.session_out(r) for r in rows]


@router.post("/acquisitions/{session_id}/resume")
def resume_acquisition(session_id: int, db: DbSession, examiner: Examiner):
    sess = _session(db, session_id)
    try:
        sess = resumable.resume(db, sess, examiner)
    except (AcquisitionError, IntegrityError) as exc:
        raise _map_errors(exc) from exc
    return _with_evidence(db, sess)


@router.get("/evidence/{evidence_id}/bad-sectors")
def bad_sectors(evidence_id: int, db: DbSession):
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    sess = db.scalars(
        select(AcquisitionSession).where(AcquisitionSession.evidence_id == evidence_id)
    ).first()
    if sess is None:
        return {
            "available": True,
            "method": "single-pass acquisition",
            "ranges": [],
            "range_count": 0,
            "bytes": 0,
            "zero_filled": False,
            "note": "acquired by the single-pass path, which aborts on any read error; "
            "an acquired item from that path therefore has no zero-filled ranges",
        }
    return {"available": True, "method": "resumable chunked copy", "session_id": sess.id} | (
        resumable.session_out(sess)["bad_sector_map"]
    )


@router.post("/cases/{case_id}/native-exports", status_code=201)
def ingest_native(case_id: int, body: NativeIn, db: DbSession, examiner: Examiner):
    _case(db, case_id)
    try:
        sess, row = native.ingest(
            db, case_id, body.source_path, body.label, body.write_blocker, examiner
        )
    except FfmpegMissing as exc:
        raise HTTPException(503, str(exc)) from exc
    except (AcquisitionError, IntegrityError) as exc:
        raise _map_errors(exc) from exc
    return {"acquisition": _with_evidence(db, sess), "native_export": native.native_out(row)}


@router.get("/evidence/{evidence_id}/native-export")
def get_native(evidence_id: int, db: DbSession):
    if db.get(Evidence, evidence_id) is None:
        raise HTTPException(404, "Evidence not found")
    row = db.scalars(select(NativeExport).where(NativeExport.evidence_id == evidence_id)).first()
    if row is None:
        return {"available": False, "reason": "this evidence was not ingested as a native export"}
    return native.native_out(row)


@router.get("/acquisition/ewf")
def ewf() -> dict:
    return {"available": False, "reason": EWF_REASON}
