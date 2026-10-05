from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CaseIn(BaseModel):
    case_number: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    description: str = ""


class CaseOut(CaseIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    examiner: str
    created_at: str


class AcquireIn(BaseModel):
    source_path: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=300)
    write_blocker: Literal["yes", "no", "unknown"]


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    label: str
    source_path: str
    source_type: str
    write_blocker: str
    status: str
    size_bytes: int
    md5: str
    sha256: str
    examiner: str
    acquired_at: str
    last_verified_at: str
    last_verify_ok: int


class CustodyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seq: int
    timestamp_utc: str
    action: str
    evidence_id: int | None
    examiner: str
    tool_version: str
    ntp_status: str
    details_json: str
    prev_hash: str
    entry_hash: str
    signature: str
    key_id: str


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    timestamp_utc: str
    examiner: str
    method: str
    path: str
    status_code: int
    case_id: int | None


class AnalyzeIn(BaseModel):
    max_pad: int = Field(default=64, ge=0, le=4096)
    join_gap: int = Field(default=0, ge=0, le=16 * 1024 * 1024)
    h264_continuity: bool = True
    validate_params: bool = True
    parser_options: dict[str, dict] = Field(default_factory=dict)  # vendor -> parser options


class ClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    evidence_id: int
    kind: str
    seq: int
    codec: str
    start_offset: int
    end_offset: int
    size_bytes: int
    extents_json: str
    nal_count: int
    irap_count: int
    vcl_count: int
    reassembled: int
    reason: str
    notes_json: str
    bitstream_sha256: str
    mp4_sha256: str
    decode_status: str
    decode_errors_json: str
    error: str
    width: int | None
    height: int | None
    fps: str
    packets: int | None
    duration_s: float | None
    has_video: bool = False
    engine: str = "generic"
    channel: int | None = None
    parsed_json: str = "{}"
