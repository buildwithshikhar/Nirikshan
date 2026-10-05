"""Identify + carve one evidence item and persist clips with hashes and custody entries.

The image is read only through evidence.open_verified (hash re-verified first; any mismatch
aborts the run). One verification covers the whole run: identification, the generic carve, any
vendor parser matched by identification, the cross-check between them, and clip export.
Generic carving always runs; vendor parser output is kept alongside it (`engine` column), never
substituted silently, and every disagreement is listed.
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
from app.vendors.parse import crosscheck


def clips_dir(case_id: int, evidence_id: int, run_id: int) -> Path:
    return data_dir() / "cases" / str(case_id) / "clips" / str(evidence_id) / f"run{run_id}"


def _match_dict(m) -> dict:
    d = asdict(m)
    d["evidence"] = [asdict(h) for h in m.evidence]
    return d


def analyze(
    db: Session,
    ev: Evidence,
    examiner: str,
    params: CarveParams,
    parser_options: dict | None = None,
) -> CarveRun:
    tool("ffmpeg")  # fail early (FfmpegMissing) before creating a run
    tool("ffprobe")
    ffv = ffmpeg_version()
    run = CarveRun(
        case_id=ev.case_id,
        evidence_id=ev.id,
        status="running",
        examiner=examiner,
        params_json=json.dumps(
            {**asdict(params), "parser_options": parser_options or {}}, sort_keys=True
        ),
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

            registry = default_registry()
            t0 = time.perf_counter()
            matches = registry.identify(f, ev.size_bytes)
            run.ident_seconds = time.perf_counter() - t0
            run.vendor_json = json.dumps([_match_dict(m) for m in matches])

            carver = Carver(read_at, params)
            out = clips_dir(ev.case_id, ev.id, run.id)
            t0 = time.perf_counter()
            generic: list[CarvedClip] = []
            orphan_seq = 0
            for item in carver.run(nal.scan(f, ev.size_bytes)):
                if isinstance(item, CarvedClip):
                    generic.append(item)
                    _store_clip(
                        db,
                        run,
                        ev,
                        f,
                        "generic",
                        item.codec,
                        item.extents,
                        len(generic),
                        out,
                        ffv,
                        examiner,
                        counts,
                        nal_count=item.nal_count,
                        irap=item.irap_count,
                        vcl=item.vcl_count,
                        reassembled=item.reassembled,
                        reason=item.end_reason,
                        notes=item.notes,
                    )
                else:
                    orphan_seq += 1
                    _store_orphan(
                        db,
                        run,
                        ev,
                        "generic",
                        item.codec,
                        item.start,
                        item.end,
                        orphan_seq,
                        item.nal_count,
                        item.reason,
                        None,
                        counts,
                    )
            run.carve_seconds = time.perf_counter() - t0

            parse_out = []
            for m in matches:
                parser = registry.parser_for(m.vendor)
                res = (
                    parser.parse(f, ev.size_bytes, (parser_options or {}).get(m.vendor))
                    if parser
                    else None
                )
                if res is None:
                    continue
                res.crosscheck = crosscheck(res.clips, generic)
                _store_parsed(db, run, ev, f, res, out, ffv, examiner, counts)
                parse_out.append(res.to_dict())
                custody.append_entry(
                    db,
                    ev.case_id,
                    "parser_completed",
                    examiner,
                    {
                        "run_id": run.id,
                        "parser": res.parser,
                        "tier": res.tier,
                        "status": res.status,
                        "options": res.options,
                        "clips": len(res.clips),
                        "orphans": len(res.orphans),
                        "inconsistencies": res.inconsistencies[:10],
                        "crosscheck_disagreements": len(res.crosscheck["disagreements"]),
                    },
                    ev.id,
                )
            run.parse_json = json.dumps(parse_out)
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


def _store_orphan(db, run, ev, engine, codec, start, end, seq, nals, reason, channel, counts):
    counts["orphans"] += 1
    db.add(
        Clip(
            run_id=run.id,
            evidence_id=ev.id,
            case_id=ev.case_id,
            kind="orphan",
            seq=seq,
            codec=codec,
            start_offset=start,
            end_offset=end,
            size_bytes=end - start,
            extents_json=json.dumps([[start, end]]),
            nal_count=nals,
            reason=reason,
            engine=engine,
            channel=channel,
        )
    )
    db.commit()


def _store_parsed(db, run, ev, f, res, out: Path, ffv, examiner, counts) -> None:
    engine = res.parser
    for seq, c in enumerate(res.clips, start=1):
        info = {
            "fields": [asdict(x) for x in c.fields],
            "timestamps": [asdict(t) for t in c.timestamps if t is not None],
            "frame_count": c.frames,
            "key_frames": c.key_frames,
            "width": c.width,
            "height": c.height,
        }
        _store_clip(
            db,
            run,
            ev,
            f,
            engine,
            c.codec,
            c.extents,
            seq,
            out,
            ffv,
            examiner,
            counts,
            nal_count=c.frames,
            irap=c.key_frames,
            vcl=c.frames,
            reassembled=False,
            reason=c.end_reason,
            notes=c.notes,
            channel=c.channel,
            parsed=info,
            exportable=c.exportable,
        )
    for seq, o in enumerate(res.orphans, start=1):
        _store_orphan(
            db,
            run,
            ev,
            engine,
            "unknown",
            o.start,
            o.end,
            seq,
            o.frames,
            o.reason,
            o.channel,
            counts,
        )


def _store_clip(
    db,
    run,
    ev,
    f,
    engine,
    codec,
    extents,
    seq,
    out: Path,
    ffv,
    examiner,
    counts,
    *,
    nal_count,
    irap,
    vcl,
    reassembled,
    reason,
    notes,
    channel=None,
    parsed=None,
    exportable=True,
) -> None:
    name = f"{engine.lower()}_{seq:04d}"
    counts["clips"] += 1
    if exportable:
        res = export_clip(f, extents, codec, out, name)
        counts[res.decode_status] += 1
        if res.mp4_path:
            Path(res.mp4_path).chmod(0o444)
        fields = dict(
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
    else:
        fields = dict(decode_status="not_exported", error=f"codec {codec} is not exported")
    size = sum(e - s for s, e in extents)
    row = Clip(
        run_id=run.id,
        evidence_id=ev.id,
        case_id=ev.case_id,
        kind="clip",
        seq=seq,
        codec=codec,
        start_offset=extents[0][0],
        end_offset=extents[-1][1],
        size_bytes=size,
        extents_json=json.dumps(extents),
        nal_count=nal_count,
        irap_count=irap,
        vcl_count=vcl,
        reassembled=int(reassembled),
        reason=reason,
        notes_json=json.dumps(notes),
        engine=engine,
        channel=channel,
        parsed_json=json.dumps(parsed or {}),
        **fields,
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
            "engine": engine,
            "codec": codec,
            "channel": channel,
            "extents": extents if len(extents) <= 50 else extents[:50] + [["...", len(extents)]],
            "extent_count": len(extents),
            "bytes": size,
            "reassembled": reassembled,
            "bitstream_sha256": row.bitstream_sha256,
            "mp4_sha256": row.mp4_sha256,
            "decode_status": row.decode_status,
            "ffmpeg_version": ffv,
        },
        ev.id,
    )
