"""Report API. The lead registers `router` in app.main (prefix /api is built in).

POST /api/cases/{id}/report        generate + store + record in custody (X-Examiner required)
GET  /api/cases/{id}/reports       list
GET  /api/reports/{id}/download    re-hashes the stored file; 409 if it no longer matches
GET  /api/cases/{id}/certificate-draft?evidence_id=   DRAFT Section 63(4) certificate (PDF)
GET  /api/cases/{id}/export.jsonld                    plain JSON-LD, NOT CASE-conformant
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import custody
from app.clock import utc_now_iso
from app.config import data_dir
from app.hashing import hash_file
from app.models import Case, Evidence
from app.report import certificate, jsonld
from app.report.build import build_report_data, library_versions
from app.report.models import Report
from app.report.pdf import render
from app.routes import DbSession, Examiner

router = APIRouter(prefix="/api")


def reports_dir(case_id: int) -> Path:
    return data_dir() / "cases" / str(case_id) / "reports"


def report_out(r: Report) -> dict:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "kind": r.kind,
        "file_name": r.file_name,
        "sha256": r.sha256,
        "size_bytes": r.size_bytes,
        "pages": r.pages,
        "content_hash": r.content_hash,
        "head_hash_before": r.head_hash_before,
        "chain_ok": bool(r.chain_ok),
        "generated_at": r.generated_at,
        "examiner": r.examiner,
        "custody_seq": r.custody_seq,
        "created_at": r.created_at,
    }


def generate_report(
    db: Session,
    case_id: int,
    examiner: str,
    generated_at: str | None = None,
    ntp: str | None = None,
    validation_results: Path | None = None,
) -> Report:
    """Build, render, store read-only (0444), register and record in the custody log."""
    data = build_report_data(db, case_id, generated_at, ntp, validation_results)
    pdf, pages, replaced = render(data)
    sha = hashlib.sha256(pdf).hexdigest()
    stamp = "".join(ch for ch in data["generated"]["generated_at"] if ch.isdigit())[:14]
    name = f"report_case{case_id}_{stamp}_{sha[:12]}.pdf"
    out_dir = reports_dir(case_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    if path.exists():
        if hash_file(path).sha256 != sha:
            raise RuntimeError(f"{name} already exists with different content")
    else:
        tmp = out_dir / (name + ".tmp")
        tmp.write_bytes(pdf)
        os.chmod(tmp, 0o444)
        tmp.replace(path)
    ver = data["custody"]["verification"]
    row = Report(
        case_id=case_id,
        file_name=name,
        file_path=str(path),
        sha256=sha,
        size_bytes=len(pdf),
        pages=pages,
        content_hash=data["content_hash"],
        head_hash_before=ver["head_hash"],
        chain_ok=int(ver["ok"]),
        generated_at=data["generated"]["generated_at"],
        examiner=examiner,
        params_json=json.dumps({"min_gap_s": 1.0, "characters_replaced": replaced}),
    )
    db.add(row)
    db.commit()
    entry = custody.append_entry(
        db,
        case_id,
        "report_generated",
        examiner,
        {
            "report_id": row.id,
            "file_name": name,
            "sha256": sha,
            "size_bytes": len(pdf),
            "pages": pages,
            "content_hash": data["content_hash"],
            "head_hash_built_from": ver["head_hash"],
            "head_hash_note": "chain head BEFORE this entry was appended",
            "entries_built_from": ver["entries"],
            "chain_ok_at_generation": ver["ok"],
            "generated_at": data["generated"]["generated_at"],
            "ntp_status": data["generated"]["ntp_status"],
            "tool_version": data["cover"]["tool_version"],
            "ffmpeg_version": data["cover"]["ffmpeg_version"],
            "libraries": library_versions(),
            "parameters": {"min_gap_s": 1.0, "characters_replaced": replaced},
        },
    )
    row.custody_seq = entry.seq
    db.commit()
    return row


def _case(db: Session, case_id: int) -> Case:
    c = db.get(Case, case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    return c


@router.post("/cases/{case_id}/report", status_code=201)
def create_report(case_id: int, db: DbSession, examiner: Examiner):
    _case(db, case_id)
    return report_out(generate_report(db, case_id, examiner))


@router.get("/cases/{case_id}/reports")
def list_reports(case_id: int, db: DbSession):
    _case(db, case_id)
    rows = db.scalars(select(Report).where(Report.case_id == case_id).order_by(Report.id.desc()))
    return [report_out(r) for r in rows]


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, db: DbSession):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    try:
        observed = hash_file(r.file_path).sha256
    except OSError:
        raise HTTPException(409, "Stored report file is missing; it cannot be served") from None
    if observed != r.sha256:
        raise HTTPException(
            409,
            f"Stored report no longer matches its recorded SHA-256 (recorded {r.sha256}, "
            f"observed {observed}); it is not served. Investigate before relying on it.",
        )
    return FileResponse(r.file_path, media_type="application/pdf", filename=r.file_name)


@router.get("/cases/{case_id}/certificate-draft")
def certificate_draft(case_id: int, db: DbSession, evidence_id: int = Query(...)):
    _case(db, case_id)
    ev = db.get(Evidence, evidence_id)
    if ev is None or ev.case_id != case_id:
        raise HTTPException(404, "Evidence not found in this case")
    if not ev.sha256 or not ev.md5:
        raise HTTPException(409, "Evidence has no recorded hashes (acquisition not complete)")
    d = certificate.certificate_data(db, case_id, evidence_id, utc_now_iso())
    pdf, _ = certificate.render_certificate(d)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="DRAFT_s63-4_certificate_case{case_id}'
            f'_evidence{evidence_id}.pdf"',
            "X-Nirikshan-Draft": "true",
        },
    )


@router.get("/cases/{case_id}/export.jsonld")
def export_jsonld(case_id: int, db: DbSession):
    _case(db, case_id)
    return JSONResponse(
        jsonld.build_jsonld(db, case_id),
        media_type="application/ld+json",
        headers={"Content-Disposition": f'attachment; filename="case{case_id}.jsonld"'},
    )
