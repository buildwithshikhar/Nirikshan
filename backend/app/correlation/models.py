"""Correlation tables. The lead imports this module in app.main and bumps SCHEMA_VERSION."""

from sqlalchemy import BigInteger, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.correlation import LINK_LABEL
from app.db import Base
from app.models import _now


class CameraTopology(Base):
    """Examiner-defined camera layout of one case (current version; history in custody)."""

    __tablename__ = "camera_topologies"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    nodes_json: Mapped[str] = mapped_column(Text, default="[]")
    edges_json: Mapped[str] = mapped_column(Text, default="[]")
    coordinate_units: Mapped[str] = mapped_column(String(40), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    floorplan_path: Mapped[str] = mapped_column(Text, default="")
    floorplan_sha256: Mapped[str] = mapped_column(String(64), default="")
    floorplan_content_type: Mapped[str] = mapped_column(String(40), default="")
    floorplan_size: Mapped[int] = mapped_column(BigInteger, default=0)
    examiner: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[str] = mapped_column(String(40), default=_now)


class ExternalLog(Base):
    """One imported, examiner-authorised external log file (e.g. door access CSV)."""

    __tablename__ = "external_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    stored_path: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64))
    time_format: Mapped[str] = mapped_column(String(64))
    resolution_s: Mapped[float] = mapped_column(Float)
    mapping_json: Mapped[str] = mapped_column(Text)
    authorization_note: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    rows_unplaced: Mapped[int] = mapped_column(Integer, default=0)
    examiner: Mapped[str] = mapped_column(String(200))
    imported_at: Mapped[str] = mapped_column(String(40), default=_now)


class ExternalLogEntry(Base):
    __tablename__ = "external_log_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    log_id: Mapped[int] = mapped_column(Integer, index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    row_number: Mapped[int] = mapped_column(Integer)  # 1 = first data row after the header
    raw_time: Mapped[str] = mapped_column(String(100))
    event_text: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    utc_lo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    utc_hi: Mapped[str | None] = mapped_column(String(40), nullable=True)
    flags: Mapped[str] = mapped_column(String(100), default="")
    unplaced_reason: Mapped[str] = mapped_column(Text, default="")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")


class CorrelationLink(Base):
    """A candidate link between two observations. Always a SUGGESTION until an analyst decides."""

    __tablename__ = "correlation_links"
    __table_args__ = (UniqueConstraint("case_id", "a_key", "b_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    a_key: Mapped[str] = mapped_column(String(120))
    b_key: Mapped[str] = mapped_column(String(120))
    a_json: Mapped[str] = mapped_column(Text)
    b_json: Mapped[str] = mapped_column(Text)
    rules_json: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    gap_s_min: Mapped[float] = mapped_column(Float)
    gap_s_max: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="suggested")  # |accepted|rejected
    decided_by: Mapped[str] = mapped_column(String(200), default="")
    decided_at: Mapped[str] = mapped_column(String(40), default="")
    decision_note: Mapped[str] = mapped_column(Text, default="")
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    label: Mapped[str] = mapped_column(String(120), default=LINK_LABEL)
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
