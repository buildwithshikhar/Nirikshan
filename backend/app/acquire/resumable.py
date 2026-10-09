"""Resumable acquisition with read-error handling (bad-sector map).

Design (docs/acquisition.md):
  * The source is opened only through evidence.open_source_readonly (allow-list, O_RDONLY).
  * The copy is written chunk by chunk to `<id>.img.partial`. After every chunk the bytes are
    fsync'ed and a checkpoint row is committed: `bytes_done` and the SHA-256 of that chunk as
    written. Python's hashlib state cannot be serialised, so no running whole-file hash is kept.
  * A read error (OSError) on a chunk is retried; if it persists, the chunk is re-read sector by
    sector and every sector that still fails is written as zero bytes and recorded as a range in
    the bad-sector map. The copy is therefore NOT a bit-identical image of the source in those
    ranges, and the evidence hashes cover the zero-filled copy (custody and the API say so).
  * Resume: the partial copy is truncated to `bytes_done`, every checkpointed chunk is re-hashed
    and compared with the stored digest, the source is re-opened and must have the same type and
    size, and the last checkpointed chunk is re-read from the source and compared (a spot check,
    skipped if that chunk contained read errors). Any mismatch refuses the resume.
  * Completion: the whole copy is re-read once, each chunk is compared with its checkpoint and the
    whole-file MD5 + SHA-256 are computed in the same pass; the copy is renamed to `<id>.img`
    and made read-only.

Limits: the resume spot check re-reads one chunk, so a source modified in an earlier region while
the acquisition was interrupted is not detected at resume time. Block devices remain opt-in and
UNVERIFIED on real disks (tests use files and an injected faulty reader).
"""

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app import custody, synthetic
from app.acquire.models import AcquisitionSession
from app.clock import utc_now_iso
from app.evidence import (
    AcquisitionError,
    IntegrityError,
    PathNotAllowed,
    image_dir,
    open_source_readonly,
)
from app.models import Evidence

DEFAULT_CHUNK = 4 * 1024 * 1024
MIN_CHUNK, MAX_CHUNK = 64 * 1024, 64 * 1024 * 1024
SECTOR = 512
MAX_RETRIES = 5
MAX_CUSTODY_RANGES = 200  # ranges listed inline in a custody entry (the total is always given)

Reader = Callable[[int, int], bytes]  # (offset, n) -> bytes; raises OSError on a read error

HASH_SCOPE_NOTE = (
    "Unreadable source ranges were replaced by zero bytes in the copy. MD5/SHA-256 cover the "
    "zero-filled copy, not the source medium; the zero-filled ranges are listed in the "
    "bad-sector map."
)


def fd_reader(fd: int, size: int) -> Reader:
    def read(off: int, n: int) -> bytes:
        return os.pread(fd, n, off)

    return read


# Test hook: replaced by a fault-injecting reader in tests. Production uses os.pread.
READER_FACTORY: Callable[[int, int], Reader] = fd_reader

_active: set[int] = set()  # sessions currently copying in this process


class ResumeRefused(AcquisitionError):
    """The checkpoint, the partial copy or the source does not match (maps to HTTP 409)."""


def _check_params(chunk_size: int, retries: int) -> None:
    if not MIN_CHUNK <= chunk_size <= MAX_CHUNK or chunk_size % SECTOR:
        raise AcquisitionError(
            f"chunk_size must be a multiple of {SECTOR} between {MIN_CHUNK} and {MAX_CHUNK}"
        )
    if not 0 <= retries <= MAX_RETRIES:
        raise AcquisitionError(f"retries must be between 0 and {MAX_RETRIES}")


def _merge(ranges: list[list], new: list[list]) -> list[list]:
    out = [list(r) for r in ranges]
    for s, e, err in new:
        if out and out[-1][1] == s and out[-1][2] == err:
            out[-1][1] = e
        else:
            out.append([s, e, err])
    return out


def _read_retry(reader: Reader, off: int, n: int, retries: int) -> bytes:
    last: OSError | None = None
    for _ in range(retries + 1):
        try:
            return reader(off, n)
        except OSError as exc:
            last = exc
    raise last  # type: ignore[misc]


