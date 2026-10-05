"""Read-only acquisition and verify-on-read.

Sources (image files, block devices) are opened O_RDONLY only. The acquired copy is written once
into the case workspace, made 0444, and re-hashed from disk before the acquisition is recorded.
Every later analysis stage must obtain the image through open_verified(), which re-hashes first.

Block-device acquisition is exercised only with file-backed fixtures and mocked stat results in
tests; acquiring a real disk is UNVERIFIED.
"""

import os
import stat
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session

from app import custody
from app.clock import utc_now_iso
from app.config import allow_block_devices, data_dir, evidence_roots
from app.hashing import CHUNK, Digests, hash_file, hash_stream
from app.models import Evidence


class AcquisitionError(Exception):
    """Caller-correctable problem with the source (maps to HTTP 400)."""


class PathNotAllowed(AcquisitionError):
    """Source is outside the configured evidence roots / block devices disabled (HTTP 403)."""


class IntegrityError(Exception):
    """Stored image no longer matches its recorded hashes (maps to HTTP 409)."""


def classify(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISBLK(mode):
        return "block_device"
    raise AcquisitionError("source must be a regular file or a block device")


def open_source_readonly(path: str) -> tuple[int, str, int, Path]:
    """Return (fd, source_type, reported_size, resolved_path). The only place a source is opened.

    The path is fully resolved (symlinks followed, ../ collapsed) *before* the policy check, and
    the resolved path is what gets opened (O_NOFOLLOW), so a symlink under an evidence root that
    points elsewhere is judged by its target.
    """
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        st = os.stat(resolved)
    except (OSError, RuntimeError) as exc:
        raise AcquisitionError(f"cannot stat source: {getattr(exc, 'strerror', exc)}") from exc
    kind = classify(st.st_mode)
    if kind == "block_device":
        if not allow_block_devices():
            raise PathNotAllowed("block devices are disabled (set NIRIKSHAN_ALLOW_BLOCK_DEVICES=1)")
    else:
        roots = evidence_roots()
        if not roots:
            raise PathNotAllowed("no evidence roots configured (set NIRIKSHAN_EVIDENCE_ROOTS)")
        if not any(resolved.is_relative_to(r) for r in roots):
            raise PathNotAllowed("source is outside the configured evidence roots")
    try:
        fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise AcquisitionError(f"cannot open source read-only: {exc.strerror}") from exc
    size = st.st_size if kind == "file" else os.lseek(fd, 0, os.SEEK_END)
    os.lseek(fd, 0, os.SEEK_SET)
    return fd, kind, size, resolved


def image_dir(case_id: int) -> Path:
    return data_dir() / "cases" / str(case_id) / "evidence"


def acquire(
    db: Session, case_id: int, source_path: str, label: str, write_blocker: str, examiner: str
) -> Evidence:
    fd, kind, reported, resolved = open_source_readonly(source_path)
    ev = Evidence(
        case_id=case_id,
        label=label,
        source_path=str(resolved),
        source_type=kind,
        write_blocker=write_blocker,
        status="acquiring",
        examiner=examiner,
    )
    db.add(ev)
    db.commit()
    dest = image_dir(case_id) / f"{ev.id}.img"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(fd, "rb", closefd=True) as src:
            out_fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(out_fd, "wb") as out:
                src_digests = hash_stream(src, out)
                out.flush()
                os.fsync(out.fileno())
        dest.chmod(0o444)
        copy_digests = hash_file(dest)  # re-read from disk: proves what was stored
        if copy_digests != src_digests:
            raise IntegrityError("acquired copy does not match source stream hashes")
        if kind == "file" and src_digests.size != reported:
            raise IntegrityError("bytes read differ from source size (source changed during read?)")
    except (OSError, IntegrityError) as exc:
        dest.unlink(missing_ok=True)
        ev.status = "failed"
        db.commit()
        custody.append_entry(
            db,
            case_id,
            "acquisition_failed",
            examiner,
            {"source_path": ev.source_path, "error": str(exc)},
            ev.id,
        )
        raise AcquisitionError(f"acquisition failed: {exc}") from exc
    ev.status = "acquired"
    ev.image_path = str(dest)
    ev.size_bytes, ev.md5, ev.sha256 = src_digests.size, src_digests.md5, src_digests.sha256
    ev.acquired_at = utc_now_iso()
    ev.last_verified_at, ev.last_verify_ok = utc_now_iso(), 1
    db.commit()
    custody.append_entry(
        db,
        case_id,
        "evidence_acquired",
        examiner,
        {
            "label": label,
            "requested_path": source_path,
            "source_path": ev.source_path,
            "source_type": kind,
            "write_blocker_used": write_blocker,
            "size_bytes": ev.size_bytes,
            "md5": ev.md5,
            "sha256": ev.sha256,
            "post_copy_verify": "pass",
        },
        ev.id,
    )
    return ev


def verify_evidence(db: Session, ev: Evidence, examiner: str) -> dict:
    """Re-hash the stored image and compare with the acquisition hashes. Always logs custody."""
    try:
        observed: Digests | None = hash_file(ev.image_path)
        error = ""
    except OSError as exc:
        observed, error = None, f"cannot read image: {exc.strerror}"
    ok = observed is not None and (observed.md5, observed.sha256, observed.size) == (
        ev.md5,
        ev.sha256,
        ev.size_bytes,
    )
    ev.last_verified_at, ev.last_verify_ok = utc_now_iso(), int(ok)
    if not ok:
        ev.status = "integrity_failed"
    db.commit()
    result = {
        "ok": ok,
        "expected": {"md5": ev.md5, "sha256": ev.sha256, "size_bytes": ev.size_bytes},
        "observed": None
        if observed is None
        else {"md5": observed.md5, "sha256": observed.sha256, "size_bytes": observed.size},
        "error": error,
    }
    custody.append_entry(db, ev.case_id, "evidence_verified", examiner, {"ok": ok, **result}, ev.id)
    return result


@contextmanager
def open_verified(db: Session, ev: Evidence, examiner: str):
    """Entry point for every analysis stage: verify, then hand out a read-only file object."""
    if ev.status not in ("acquired", "integrity_failed"):
        raise IntegrityError(f"evidence {ev.id} is not acquired (status={ev.status})")
    if not verify_evidence(db, ev, examiner)["ok"]:
        raise IntegrityError(f"evidence {ev.id} failed verification; refusing to analyse")
    with open(ev.image_path, "rb") as f:
        yield f


__all__ = ["CHUNK", "acquire", "open_verified", "verify_evidence"]
