"""Lightweight integrity gate for small, frequent, read-only reads (hex view, region scan).

A full re-hash (evidence.open_verified) per 4 KiB hex read would re-read the whole image and
write a custody entry each time. Instead, reads are allowed only when:
  * the evidence is `acquired` and its most recent full verification PASSED (last_verify_ok == 1;
    every analysis run and POST /evidence/{id}/verify performs one and custody-logs it), and
  * the stored copy still has the recorded size and no write permission bit (made 0444 at
    acquisition).
This does NOT prove the bytes are unchanged since the last full verification; the response
carries the time of that verification so the examiner can re-verify.
Limits: docs/storage-explorer.md.
"""

import os
import stat
from pathlib import Path

from fastapi import HTTPException

from app.models import Evidence


def get_evidence(db, evidence_id: int) -> Evidence:
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    return ev


def check(ev: Evidence) -> dict:
    """Raise HTTP 409 unless the light gate passes. Returns the gate description."""
    if ev.status != "acquired":
        raise HTTPException(409, f"evidence {ev.id} is not readable (status={ev.status})")
    if ev.last_verify_ok != 1:
        raise HTTPException(
            409, f"evidence {ev.id} has no passing full verification; POST /verify first"
        )
    try:
        st = os.stat(ev.image_path)
    except OSError as exc:
        raise HTTPException(409, f"stored image unreadable: {exc.strerror}") from exc
    if st.st_size != ev.size_bytes:
        raise HTTPException(409, "stored image size differs from the acquisition record")
    if stat.S_IMODE(st.st_mode) & 0o222:
        raise HTTPException(409, "stored image is writable; refusing (expected mode 0444)")
    return {
        "gate": "light (size + read-only mode + last full verification passed)",
        "last_full_verification": ev.last_verified_at,
        "evidence_sha256": ev.sha256,
    }


def open_image(ev: Evidence):
    return open(Path(ev.image_path), "rb")