def read_chunk(
    reader: Reader, off: int, n: int, retries: int, sector: int = SECTOR
) -> tuple[bytes, list[list]]:
    """Read n bytes at off. Returns (data, bad ranges [[start, end, error]]). Short reads raise
    AcquisitionError (the source is smaller than reported: changed or truncated)."""
    try:
        data = _read_retry(reader, off, n, retries)
        if len(data) != n:
            raise AcquisitionError(f"short read at offset {off}: source changed or truncated?")
        return data, []
    except OSError:
        pass
    parts, bad = [], []
    for s in range(off, off + n, sector):
        m = min(sector, off + n - s)
        try:
            b = _read_retry(reader, s, m, retries)
            if len(b) != m:
                raise AcquisitionError(f"short read at offset {s}: source changed or truncated?")
        except OSError as exc:
            b = bytes(m)
            err = exc.strerror or type(exc).__name__
            bad = _merge(bad, [[s, s + m, err]])
        parts.append(b)
    return b"".join(parts), bad


def _partial(ev: Evidence) -> Path:
    return image_dir(ev.case_id) / f"{ev.id}.img.partial"


def _fail(db: Session, sess: AcquisitionSession, ev: Evidence, examiner: str, msg: str) -> None:
    sess.status, sess.error, sess.updated_at = "failed", msg, utc_now_iso()
    ev.status = "failed"
    db.commit()
    custody.append_entry(
        db,
        ev.case_id,
        "acquisition_failed",
        examiner,
        {"session_id": sess.id, "source_path": sess.source_path, "error": msg},
        ev.id,
    )


def start(
    db: Session,
    case_id: int,
    source_path: str,
    label: str,
    write_blocker: str,
    examiner: str,
    *,
    mode: str = "image",
    chunk_size: int = DEFAULT_CHUNK,
    retries: int = 1,
    stop_after_chunks: int | None = None,
) -> AcquisitionSession:
    """Begin a resumable acquisition. `stop_after_chunks` simulates an interruption (tests)."""
    _check_params(chunk_size, retries)
    fd, kind, size, resolved = open_source_readonly(source_path)
    try:
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
        dest = _partial(ev)
        dest.parent.mkdir(parents=True, exist_ok=True)
        sess = AcquisitionSession(
            case_id=case_id,
            evidence_id=ev.id,
            mode=mode,
            source_path=str(resolved),
            source_type=kind,
            source_size=size,
            chunk_size=chunk_size,
            sector_size=SECTOR,
            retries=retries,
            partial_path=str(dest),
            examiner=examiner,
        )
        db.add(sess)
        db.commit()
        custody.append_entry(
            db,
            case_id,
            "acquisition_started",
            examiner,
            {
                "session_id": sess.id,
                "mode": mode,
                "requested_path": source_path,
                "source_path": str(resolved),
                "source_type": kind,
                "source_size": size,
                "chunk_size": chunk_size,
                "retries": retries,
                "write_blocker_used": write_blocker,
            },
            ev.id,
        )
        out = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        return _run(db, sess, ev, fd, out, examiner, stop_after_chunks)
    finally:
        os.close(fd)


