"""Evidence package API (prefix /api).

POST /api/cases/{case_id}/package       build (case member, admin/examiner) -> 201 package record
GET  /api/cases/{case_id}/packages      list
GET  /api/packages/{package_id}/download re-hashes the stored file first; 409 on mismatch
GET  /api/package-key                   public: package signing key id + public key

The passphrase (optional) travels in the request body: the app does not provide TLS, so send it
only over loopback or through a TLS-terminating proxy. It is never stored or logged.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import custody
from app.clock import ntp_status, utc_now_iso
from app.config import data_dir
from app.hashing import hash_file
from app.models import Case
from app.package import build as builder
from app.package import crypto, keys
from app.package.models import Package
from app.routes import DbSession, Examiner

router = APIRouter(prefix="/api")


class PackageIn(BaseModel):
    include_clips: bool = True
    passphrase: str | None = Field(default=None, min_length=crypto.MIN_PASSPHRASE, max_length=1024)


def packages_dir(case_id: int) -> Path:
    return data_dir() / "cases" / str(case_id) / "packages"


def package_out(p: Package) -> dict:
    return {
        "id": p.id,
        "case_id": p.case_id,
        "file_name": p.file_name,
        "sha256": p.sha256,
        "size_bytes": p.size_bytes,
        "encrypted": p.encrypted,
        "manifest_sha256": p.manifest_sha256,
        "key_id": p.key_id,
        "file_count": p.file_count,
        "include_clips": p.include_clips,
        "head_hash_built_from": p.head_hash_built_from,
        "created_at": p.created_at,
        "created_by": p.created_by,
        "custody_seq": p.custody_seq,
        "excluded": json.loads(p.excluded_json),
        "verify_command": (
            f"python -m app.cli verify-package {p.file_name} --expect-key-id {p.key_id}"
        ),
    }


def create_package(
    db: Session,
    case_id: int,
    examiner: str,
    *,
    include_clips: bool = True,
    passphrase: bytes | None = None,
) -> Package:
    created_at, ntp = utc_now_iso(), ntp_status()
    out_dir = packages_dir(case_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = "".join(ch for ch in created_at if ch.isdigit())[:14]
    tmp_zip = out_dir / f".building_{stamp}_{os.getpid()}.zip"
    tmp_enc = tmp_zip.with_suffix(".nrkenc")
    try:
        with open(tmp_zip, "wb") as f:
            res = builder.build(
                db,
                case_id,
                f,
                created_at=created_at,
                created_by=examiner,
                ntp=ntp,
                include_clips=include_clips,
            )
        final_src = tmp_zip
        if passphrase:
            with open(tmp_zip, "rb") as src, open(tmp_enc, "wb") as dst:
                crypto.encrypt_stream(src, dst, passphrase)
            tmp_zip.unlink()  # plaintext copy removed (not scrubbed: see docs/package.md)
            final_src = tmp_enc
        sha = hash_file(final_src).sha256
        suffix = ".zip.nrkenc" if passphrase else ".zip"
        name = f"package_case{case_id}_{stamp}_{sha[:12]}{suffix}"
        final = out_dir / name
        os.chmod(final_src, 0o444)
        final_src.replace(final)
    finally:
        for t in (tmp_zip, tmp_enc):
            if t.exists():
                t.chmod(0o600)
                t.unlink()
    manifest = json.loads(res.manifest)
    row = Package(
        case_id=case_id,
        file_name=name,
        file_path=str(final),
        sha256=sha,
        size_bytes=final.stat().st_size,
        encrypted=bool(passphrase),
        manifest_sha256=hashlib.sha256(res.manifest).hexdigest(),
        signature_hex=res.signature.hex(),
        key_id=keys.key_id(),
        file_count=len(res.files),
        include_clips=include_clips,
        head_hash_built_from=manifest["custody"]["head_hash"],
        created_at=created_at,
        created_by=examiner,
        excluded_json=json.dumps(res.excluded),
    )
    db.add(row)
    db.commit()
    entry = custody.append_entry(
        db,
        case_id,
        "package_created",
        examiner,
        {
            "package_id": row.id,
            "file_name": name,
            "sha256": sha,
            "size_bytes": row.size_bytes,
            "encrypted": row.encrypted,
            "encryption": "AES-256-GCM chunked, scrypt key (docs/package.md)"
            if passphrase
            else "none",
            "manifest_sha256": row.manifest_sha256,
            "manifest_signature": row.signature_hex,
            "package_key_id": row.key_id,
            "files": row.file_count,
            "include_clips": include_clips,
            "excluded": res.excluded,
            "head_hash_built_from": row.head_hash_built_from,
            "head_hash_note": "chain head BEFORE this entry was appended",
        },
    )
    row.custody_seq = entry.seq
    db.commit()
    return row


@router.get("/package-key")
def package_key():
    return {
        "algorithm": "Ed25519",
        "key_id": keys.key_id(),
        "public_key_hex": keys.public_key_hex(),
    }


@router.post("/cases/{case_id}/package", status_code=201)
def post_package(case_id: int, db: DbSession, examiner: Examiner, body: PackageIn | None = None):
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    b = body or PackageIn()
    try:
        row = create_package(
            db,
            case_id,
            examiner,
            include_clips=b.include_clips,
            passphrase=b.passphrase.encode() if b.passphrase else None,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return package_out(row)


@router.get("/cases/{case_id}/packages")
def list_packages(case_id: int, db: DbSession):
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    rows = db.scalars(select(Package).where(Package.case_id == case_id).order_by(Package.id.desc()))
    return [package_out(p) for p in rows]


@router.get("/packages/{package_id}/download")
def download_package(package_id: int, db: DbSession):
    p = db.get(Package, package_id)
    if p is None:
        raise HTTPException(404, "Package not found")
    try:
        observed = hash_file(p.file_path).sha256
    except OSError:
        raise HTTPException(409, "Stored package file is missing; it cannot be served") from None
    if observed != p.sha256:
        raise HTTPException(
            409, f"Stored package no longer matches its recorded SHA-256 ({p.sha256}); not served"
        )
    return FileResponse(
        p.file_path,
        media_type="application/octet-stream" if p.encrypted else "application/zip",
        filename=p.file_name,
    )
