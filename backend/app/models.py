from datetime import datetime, timezone

from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class SchemaMeta(Base):
    """Single-row schema version marker (no migrations framework yet)."""

    __tablename__ = "schema_meta"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)


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


class CarveRun(Base):
    """One identify + carve pass over an evidence item (read via open_verified only)."""

    __tablename__ = "carve_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))  # running | completed | failed
    examiner: Mapped[str] = mapped_column(String(200))
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    vendor_json: Mapped[str] = mapped_column(Text, default="[]")
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    parse_json: Mapped[str] = mapped_column(Text, default="[]")  # structured parser results
    tool_version: Mapped[str] = mapped_column(String(50), default="")
    ffmpeg_version: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[str] = mapped_column(String(40), default=_now)
    finished_at: Mapped[str] = mapped_column(String(40), default="")
    ident_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    carve_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")


class Clip(Base):
    """A carved clip, or an orphan range that could not become a clip (kind='orphan')."""

    __tablename__ = "clips"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("carve_runs.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(Integer, index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # clip | orphan
    seq: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str] = mapped_column(String(10))
    start_offset: Mapped[int] = mapped_column(BigInteger)
    end_offset: Mapped[int] = mapped_column(BigInteger)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    extents_json: Mapped[str] = mapped_column(Text, default="[]")
    nal_count: Mapped[int] = mapped_column(Integer, default=0)
    irap_count: Mapped[int] = mapped_column(Integer, default=0)
    vcl_count: Mapped[int] = mapped_column(Integer, default=0)
    reassembled: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")  # end reason (clip) / why orphaned
    notes_json: Mapped[str] = mapped_column(Text, default="[]")
    bitstream_sha256: Mapped[str] = mapped_column(String(64), default="")
    mp4_path: Mapped[str] = mapped_column(Text, default="")
    mp4_sha256: Mapped[str] = mapped_column(String(64), default="")
    decode_status: Mapped[str] = mapped_column(String(20), default="not_exported")
    decode_errors_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str] = mapped_column(Text, default="")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[str] = mapped_column(String(20), default="")
    packets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine: Mapped[str] = mapped_column(String(30), default="generic")  # generic | <vendor> parser
    channel: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_json: Mapped[str] = mapped_column(Text, default="{}")  # parser fields/timestamps
