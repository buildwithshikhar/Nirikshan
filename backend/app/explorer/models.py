from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import _now


class RawReadAudit(Base):
    """One bounded raw-byte read (hex view). Audited here; deliberately NOT custody-logged per
    read (a custody entry per 4 KiB page would flood the chain without adding integrity value)."""

    __tablename__ = "raw_read_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp_utc: Mapped[str] = mapped_column(String(40), default=_now)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), index=True)
    examiner: Mapped[str] = mapped_column(String(200))
    offset: Mapped[int] = mapped_column(BigInteger)
    length: Mapped[int] = mapped_column(Integer)
    bytes_sha256: Mapped[str] = mapped_column(String(64))
