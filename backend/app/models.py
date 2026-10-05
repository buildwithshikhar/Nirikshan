from datetime import datetime, timezone

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_number: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    examiner: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    label: Mapped[str] = mapped_column(String(300))
    source_path: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20))  # file | block_device
    write_blocker: Mapped[str] = mapped_column(String(10))  # yes | no | unknown (attestation)
    status: Mapped[str] = mapped_column(
        String(20)
    )  # acquiring | acquired | failed | integrity_failed
    image_path: Mapped[str] = mapped_column(Text, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    md5: Mapped[str] = mapped_column(String(32), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    examiner: Mapped[str] = mapped_column(String(200))
    acquired_at: Mapped[str] = mapped_column(String(40), default=_now)
    last_verified_at: Mapped[str] = mapped_column(String(40), default="")
    last_verify_ok: Mapped[int] = mapped_column(Integer, default=-1)  # -1 never, 0 fail, 1 pass


class CustodyEntry(Base):
    """Append-only (no update/delete code path). Integrity comes from hash chain + signatures."""

    __tablename__ = "custody_entries"
    __table_args__ = (UniqueConstraint("case_id", "seq"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    timestamp_utc: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(50))
    evidence_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    examiner: Mapped[str] = mapped_column(String(200))
    tool_version: Mapped[str] = mapped_column(String(50))
    ntp_status: Mapped[str] = mapped_column(String(20))
    details_json: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(String(128))
    key_id: Mapped[str] = mapped_column(String(16))


class AuditEntry(Base):
    """Every API request (examiner header is an attestation, not authentication)."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp_utc: Mapped[str] = mapped_column(String(40), default=_now)
    examiner: Mapped[str] = mapped_column(String(200), default="")
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
