"""DB models for P5. The lead imports this module in app.main and bumps SCHEMA_VERSION."""

from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class TimeAssumption(Base):
    """The examiner's timezone assumption for one evidence item (at most one current row; the
    full history is in the custody log, every change writes an entry)."""

    __tablename__ = "time_assumptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), unique=True, index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)  # IANA or None
    epoch_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)  # utc|device_local
    evidence_kind: Mapped[str] = mapped_column(String(30), default="examiner_entered")
    notes: Mapped[str] = mapped_column(Text, default="")
    examiner: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    updated_at: Mapped[str] = mapped_column(String(40), default=_now)


class ReferenceObservation(Base):
    """Device clock reading paired with a true UTC time (SWGDE 17-V-002-1.4 style)."""

    __tablename__ = "time_references"
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    device_time_raw: Mapped[str] = mapped_column(String(64))  # wall clock as shown, no timezone
    true_time_utc: Mapped[str] = mapped_column(String(40))  # ISO-8601 UTC
    method: Mapped[str] = mapped_column(String(30))  # photo_dvr_clock|known_event|ntp_phone|other
    notes: Mapped[str] = mapped_column(Text, default="")
    photo_path: Mapped[str] = mapped_column(Text, default="")  # reference only, not copied
    reading_uncertainty_s: Mapped[float] = mapped_column(Float, default=1.0)
    examiner: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class TimeModel(Base):
    """A stored fitted offset/drift model (append-only: refits add rows, latest is used)."""

    __tablename__ = "time_models"
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    model_json: Mapped[str] = mapped_column(Text)
    timezone_used: Mapped[str] = mapped_column(String(64), default="")
    examiner: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class OsdCheck(Base):
    """Latest stored OSD cross-check result per run (append-only)."""

    __tablename__ = "osd_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    clip_id: Mapped[int] = mapped_column(Integer, index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    result_json: Mapped[str] = mapped_column(Text)
    examiner: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
