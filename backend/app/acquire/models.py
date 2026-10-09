"""Tables for resumable acquisition (checkpoint + bad-sector map) and native-export ingest."""

from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import _now


class AcquisitionSession(Base):
    """Checkpoint of one resumable acquisition.

    hashlib state cannot be serialised, so the checkpoint is a list of per-chunk SHA-256 digests
    of the bytes written (zero-filled where the source could not be read) plus `bytes_done`.
    Whole-file MD5/SHA-256 are computed on completion by re-reading the finished copy.
    """

    __tablename__ = "acquisition_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="image")  # image | native_export
    source_path: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20))  # file | block_device
    source_size: Mapped[int] = mapped_column(BigInteger)
    chunk_size: Mapped[int] = mapped_column(Integer)
    sector_size: Mapped[int] = mapped_column(Integer, default=512)
    retries: Mapped[int] = mapped_column(Integer, default=1)
    bytes_done: Mapped[int] = mapped_column(BigInteger, default=0)
    chunk_sha256_json: Mapped[str] = mapped_column(Text, default="[]")
    bad_ranges_json: Mapped[str] = mapped_column(Text, default="[]")  # [[start, end, error], ...]
    partial_path: Mapped[str] = mapped_column(Text, default="")
    # in_progress | interrupted | completed | failed
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    resumes: Mapped[int] = mapped_column(Integer, default=0)
    examiner: Mapped[str] = mapped_column(String(200))
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    updated_at: Mapped[str] = mapped_column(String(40), default=_now)


class NativeExport(Base):
    """ffprobe description of an acquired standard export (MP4/AVI/MKV/TS/...). No vendor claim."""

    __tablename__ = "native_exports"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="native_export")
    probe_status: Mapped[str] = mapped_column(String(20))  # recognised | unrecognised
    format_name: Mapped[str] = mapped_column(String(200), default="")
    format_long_name: Mapped[str] = mapped_column(String(300), default="")
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    bit_rate: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    nb_streams: Mapped[int] = mapped_column(Integer, default=0)
    probe_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    streams_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="{}")
    probe_error: Mapped[str] = mapped_column(Text, default="")
    ffprobe_version: Mapped[str] = mapped_column(String(200), default="")
    probed_at: Mapped[str] = mapped_column(String(40), default=_now)
