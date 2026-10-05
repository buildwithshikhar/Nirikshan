"""Identify + carve one evidence item and persist clips with hashes and custody entries.

The image is read only through evidence.open_verified (hash re-verified first; any mismatch
aborts the run). One verification covers the whole run: identification, scanning and clip export.
"""

import json
import time
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.orm import Session

from app import __version__, custody
from app.carving import nal
from app.carving.carve import CarveParams, Carver
from app.carving.carve import Clip as CarvedClip
from app.carving.export import export_clip, ffmpeg_version, tool
from app.clock import utc_now_iso
from app.config import data_dir
from app.evidence import open_verified
from app.models import CarveRun, Clip, Evidence
from app.vendors import default_registry


def clips_dir(case_id: int, evidence_id: int, run_id: int) -> Path:
    return data_dir() / "cases" / str(case_id) / "clips" / str(evidence_id) / f"run{run_id}"


def _match_dict(m) -> dict:
    d = asdict(m)
    d["evidence"] = [asdict(h) for h in m.evidence]
    return d


def analyze(db: Session, ev: Evidence, examiner: str, params: CarveParams) -> CarveRun:
    tool("ffmpeg")  # fail early (FfmpegMissing) before creating a run
    tool("ffprobe")
    ffv = ffmpeg_version()
    run = CarveRun(
        case_id=ev.case_id,
        evidence_id=ev.id,
        status="running",
        examiner=examiner,
        params_json=json.dumps(asdict(params), sort_keys=True),
        tool_version=__version__,
        ffmpeg_version=ffv,
    )
    db.add(run)
    db.commit()
    counts = {"clips": 0, "orphans": 0, "ok": 0, "decode_errors": 0, "export_failed": 0}
    try:
        with open_verified(db, ev, examiner) as f:

            def read_at(off: int, n: int) -> bytes:
                f.seek(off)
                return f.read(n)

            t0 = time.perf_counter()
            matches = default_registry().identify(f, ev.size_bytes)
            run.ident_seconds = time.perf_counter() - t0
            run.vendor_json = json.dumps([_match_dict(m) for m in matches])

            carver = Carver(read_at, params)
            out = clips_dir(ev.case_id, ev.id, run.id)
            t0 = time.perf_counter()
            clip_seq = orphan_seq = 0
            for item in carver.run(nal.scan(f, ev.size_bytes)):
                if isinstance(item, CarvedClip):
                    clip_seq += 1
                    _store_clip(db, run, ev, f, item, clip_seq, out, ffv, examiner, counts)
                else:
                    orphan_seq += 1
                    counts["orphans"] += 1
                    db.add(
                        Clip(
                            run_id=run.id,
                            evidence_id=ev.id,
                            case_id=ev.case_id,
                            kind="orphan",
                            seq=orphan_seq,
                            codec=item.codec,
                            start_offset=item.start,
                            end_offset=item.end,
                            size_bytes=item.end - item.start,
                            extents_json=json.dumps([[item.start, item.end]]),
                            nal_count=item.nal_count,
                            reason=item.reason,
                        )
                    )
                    db.commit()
            run.carve_seconds = time.perf_counter() - t0
            run.stats_json = json.dumps({**carver.stats, **counts, "bytes_scanned": ev.size_bytes})
    except Exception as exc:  # recorded in the run and custody log, then re-raised
        run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"
        run.finished_at = utc_now_iso()
        db.commit()
        custody.append_entry(
            db, ev.case_id, "carve_failed", examiner, {"run_id": run.id, "error": run.error}, ev.id
        )
        raise
    run.status, run.finished_at = "completed", utc_now_iso()
    db.commit()
    mb = ev.size_bytes / (1024 * 1024)
    custody.append_entry(
        db,
        ev.case_id,
        "carve_completed",
        examiner,
        {
            "run_id": run.id,
            "params": json.loads(run.params_json),
            "vendor_matches": [
                {"vendor": m.vendor, "tier": m.tier, "confidence": m.confidence} for m in matches
            ],
            "counts": counts,
            "bytes_scanned": ev.size_bytes,
            "identify_mb_per_s": round(mb / run.ident_seconds, 1) if run.ident_seconds else None,
            "carve_mb_per_s": round(mb / run.carve_seconds, 1) if run.carve_seconds else None,
            "ffmpeg_version": ffv,
        },
        ev.id,
    )
    return run


def _store_clip(db, run, ev, f, c: CarvedClip, seq, out: Path, ffv, examiner, counts) -> None:
    res = export_clip(f, c.extents, c.codec, out, f"clip_{seq:04d}")
    counts["clips"] += 1
    counts[res.decode_status] += 1
    if res.mp4_path:
        Path(res.mp4_path).chmod(0o444)
    row = Clip(
        run_id=run.id,
        evidence_id=ev.id,
        case_id=ev.case_id,
        kind="clip",
        seq=seq,
        codec=c.codec,
        start_offset=c.start,
        end_offset=c.end,
        size_bytes=c.size,
        extents_json=json.dumps(c.extents),
        nal_count=c.nal_count,
        irap_count=c.irap_count,
        vcl_count=c.vcl_count,
        reassembled=int(c.reassembled),
        reason=c.end_reason,
        notes_json=json.dumps(c.notes),
        bitstream_sha256=res.bitstream_sha256,
        mp4_path=res.mp4_path,
        mp4_sha256=res.mp4_sha256,
        decode_status=res.decode_status,
        decode_errors_json=json.dumps(res.decode_errors),
        error=res.error,
        width=res.width,
        height=res.height,
        fps=res.fps,
        packets=res.packets,
        duration_s=res.duration_s,
    )
    db.add(row)
    db.commit()
    custody.append_entry(
        db,
        ev.case_id,
        "clip_carved",
        examiner,
        {
            "run_id": run.id,
            "clip_id": row.id,
            "codec": c.codec,
            "extents": c.extents,
            "bytes": c.size,
            "reassembled": c.reassembled,
            "bitstream_sha256": res.bitstream_sha256,
            "mp4_sha256": res.mp4_sha256,
            "decode_status": res.decode_status,
            "ffmpeg_version": ffv,
        },
        ev.id,
    )
