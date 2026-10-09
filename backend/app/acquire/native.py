"""Logical acquisition of standard exports (MP4, AVI, MKV, MPEG-TS, ASF, MOV, ... files).

The file is acquired with the resumable copier (hashed, read-only copy, custody), then the STORED
COPY is described by ffprobe: container, streams, codecs, durations. Nothing here identifies a
vendor: container metadata tags are stored as found and labelled as such. A file ffprobe cannot
parse stays acquired (it is evidence) and is recorded with probe_status 'unrecognised'.
"""

import json
import subprocess

from sqlalchemy.orm import Session

from app import custody
from app.acquire import resumable
from app.acquire.models import AcquisitionSession, NativeExport
from app.carving.export import ffmpeg_version, tool
from app.clock import utc_now_iso
from app.models import Evidence

PROBE_TIMEOUT = 120
STREAM_KEYS = (
    "index",
    "codec_type",
    "codec_name",
    "codec_long_name",
    "profile",
    "width",
    "height",
    "pix_fmt",
    "r_frame_rate",
    "avg_frame_rate",
    "sample_rate",
    "channels",
    "duration",
    "bit_rate",
    "nb_frames",
    "codec_tag_string",
)
# FFmpeg's demuxer probe score (0-100): containers identified by their structure score 100; raw
# elementary streams (h264/hevc) 51. 50 (AVPROBE_SCORE_EXTENSION) means the file name extension
# alone decided; the stored copy is named <id>.img, which FFmpeg maps to the image2/GEM raster
# demuxer, so random bytes "probe" as a video at score 50. Only scores above 50 count.
MIN_PROBE_SCORE = 51
TAG_NOTE = "container metadata as stored in the file; not a vendor identification"


def _num(v, cast):
    try:
        return cast(v) if v not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def probe(path: str) -> dict:
    """ffprobe the file. Returns a dict with status recognised|unrecognised (never raises except
    FfmpegMissing when ffprobe is absent)."""
    cmd = [
        tool("ffprobe"),
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        path,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"status": "unrecognised", "error": "ffprobe timed out"}
    try:
        info = json.loads(out.stdout or "{}")
    except ValueError:
        info = {}
    fmt, streams = info.get("format") or {}, info.get("streams") or []
    if out.returncode != 0 or not fmt or not streams:
        err = "; ".join(ln for ln in out.stderr.splitlines() if ln.strip())[:500]
        return {"status": "unrecognised", "error": err or "ffprobe found no streams"}
    score = _num(fmt.get("probe_score"), int)
    name = fmt.get("format_name", "")
    if not any(s.get("codec_type") in ("video", "audio") for s in streams):
        # ffprobe falls back to e.g. the 'tty' text demuxer for arbitrary bytes
        return {
            "status": "unrecognised",
            "error": f"no audio/video stream (ffprobe format '{name}')",
            "probe_score": score,
        }
    if score is not None and score < MIN_PROBE_SCORE:
        return {
            "status": "unrecognised",
            "error": f"ffprobe guessed '{name}' with probe score {score} < {MIN_PROBE_SCORE}",
            "probe_score": score,
        }
    return {
        "status": "recognised",
        "probe_score": score,
        "format_name": fmt.get("format_name", ""),
        "format_long_name": fmt.get("format_long_name", ""),
        "duration_s": _num(fmt.get("duration"), float),
        "bit_rate": _num(fmt.get("bit_rate"), int),
        "nb_streams": int(fmt.get("nb_streams") or len(streams)),
        "streams": [{k: s[k] for k in STREAM_KEYS if k in s} for s in streams],
        "tags": fmt.get("tags") or {},
        "error": "",
    }


def ingest(
    db: Session,
    case_id: int,
    source_path: str,
    label: str,
    write_blocker: str,
    examiner: str,
    chunk_size: int = resumable.DEFAULT_CHUNK,
) -> tuple[AcquisitionSession, NativeExport]:
    tool("ffprobe")  # fail early (FfmpegMissing -> 503) before anything is acquired
    sess = resumable.start(
        db,
        case_id,
        source_path,
        label,
        write_blocker,
        examiner,
        mode="native_export",
        chunk_size=chunk_size,
    )
    ev = db.get(Evidence, sess.evidence_id)
    return sess, probe_and_record(db, ev, examiner)


def probe_and_record(db: Session, ev: Evidence, examiner: str) -> NativeExport:
    p = probe(ev.image_path)
    row = NativeExport(
        case_id=ev.case_id,
        evidence_id=ev.id,
        probe_status=p["status"],
        format_name=p.get("format_name", ""),
        format_long_name=p.get("format_long_name", ""),
        duration_s=p.get("duration_s"),
        bit_rate=p.get("bit_rate"),
        nb_streams=p.get("nb_streams", 0),
        probe_score=p.get("probe_score"),
        streams_json=json.dumps(p.get("streams", [])),
        tags_json=json.dumps(p.get("tags", {})),
        probe_error=p.get("error", ""),
        ffprobe_version=ffmpeg_version(),
        probed_at=utc_now_iso(),
    )
    db.add(row)
    db.commit()
    custody.append_entry(
        db,
        ev.case_id,
        "native_export_probed",
        examiner,
        {
            "evidence_id": ev.id,
            "sha256": ev.sha256,
            "probe_status": row.probe_status,
            "format_name": row.format_name,
            "duration_s": row.duration_s,
            "nb_streams": row.nb_streams,
            "probe_score": row.probe_score,
            "codecs": [s.get("codec_name") for s in p.get("streams", [])],
            "probe_error": row.probe_error,
            "ffprobe_version": row.ffprobe_version,
            "vendor_claim": "none (standard export ingest)",
        },
        ev.id,
    )
    return row


def native_out(row: NativeExport) -> dict:
    return {
        "available": True,
        "kind": row.kind,
        "evidence_id": row.evidence_id,
        "probe_status": row.probe_status,
        "container": {
            "format_name": row.format_name,
            "format_long_name": row.format_long_name,
            "duration_s": row.duration_s,
            "bit_rate": row.bit_rate,
            "nb_streams": row.nb_streams,
            "probe_score": row.probe_score,
        },
        "streams": json.loads(row.streams_json),
        "tags": json.loads(row.tags_json),
        "tags_note": TAG_NOTE,
        "probe_error": row.probe_error,
        "ffprobe_version": row.ffprobe_version,
        "probed_at": row.probed_at,
        "vendor_claim": None,
        "note": "Standard-export ingest: the file was hashed and described by ffprobe. "
        "No vendor, device or proprietary-format claim is made.",
    }
