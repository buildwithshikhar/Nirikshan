"""Validation re-run records. The lead imports this module in app.main and bumps SCHEMA_VERSION."""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import _now


class ValidationRerun(Base):
    __tablename__ = "validation_reruns"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    # queued | running | completed | failed | timeout | interrupted
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    command_json: Mapped[str] = mapped_column(Text, default="[]")
    out_dir: Mapped[str] = mapped_column(Text, default="")
    baseline_path: Mapped[str] = mapped_column(Text, default="")
    baseline_sha256_before: Mapped[str] = mapped_column(String(64), default="")
    baseline_sha256_after: Mapped[str] = mapped_column(String(64), default="")
    baseline_digest: Mapped[str] = mapped_column(String(64), default="")
    rerun_digest: Mapped[str] = mapped_column(String(64), default="")
    comparison_json: Mapped[str] = mapped_column(Text, default="null")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_tail: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    examiner: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    started_at: Mapped[str] = mapped_column(String(40), default="")
    finished_at: Mapped[str] = mapped_column(String(40), default="")
