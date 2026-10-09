"""Evidence package records. Imported by app.main so create_all sees the table."""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import _now


class Package(Base):
    __tablename__ = "evidence_packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(200))
    file_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))  # of the file as stored (zip or encrypted)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    signature_hex: Mapped[str] = mapped_column(String(128))
    key_id: Mapped[str] = mapped_column(String(16))
    file_count: Mapped[int] = mapped_column(Integer)
    include_clips: Mapped[bool] = mapped_column(Boolean, default=True)
    head_hash_built_from: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    created_by: Mapped[str] = mapped_column(String(200))
    custody_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excluded_json: Mapped[str] = mapped_column(Text, default="[]")
