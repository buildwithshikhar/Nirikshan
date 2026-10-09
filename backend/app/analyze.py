"""Identify + carve one evidence item and persist clips with hashes and custody entries.

The image is read only through evidence.open_verified (hash re-verified first; any mismatch
aborts the run). One verification covers the whole run: identification, the generic carve, any
vendor parser matched by identification, the cross-check between them, and clip export.
Generic carving always runs; vendor parser output is kept alongside it (`engine` column), never
substituted silently, and every disagreement is listed.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__, custody
from app.carving import nal
from app.carving.carve import CarveParams, Carver
from app.carving.carve import Clip as CarvedClip
from app.carving.export import export_clip, ffmpeg_version, tool
from app.carving.ranges import carve_ranges, merge_spans, uncovered
from app.clock import utc_now_iso
from app.config import data_dir
from app.evidence import open_verified
from app.models import CarveRun, Clip, Evidence
from app.vendors import default_registry
from app.vendors.parse import crosscheck


class AnalysisCancelled(Exception):
    """Raised at a checkpoint when should_cancel() returns True; handled inside analyze()."""


ProgressFn = Callable[[str, float], None]


@dataclass
class _Hooks:
    """Optional progress / cancel callbacks. With both None (the synchronous API) every call is
    a no-op, so the pipeline behaves exactly as before."""

    progress: ProgressFn | None = None
    should_cancel: Callable[[], bool] | None = None

    def report(self, stage: str, fraction: float) -> None:
        if self.progress is not None:
            self.progress(stage, max(0.0, min(1.0, fraction)))

    def check(self) -> None:
        if self.should_cancel is not None and self.should_cancel():
            raise AnalysisCancelled


class LiveSource:
    """In-process identification/parsing/carving over the open image (the default). The
    isolated alternative with the same interface is app.workers.plan.PlannedSource."""

    timings: dict = {}

    def __init__(self, f, size: int, registry, params: CarveParams, parser_options: dict | None):
        self.f, self.size, self.registry = f, size, registry
        self.params, self.parser_options = params, parser_options or {}

    def identify(self) -> list:
        return self.registry.identify(self.f, self.size)

    def parse(self, _index: int, m):
        parser = self.registry.parser_for(m.vendor)
        opts = self.parser_options.get(m.vendor)
        return parser.parse(self.f, self.size, opts) if parser else None

    def generic(self, ranges):
        return carve_ranges(self.f, ranges, self.params)

    def full_generic(self) -> list:
        def read_at(off: int, n: int) -> bytes:
            self.f.seek(off)
            return self.f.read(n)

        return _dry_generic(self.f, self.size, read_at, self.params)


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
    generic_scope: str = "uncovered",
    *,
    progress: ProgressFn | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_run: Callable[[CarveRun], None] | None = None,
    planner: Callable[[_Hooks], object] | None = None,
) -> CarveRun:
    """Run the pipeline. `progress(stage, fraction)` and `should_cancel()` are optional; they are
    checked between stages, clips and exports (never inside one ffmpeg call or the initial image
    hash). A cancelled run is returned with status "cancelled" (see _finish_cancelled).
    `planner(hooks)`, when given, returns a source with LiveSource's interface computed elsewhere
    (an isolated worker: app.workers.pipeline); everything is still stored by this function."""
    hooks = _Hooks(progress, should_cancel)
    tool("ffmpeg")  # fail early (FfmpegMissing) before creating a run
    tool("ffprobe")
    ffv = ffmpeg_version()
    run = CarveRun(
        case_id=ev.case_id,
        evidence_id=ev.id,
        status="running",
        examiner=examiner,
        params_json=json.dumps(
            {
                **asdict(params),
                "parser_options": parser_options or {},
                "generic_scope": generic_scope,
            },
            sort_keys=True,
        ),
        tool_version=__version__,
        ffmpeg_version=ffv,
    )
    db.add(run)
    db.commit()
    if on_run is not None:
        on_run(run)
    out = clips_dir(ev.case_id, ev.id, run.id)
    counts = {"clips": 0, "orphans": 0, "ok": 0, "decode_errors": 0, "export_failed": 0}
    matches: list = []
    try:
        hooks.report("Verifying image hash", 0.02)
        hooks.check()
        with open_verified(db, ev, examiner) as f:
            hooks.report("Identifying vendor", 0.10)
            hooks.check()

            registry = default_registry()
            if planner is None:
                src = LiveSource(f, ev.size_bytes, registry, params, parser_options)
            else:
                src = planner(hooks)  # runs before anything of this run is stored
                hooks.check()
            t0 = time.perf_counter()
            matches = src.identify()
            run.ident_seconds = time.perf_counter() - t0 + src.timings.get("identify", 0.0)
            run.vendor_json = json.dumps([_match_dict(m) for m in matches])

            # 1) vendor parsers first (their clips are exported and stored)
            t0 = time.perf_counter()
            parse_results = []
            hooks.report("Running vendor parsers", 0.15)
            for i, m in enumerate(matches):
                hooks.check()
                res = src.parse(i, m)
                if res is not None:
                    parse_results.append(res)
                    _store_parsed(db, run, ev, f, res, out, ffv, examiner, counts, hooks)
            parse_seconds = time.perf_counter() - t0 + src.timings.get("parse", 0.0)
            # 2) generic carving over the bytes no parser clip spans (never twice, never lost)
            spans = [(c.start, c.end) for r in parse_results for c in r.clips]
            covered = merge_spans(spans)
            ranges = (
                uncovered(covered, ev.size_bytes)
                if generic_scope == "uncovered"
                else [(0, ev.size_bytes)]
            )
            t0 = time.perf_counter()
            generic: list[CarvedClip] = []
            orphan_seq = 0
            for item in src.generic(ranges):
                hooks.check()
                hooks.report(
                    "Generic carving and exporting clips",
                    0.50 + 0.35 * min(1.0, item.end / max(1, ev.size_bytes)),
                )
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
                        hooks=hooks,
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
            run.carve_seconds = time.perf_counter() - t0 + src.timings.get("carve", 0.0)
            # 3) cross-check parser clips against an independent generic pass over the whole
            # image (dry run: nothing exported or stored besides the disagreement list)
            parse_out = []
            crosscheck_seconds = 0.0
            hooks.check()
            if parse_results:
                hooks.report("Cross-checking parser output against generic carving", 0.90)
                t1 = time.perf_counter()
                full = src.full_generic()
                crosscheck_seconds = (
                    time.perf_counter() - t1 + src.timings.get("crosscheck_pass", 0.0)
                )
                for res in parse_results:
                    res.crosscheck = crosscheck(res.clips, full)
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
            hooks.report("Finalizing run", 0.98)
            hooks.check()
            covered_bytes = sum(e - s for s, e in covered)
            pipeline = {
                "mode": "parser_first",
                "generic_scope": generic_scope,
                "parser_covered_bytes": covered_bytes,
                "generic_ranges": len(ranges),
                "parse_seconds": round(parse_seconds, 3),
                "crosscheck_seconds": round(crosscheck_seconds, 3),
                "isolated_worker": planner is not None,
            }
            if planner is not None:
                pipeline["worker_timings"] = src.timings
            carver_stats: dict = {}
            run.parse_json = json.dumps(parse_out)
            run.stats_json = json.dumps(
                {**carver_stats, **counts, **pipeline, "bytes_scanned": ev.size_bytes}
            )
    except AnalysisCancelled:
        return _finish_cancelled(db, run, ev, examiner, counts, out, hooks)
    except Exception as exc:  # recorded in the run and custody log, then re-raised
        run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"
        run.finished_at = utc_now_iso()
        db.commit()
        sweep_unrecorded(db, run, out)
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


def sweep_unrecorded(db: Session, run: CarveRun, out: Path) -> list[str]:
    """Delete every file in the run's clip directory that no Clip row of this run records (a
    half-written bitstream/MP4); recorded MP4s are kept. Never raises. Returns removed names."""
    removed: list[str] = []
    try:
        if not out.is_dir():
            return removed
        keep = {
            str(Path(p).resolve())
            for p in db.scalars(
                select(Clip.mp4_path).where(Clip.run_id == run.id, Clip.mp4_path != "")
            )
        }
        for p in sorted(out.iterdir()):
            if p.is_file() and str(p.resolve()) not in keep:
                p.chmod(0o600)
                p.unlink(missing_ok=True)
                removed.append(p.name)
        if not any(out.iterdir()):
            out.rmdir()
    except OSError:
        pass
    return removed


def _finish_cancelled(db, run, ev, examiner, counts, out, hooks) -> CarveRun:
    """Cancelled between checkpoints: nothing half-written stays on disk, clips that were fully
    recorded stay recorded (and are listed in the custody entry), the run is marked cancelled."""
    removed = sweep_unrecorded(db, run, out)
    recorded = db.scalars(
        select(Clip).where(Clip.run_id == run.id, Clip.kind == "clip").order_by(Clip.id)
    ).all()
    orphans = db.scalar(
        select(func.count()).select_from(Clip).where(Clip.run_id == run.id, Clip.kind == "orphan")
    )
    run.status, run.finished_at = "cancelled", utc_now_iso()
    run.error = "cancelled by examiner request; results of this run are partial"
    run.stats_json = json.dumps({**counts, "partial": True, "bytes_scanned": ev.size_bytes})
    db.commit()
    custody.append_entry(
        db,
        ev.case_id,
        "analysis_cancelled",
        examiner,
        {
            "run_id": run.id,
            "partial": True,
            "completed_clip_ids": [c.id for c in recorded],
            "completed_clips": len(recorded),
            "orphans_recorded": orphans,
            "unrecorded_files_removed": removed,
            "note": "clips listed were fully exported and recorded before the cancel; "
            "everything else of this run was discarded",
        },
        ev.id,
    )
    return run


def _dry_generic(f, size, read_at, params) -> list[CarvedClip]:
    carver = Carver(read_at, params)
    return [c for c in carver.run(nal.scan(f, size)) if isinstance(c, CarvedClip)]


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


def _store_parsed(
    db, run, ev, f, res, out: Path, ffv, examiner, counts, hooks: _Hooks | None = None
) -> None:
    hooks = hooks or _Hooks()
    engine = res.parser
    for seq, c in enumerate(res.clips, start=1):
        hooks.report("Exporting parser clips", 0.15 + 0.35 * (seq - 1) / max(1, len(res.clips)))
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
            hooks=hooks,
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
    hooks: _Hooks | None = None,
) -> None:
    if hooks is not None:
        hooks.check()  # checkpoint before any file is written for this clip
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
