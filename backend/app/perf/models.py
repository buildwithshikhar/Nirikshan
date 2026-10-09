"""Manual baseline times entered by an examiner (the only input of the "time saved" metric)."""

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import _now

TASKS = ("analyze", "analytics")


class ManualBaseline(Base):
    """History is kept; the newest row per (case, task) is the one used."""

    __tablename__ = "perf_baselines"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    task: Mapped[str] = mapped_column(String(20))
    manual_seconds: Mapped[float] = mapped_column(Float)
    basis: Mapped[str] = mapped_column(String(20), default="estimate")  # measured | estimate
    note: Mapped[str] = mapped_column(Text, default="")
    entered_by: Mapped[str] = mapped_column(String(200))
    entered_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entered_at: Mapped[str] = mapped_column(String(40), default=_now)
    custody_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