def resume(
    db: Session,
    sess: AcquisitionSession,
    examiner: str,
    *,
    stop_after_chunks: int | None = None,
) -> AcquisitionSession:
    if sess.status not in ("interrupted", "in_progress"):
        raise ResumeRefused(f"session {sess.id} is {sess.status}; only interrupted sessions resume")
    if sess.id in _active:
        raise ResumeRefused(f"session {sess.id} is still copying in this process")
    ev = db.get(Evidence, sess.evidence_id)
    dest = Path(sess.partial_path)
    hashes: list[str] = json.loads(sess.chunk_sha256_json)
    checks: dict = {"prefix_bytes": sess.bytes_done, "prefix_chunks": len(hashes)}

    def refuse(msg: str) -> None:
        checks["result"] = "refused"
        custody.append_entry(
            db,
            ev.case_id,
            "acquisition_resume_refused",
            examiner,
            {"session_id": sess.id, "reason": msg, **checks},
            ev.id,
        )
        _fail(db, sess, ev, examiner, f"resume refused: {msg}")
        raise ResumeRefused(f"resume refused: {msg}")

    if not dest.is_file():
        refuse("partial copy is missing")
    have = dest.stat().st_size
    if have < sess.bytes_done:
        refuse(f"partial copy has {have} bytes, checkpoint says {sess.bytes_done}")
    checks["truncated_unconfirmed_bytes"] = have - sess.bytes_done
    if have > sess.bytes_done:  # bytes written after the last committed checkpoint
        os.truncate(dest, sess.bytes_done)
    bad_idx = _bad_chunks(sess)
    with open(dest, "rb") as f:
        for i, want in enumerate(hashes):
            got = hashlib.sha256(f.read(sess.chunk_size)).hexdigest()
            if got != want:
                refuse(f"partial copy chunk {i} does not match its checkpoint digest")
    checks["prefix_verified"] = True
    try:
        fd, kind, size, _resolved = open_source_readonly(sess.source_path)
    except (AcquisitionError, PathNotAllowed) as exc:
        refuse(f"cannot reopen source: {exc}")
    try:
        if kind != sess.source_type or size != sess.source_size:
            refuse(
                f"source changed: {kind}/{size} bytes, checkpoint {sess.source_type}/"
                f"{sess.source_size} bytes"
            )
        if hashes and (len(hashes) - 1) not in bad_idx:
            i = len(hashes) - 1
            off = i * sess.chunk_size
            n = min(sess.chunk_size, sess.source_size - off)
            reader = READER_FACTORY(fd, size)
            try:
                data, bad = read_chunk(reader, off, n, sess.retries)
            except AcquisitionError as exc:
                refuse(str(exc))
            if bad or hashlib.sha256(data).hexdigest() != hashes[i]:
                refuse(f"source chunk {i} re-read differs from the checkpoint (source changed?)")
            checks["source_spot_check_chunk"] = i
        else:
            checks["source_spot_check_chunk"] = None
        sess.resumes += 1
        db.commit()
        custody.append_entry(
            db,
            ev.case_id,
            "acquisition_resumed",
            examiner,
            {"session_id": sess.id, "result": "accepted", **checks},
            ev.id,
        )
        out = os.open(dest, os.O_WRONLY)
        return _run(db, sess, ev, fd, out, examiner, stop_after_chunks)
    finally:
        os.close(fd)


