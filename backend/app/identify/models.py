from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import _now


class DeviceIdentification(Base):
    """Stored device-intelligence result for one evidence item (recomputed on request)."""

    __tablename__ = "device_identifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), index=True)
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    tool_version: Mapped[str] = mapped_column(String(50))
    registry_key: Mapped[str] = mapped_column(String(200))  # parser vendors + versions
    examiner: Mapped[str] = mapped_column(String(200))
    result_json: Mapped[str] = mapped_column(Text)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
