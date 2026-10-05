"""DB rows for analytics. No identity, embedding or matching columns exist, by design.

The lead imports this module in app.main (so create_all sees the tables) and bumps SCHEMA_VERSION.
"""

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.analytics import TRIAGE_LABEL
from app.db import Base
from app.models import _now


class AnalyticsRun(Base):
    __tablename__ = "analytics_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    evidence_id: Mapped[int] = mapped_column(Integer, index=True)
    clip_id: Mapped[int] = mapped_column(ForeignKey("clips.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # motion | objects | faces
    status: Mapped[str] = mapped_column(String(20))  # running | completed | failed
    examiner: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(60), default=TRIAGE_LABEL)
    bitstream_sha256: Mapped[str] = mapped_column(String(64), default="")  # of the analysed clip
    mp4_sha256: Mapped[str] = mapped_column(String(64), default="")
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    model_json: Mapped[str] = mapped_column(Text, default="null")  # name/version/licence/sha256
    error_rates_json: Mapped[str] = mapped_column(Text, default="null")
    tool_json: Mapped[str] = mapped_column(Text, default="{}")  # tool/ffmpeg/onnxruntime versions
    frames_analysed: Mapped[int] = mapped_column(Integer, default=0)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    ms_per_frame: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[str] = mapped_column(String(40), default=_now)
    finished_at: Mapped[str] = mapped_column(String(40), default="")
    error: Mapped[str] = mapped_column(Text, default="")


class Detection(Base):
    """One object or face box on one sampled frame (a lead, not an identification)."""

    __tablename__ = "detections"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analytics_runs.id"), index=True)
    clip_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # objects | faces
    frame_index: Mapped[int] = mapped_column(Integer)
    nominal_time_s: Mapped[float] = mapped_column(Float)  # frame_index / stream fps
    class_name: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(60), default=TRIAGE_LABEL)


class MotionInterval(Base):
    __tablename__ = "motion_intervals"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analytics_runs.id"), index=True)
    clip_id: Mapped[int] = mapped_column(Integer, index=True)
    start_frame: Mapped[int] = mapped_column(Integer)
    end_frame: Mapped[int] = mapped_column(Integer)
    start_time_s: Mapped[float] = mapped_column(Float)  # nominal
    end_time_s: Mapped[float] = mapped_column(Float)  # nominal
    n_samples: Mapped[int] = mapped_column(Integer)
    score_peak: Mapped[float] = mapped_column(Float)
    score_mean: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(60), default=TRIAGE_LABEL)
