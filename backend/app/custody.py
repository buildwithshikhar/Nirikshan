"""Hash-chained, Ed25519-signed custody log (one chain per case).

entry_hash = SHA-256(canonical JSON of all entry fields incl. prev_hash); signature signs
entry_hash. A fully recomputed chain still fails signature verification without the key.
Limitation: deleting the newest entries leaves a valid shorter chain; record `head_hash`
externally (e.g. on the report) to detect truncation.
"""

import hashlib
import json
import threading

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import __version__, signing
from app.clock import ntp_status, utc_now_iso
from app.models import CustodyEntry

GENESIS = "0" * 64


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def entry_payload(e: CustodyEntry) -> dict:
    return {
        "v": 1,
        "case_id": e.case_id,
        "seq": e.seq,
        "timestamp_utc": e.timestamp_utc,
        "action": e.action,
        "evidence_id": e.evidence_id,
        "examiner": e.examiner,
        "tool_version": e.tool_version,
        "ntp_status": e.ntp_status,
        "details": json.loads(e.details_json),
        "prev_hash": e.prev_hash,
    }


def compute_hash(e: CustodyEntry) -> str:
    return hashlib.sha256(canonical_json(entry_payload(e)).encode()).hexdigest()


_APPEND_LOCK = threading.Lock()
APPEND_RETRIES = 5


def append_entry(
    db: Session,
    case_id: int,
    action: str,
    examiner: str,
    details: dict,
    evidence_id: int | None = None,
) -> CustodyEntry:
    """Append the next entry of the case chain. Serialised in-process (concurrent jobs of one
    case would otherwise read the same head and collide on (case_id, seq)); a collision with
    another process is retried against the new head."""
    for attempt in range(APPEND_RETRIES):
        with _APPEND_LOCK:
            try:
                return _append(db, case_id, action, examiner, details, evidence_id)
            except IntegrityError:
                db.rollback()
                if attempt == APPEND_RETRIES - 1:
                    raise
    raise RuntimeError("unreachable")


def _append(db, case_id, action, examiner, details, evidence_id) -> CustodyEntry:
    last = db.scalars(
        select(CustodyEntry)
        .where(CustodyEntry.case_id == case_id)
        .order_by(CustodyEntry.seq.desc())
        .limit(1)
    ).first()
    entry = CustodyEntry(
        case_id=case_id,
        seq=(last.seq + 1) if last else 1,
        timestamp_utc=utc_now_iso(),
        action=action,
        evidence_id=evidence_id,
        examiner=examiner,
        tool_version=__version__,
        ntp_status=ntp_status(),
        details_json=canonical_json(details),
        prev_hash=last.entry_hash if last else GENESIS,
    )
    entry.entry_hash = compute_hash(entry)
    entry.signature = signing.sign(entry.entry_hash.encode())
    entry.key_id = signing.key_id(signing.public_key())
    db.add(entry)
    db.commit()
    return entry


def verify_chain(db: Session, case_id: int) -> dict:
    """Check sequence, hash links, recomputed hashes and signatures. Never raises on tampering."""
    entries = db.scalars(
        select(CustodyEntry).where(CustodyEntry.case_id == case_id).order_by(CustodyEntry.seq)
    ).all()
    pub = signing.public_key()
    kid = signing.key_id(pub)
    failures: list[dict] = []

    def fail(seq: int, reason: str) -> None:
        failures.append({"seq": seq, "reason": reason})

    prev = GENESIS
    for i, e in enumerate(entries, start=1):
        if e.seq != i:
            fail(e.seq, f"sequence gap or reorder (expected {i})")
        if e.prev_hash != prev:
            fail(e.seq, "prev_hash does not match previous entry_hash")
        try:
            recomputed = compute_hash(e)
        except ValueError:
            recomputed = ""
            fail(e.seq, "details not parseable")
        if recomputed and recomputed != e.entry_hash:
            fail(e.seq, "entry_hash does not match entry contents")
        if e.key_id != kid:
            fail(e.seq, f"signed with unknown key {e.key_id}")
        elif not signing.verify(pub, e.entry_hash.encode(), e.signature):
            fail(e.seq, "invalid signature")
        prev = e.entry_hash
    return {
        "ok": not failures,
        "entries": len(entries),
        "head_hash": prev,
        "key_id": kid,
        "failures": failures,
    }
