"""Evidence intake helpers for the acquisition wizard.

GET  /api/evidence-files?path=          list files and folders inside the evidence roots (read-only)
POST /api/cases/{case_id}/uploads?filename=   stream a browser upload to the incoming folder

Both are confined to NIRIKSHAN_EVIDENCE_ROOTS. Uploaded bytes are never executed or parsed here: the
file is stored under a generated name, hashed on arrival and recorded in the custody chain; the
examiner then acquires it like any other source (which hashes it again into the case).
"""

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import anyio
from fastapi import APIRouter, HTTPException, Request

from app import custody
from app.config import evidence_roots, incoming_dir, max_upload_bytes, public_instance
from app.models import Case
from app.routes import DbSession, Examiner

router = APIRouter(prefix="/api")

MAX_ENTRIES = 1000
CHUNK = 1024 * 1024
_BAD_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")


def _inside_roots(p: Path) -> bool:
    return any(p.is_relative_to(r) for r in evidence_roots())


@router.get("/evidence-files")
def list_evidence_files(path: str = "") -> dict:
    """Entries of one folder under an evidence root. No path = the roots themselves. Symlinks whose
    target is outside the roots, and anything not a regular file or folder, are not listed."""
    roots = evidence_roots()
    if not roots:
        return {
            "available": False,
            "reason": "no evidence roots configured (NIRIKSHAN_EVIDENCE_ROOTS)",
        }
    if not path:
        return {
            "available": True,
            "path": "",
            "parent": None,
            "entries": [
                {"name": str(r), "kind": "dir", "size": None, "path": str(r)} for r in roots
            ],
        }
    if "\x00" in path:
        raise HTTPException(400, "invalid path")
    try:
        here = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(404, "folder not found") from None
    if not _inside_roots(here):
        raise HTTPException(403, "path is outside the configured evidence roots")
    if not here.is_dir():
        raise HTTPException(400, "not a folder")
    entries = []
    truncated = False
    try:
        children = sorted(here.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
    except OSError as exc:
        raise HTTPException(403, f"cannot list folder: {exc.strerror}") from None
    for child in children:
        try:
            target = child.resolve(strict=True)
            if not _inside_roots(target):
                continue  # symlink escape: hidden
            st = target.stat()
        except (OSError, RuntimeError):
            continue
        if target.is_dir():
            kind, size = "dir", None
        elif target.is_file():
            kind, size = "file", st.st_size
        else:
            continue
        if len(entries) >= MAX_ENTRIES:
            truncated = True
            break
        entries.append(
            {
                "name": child.name,
                "kind": kind,
                "size": size,
                "path": str(target),
                "symlink": child.is_symlink(),
            }
        )
    parent = here.parent if any(here != r for r in roots) and _inside_roots(here.parent) else None
    return {
        "available": True,
        "path": str(here),
        "parent": str(parent) if parent else "",
        "entries": entries,
        "truncated": truncated,
    }


def _check_filename(name: str) -> str:
    if not name or _BAD_NAME.search(name) or ".." in name or len(name) > 255:
        raise HTTPException(
            400,
            "unsafe or missing filename (path separators, '..' and control characters are refused)",
        )
    return name


@router.get("/uploads/limits")
def upload_limits() -> dict:
    inc = incoming_dir()
    if public_instance():
        return {
            "available": False,
            "reason": "uploads are disabled on a public instance (reference data only)",
        }
    if inc is None:
        return {"available": False, "reason": "no evidence root configured for the incoming folder"}
    return {"available": True, "max_bytes": max_upload_bytes()}


@router.post("/cases/{case_id}/uploads", status_code=201)
async def upload_evidence_file(
    case_id: int, filename: str, request: Request, db: DbSession, examiner: Examiner
):
    """Raw-body upload (application/octet-stream), streamed to disk chunk by chunk."""
    if public_instance():
        raise HTTPException(403, "uploads are disabled on a public instance")
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    original = _check_filename(filename)
    inc = incoming_dir()
    if inc is None:
        raise HTTPException(
            503, "no evidence root is configured, so there is nowhere to store uploads"
        )
    limit = max_upload_bytes()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"file is larger than the upload limit ({limit} bytes)")
    inc.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(inc, 0o700)
    stored = inc / f"upload-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:12]}.bin"
    sha, md5, size = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0
    fd = os.open(stored, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    ok = False
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        413, f"file is larger than the upload limit ({limit} bytes)"
                    )
                sha.update(chunk)
                md5.update(chunk)
                await anyio.to_thread.run_sync(out.write, chunk)
            await anyio.to_thread.run_sync(out.flush)
            await anyio.to_thread.run_sync(os.fsync, out.fileno())
        if size == 0:
            raise HTTPException(400, "empty upload")
        ok = True
    finally:
        if not ok:
            stored.unlink(missing_ok=True)
    entry = custody.append_entry(
        db,
        case_id,
        "file_uploaded_via_browser",
        examiner,
        {
            "note": "uploaded via browser",
            "original_filename": original,
            "size_bytes": size,
            "sha256": sha.hexdigest(),
            "md5": md5.hexdigest(),
            "stored_path": str(stored),
        },
    )
    return {
        "path": str(stored),
        "size_bytes": size,
        "sha256": sha.hexdigest(),
        "md5": md5.hexdigest(),
        "original_filename": original,
        "custody_seq": entry.seq,
    }
