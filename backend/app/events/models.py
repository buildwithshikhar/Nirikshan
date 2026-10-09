"""Indexed AI events (derived from analytics rows; rebuildable). No identity/embedding columns.

The lead imports this module in app.main (so create_all sees the table) and bumps SCHEMA_VERSION.
"""

from sqlalchemy import BigInteger, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.analytics import TRIAGE_LABEL
from app.db import Base
from app.models import _now


class IndexedEvent(Base):
    """One motion interval or one object/face detection box, with its clip placement.

    `source_kind` + `source_row_id` point back at motion_intervals / detections; the unique
    constraint makes reindexing idempotent and keeps event ids stable across reindexes."""

    __tablename__ = "ai_events"
    __table_args__ = (UniqueConstraint("source_kind", "source_row_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    evidence_id: Mapped[int] = mapped_column(Integer, index=True)
    clip_id: Mapped[int] = mapped_column(Integer, index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    source_kind: Mapped[str] = mapped_column(String(12))  # detection | motion
    source_row_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))  # motion | objects | faces
    class_name: Mapped[str] = mapped_column(String(40), index=True)
    channel: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    frame_index: Mapped[int] = mapped_column(Integer)
    end_frame_index: Mapped[int] = mapped_column(Integer)
    nominal_time_s: Mapped[float] = mapped_column(Float)  # within the clip (frame / stream fps)
    nominal_end_s: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # None for motion
    motion_score_peak: Mapped[float | None] = mapped_column(Float, nullable=True)
    placement: Mapped[str] = mapped_column(String(12))  # placed | unplaceable
    unplaceable_reason: Mapped[str] = mapped_column(Text, default="")
    tz_status: Mapped[str] = mapped_column(String(20), default="unknown")
    assumed_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    utc_lo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    utc_hi: Mapped[str | None] = mapped_column(String(40), nullable=True)
    utc_end_lo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    utc_end_hi: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_name: Mapped[str] = mapped_column(String(80), default="")
    model_sha256: Mapped[str] = mapped_column(String(64), default="")
    clip_bitstream_sha256: Mapped[str] = mapped_column(String(64), default="")
    clip_mp4_sha256: Mapped[str] = mapped_column(String(64), default="")
    clip_start_offset: Mapped[int] = mapped_column(BigInteger, default=0)
    clip_end_offset: Mapped[int] = mapped_column(BigInteger, default=0)
    clip_extents_json: Mapped[str] = mapped_column(Text, default="[]")
    search_text: Mapped[str] = mapped_column(Text, default="")
    label: Mapped[str] = mapped_column(String(60), default=TRIAGE_LABEL)
    indexed_at: Mapped[str] = mapped_column(String(40), default=_now)
