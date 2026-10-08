"""DB row for generated reports. The lead imports this module in app.main (so create_all sees
the table) and bumps SCHEMA_VERSION."""

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import _now


class Report(Base):
    """One generated PDF. The file is stored read-only; `sha256` is also in the custody log
    (action report_generated) and is re-checked on every download."""

    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="case_report")
    file_name: Mapped[str] = mapped_column(String(200), default="")
    file_path: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    head_hash_before: Mapped[str] = mapped_column(String(64), default="")
    chain_ok: Mapped[int] = mapped_column(Integer, default=0)
    generated_at: Mapped[str] = mapped_column(String(40), default="")
    examiner: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    custody_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
