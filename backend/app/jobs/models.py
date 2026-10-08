from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

STATUSES = ("queued", "running", "cancelling", "cancelled", "failed", "completed")
ACTIVE = ("queued", "running", "cancelling")
TERMINAL = ("cancelled", "failed", "completed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Job(Base):
    """One background job. `active_key` is the idempotency key while the job is queued, running
    or cancelling and NULL once it is terminal, so the UNIQUE constraint allows one active job
    per identical request and any number of finished ones."""

    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("active_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # analyze
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), index=True)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(12), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(200), default="Queued")
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    examiner: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    active_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    started_at: Mapped[str] = mapped_column(String(40), default="")
    finished_at: Mapped[str] = mapped_column(String(40), default="")