def _bad_chunks(sess: AcquisitionSession) -> set[int]:
    out = set()
    for s, e, _err in json.loads(sess.bad_ranges_json):
        out.update(range(s // sess.chunk_size, (e - 1) // sess.chunk_size + 1))
    return out


def _run(db, sess, ev, fd, out, examiner, stop_after_chunks) -> AcquisitionSession:
    _active.add(sess.id)
    try:
        reader = READER_FACTORY(fd, sess.source_size)
        hashes: list[str] = json.loads(sess.chunk_sha256_json)
        bad: list[list] = json.loads(sess.bad_ranges_json)
        off, done_now = sess.bytes_done, 0
        sess.status = "in_progress"
        db.commit()
        try:
            while off < sess.source_size:
                if stop_after_chunks is not None and done_now >= stop_after_chunks:
                    sess.status, sess.updated_at = "interrupted", utc_now_iso()
                    db.commit()
                    custody.append_entry(
                        db,
                        ev.case_id,
                        "acquisition_interrupted",
                        examiner,
                        {"session_id": sess.id, "bytes_done": off, "chunks": len(hashes)},
                        ev.id,
                    )
                    return sess
                n = min(sess.chunk_size, sess.source_size - off)
                data, errs = read_chunk(reader, off, n, sess.retries, sess.sector_size)
                os.pwrite(out, data, off)
                os.fsync(out)
                hashes.append(hashlib.sha256(data).hexdigest())
                bad = _merge(bad, errs)
                off += n
                done_now += 1
                sess.bytes_done = off
                sess.chunk_sha256_json = json.dumps(hashes)
                sess.bad_ranges_json = json.dumps(bad)
                sess.updated_at = utc_now_iso()
                db.commit()  # checkpoint
        except (OSError, AcquisitionError) as exc:  # write failure or a changed source
            sess.status, sess.error = "interrupted", f"{type(exc).__name__}: {exc}"
            db.commit()
            custody.append_entry(
                db,
                ev.case_id,
                "acquisition_interrupted",
                examiner,
                {"session_id": sess.id, "bytes_done": sess.bytes_done, "error": sess.error},
                ev.id,
            )
            raise AcquisitionError(f"acquisition interrupted: {exc}; resume is possible") from exc
    finally:
        os.close(out)
        _active.discard(sess.id)
    return _finish(db, sess, ev, examiner)


def _finish(db: Session, sess: AcquisitionSession, ev: Evidence, examiner: str):
    hashes = json.loads(sess.chunk_sha256_json)
    bad = json.loads(sess.bad_ranges_json)
    partial = Path(sess.partial_path)
    md5, sha = hashlib.md5(usedforsecurity=False), hashlib.sha256()
    size = 0
    with open(partial, "rb") as f:
        for i, want in enumerate(hashes):
            chunk = f.read(sess.chunk_size)
            if hashlib.sha256(chunk).hexdigest() != want:
                _fail(db, sess, ev, examiner, f"copy chunk {i} differs from its checkpoint")
                raise IntegrityError(f"acquired copy chunk {i} does not match its checkpoint")
            md5.update(chunk)
            sha.update(chunk)
            size += len(chunk)
        if f.read(1):
            _fail(db, sess, ev, examiner, "copy is longer than the checkpointed bytes")
            raise IntegrityError("acquired copy is longer than the checkpointed bytes")
    if size != sess.source_size:
        _fail(db, sess, ev, examiner, f"copy has {size} bytes, source {sess.source_size}")
        raise IntegrityError("acquired copy size differs from the source size")
    dest = image_dir(ev.case_id) / f"{ev.id}.img"
    os.replace(partial, dest)
    dest.chmod(0o444)
    bad_bytes = sum(e - s for s, e, _ in bad)
    now = utc_now_iso()
    ev.status, ev.image_path = "acquired", str(dest)
    ev.size_bytes, ev.md5, ev.sha256 = size, md5.hexdigest(), sha.hexdigest()
    ev.acquired_at = now
    ev.last_verified_at, ev.last_verify_ok = now, 1
    ev.synthetic = synthetic.is_synthetic_image(dest)
    sess.status, sess.partial_path, sess.updated_at = "completed", str(dest), now
    db.commit()
    details = {
        "session_id": sess.id,
        "mode": sess.mode,
        "acquisition_method": "resumable chunked copy",
        "label": ev.label,
        "source_path": ev.source_path,
        "source_type": ev.source_type,
        "write_blocker_used": ev.write_blocker,
        "size_bytes": size,
        "md5": ev.md5,
        "sha256": ev.sha256,
        "chunk_size": sess.chunk_size,
        "chunks": len(hashes),
        "chunk_sha256_list_sha256": hashlib.sha256("".join(hashes).encode()).hexdigest(),
        "resumes": sess.resumes,
        "post_copy_verify": "pass (copy re-read; every chunk matched its checkpoint digest)",
        "bad_sector_ranges": len(bad),
        "bad_sector_bytes": bad_bytes,
        "bad_sector_map": bad[:MAX_CUSTODY_RANGES],
        "zero_filled": bool(bad),
        "hash_scope": HASH_SCOPE_NOTE if bad else "copy is complete; no read errors occurred",
        "synthetic_banner": ev.synthetic,
    }
    if ev.source_type == "block_device":
        details["block_device_note"] = "block-device acquisition is unverified on real disks"
    custody.append_entry(db, ev.case_id, "evidence_acquired", examiner, details, ev.id)
    return sess


def session_out(sess: AcquisitionSession) -> dict:
    bad = json.loads(sess.bad_ranges_json)
    return {
        "id": sess.id,
        "case_id": sess.case_id,
        "evidence_id": sess.evidence_id,
        "mode": sess.mode,
        "status": sess.status,
        "source_path": sess.source_path,
        "source_type": sess.source_type,
        "source_size": sess.source_size,
        "bytes_done": sess.bytes_done,
        "progress": round(sess.bytes_done / sess.source_size, 4) if sess.source_size else 1.0,
        "chunk_size": sess.chunk_size,
        "chunks_checkpointed": len(json.loads(sess.chunk_sha256_json)),
        "retries": sess.retries,
        "resumes": sess.resumes,
        "error": sess.error,
        "bad_sector_map": {
            "ranges": [{"start": s, "end": e, "bytes": e - s, "error": err} for s, e, err in bad],
            "range_count": len(bad),
            "bytes": sum(e - s for s, e, _ in bad),
            "sector_size": sess.sector_size,
            "zero_filled": bool(bad),
            "hash_scope": HASH_SCOPE_NOTE if bad else "no read errors recorded",
        },
        "created_at": sess.created_at,
        "updated_at": sess.updated_at,
    }
