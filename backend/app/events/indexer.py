"""Build the event index of a case from STORED analytics rows (idempotent, no re-analysis).

Absolute time comes only from the case timeline (app.timeline.routes.build_case_timeline), so the
index obeys the same rules: no default timezone, unplaceable clips get no absolute time and keep
the timeline's reason. For a placed clip, an event at nominal offset t has
    utc_lo = clip_start.lo + t,  utc_hi = clip_start.hi + t
i.e. the clip-start uncertainty bar shifted by the nominal in-clip offset (frame index / stream
fps, constant-rate assumption; clock drift inside one clip is not modelled).

`index_case` is safe to call repeatedly (e.g. by app.main after every analytics run): rows are
upserted by (source_kind, source_row_id), so event ids stay stable, and events whose source rows
disappeared are removed.
"""

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import TRIAGE_LABEL
from app.analytics.models import AnalyticsRun, Detection, MotionInterval
from app.clock import utc_now_iso
from app.events import fts
from app.events.models import IndexedEvent
from app.models import Clip
from app.timeline.routes import build_case_timeline
from app.timeline.timestamps import iso, parse_iso_utc

MOTION_MODEL = "frame-difference motion (no learned model)"
KIND_WORDS = {"motion": "motion", "objects": "object detection", "faces": "face detection"}


def _shift(s: str, seconds: float) -> str:
    dt: datetime = parse_iso_utc(s)
    return iso(dt + timedelta(seconds=seconds))  # type: ignore[return-value]


def placement_map(db: Session, case_id: int) -> tuple[dict[int, dict], dict[int, str]]:
    """clip_id -> placement info from the case timeline; evidence_id -> assumed timezone."""
    tl = build_case_timeline(db, case_id, 1.0)
    out: dict[int, dict] = {}
    for p in tl["placed"]:
        rec = p.get("start_record") or {}
        out[p["clip_id"]] = {
            "placement": "placed",
            "start": p["start"],
            "tz_status": p["tz_status"],
            "assumed_timezone": rec.get("assumed_timezone"),
            "reason": "",
        }
    for u in tl["unplaceable"]:
        out[u["clip_id"]] = {
            "placement": "unplaceable",
            "start": None,
            "tz_status": u["tz_status"],
            "assumed_timezone": (u.get("start_record") or {}).get("assumed_timezone"),
            "reason": u["reason"],
        }
    zones = {e["evidence_id"]: e.get("timezone") for e in tl["evidence"]}
    return out, zones


def _search_text(class_name: str, kind: str, channel, clip_id: int, ev_id: int, model: str):
    cam = f"camera {channel} channel {channel} cam{channel}" if channel is not None else ""
    return " ".join(
        x
        for x in (
            class_name.replace("_", " "),
            class_name,
            KIND_WORDS.get(kind, kind),
            cam,
            f"clip {clip_id}",
            f"evidence {ev_id}",
            model,
        )
        if x
    ).lower()


def index_case(db: Session, case_id: int) -> dict:
    """(Re)build the index for one case. Returns counts and the full-text backend used."""
    places, _zones = placement_map(db, case_id)
    runs = db.scalars(
        select(AnalyticsRun)
        .where(AnalyticsRun.case_id == case_id, AnalyticsRun.status == "completed")
        .order_by(AnalyticsRun.id)
    ).all()
    existing = {
        (e.source_kind, e.source_row_id): e
        for e in db.scalars(select(IndexedEvent).where(IndexedEvent.case_id == case_id))
    }
    seen: set[tuple[str, int]] = set()
    clips: dict[int, Clip | None] = {}
    now = utc_now_iso()
    counts = {"motion": 0, "objects": 0, "faces": 0, "placed": 0, "unplaceable": 0}
    for run in runs:
        clip = clips.setdefault(run.clip_id, db.get(Clip, run.clip_id))
        if clip is None:
            continue
        model = json.loads(run.model_json or "null") or {}
        model_name = model.get("name", MOTION_MODEL if run.kind == "motion" else "")
        model_sha = model.get("sha256", "")
        pl = places.get(clip.id) or {
            "placement": "unplaceable",
            "start": None,
            "tz_status": "unknown",
            "assumed_timezone": None,
            "reason": "clip is not on the case timeline",
        }
        if run.kind == "motion":
            src = db.scalars(select(MotionInterval).where(MotionInterval.run_id == run.id)).all()
            items = [
                (
                    "motion",
                    m.id,
                    "motion",
                    m.start_frame,
                    m.end_frame,
                    m.start_time_s,
                    m.end_time_s,
                    None,
                    m.score_peak,
                )
                for m in src
            ]
        else:
            src = db.scalars(select(Detection).where(Detection.run_id == run.id)).all()
            items = [
                (
                    "detection",
                    d.id,
                    d.class_name,
                    d.frame_index,
                    d.frame_index,
                    d.nominal_time_s,
                    d.nominal_time_s,
                    d.confidence,
                    None,
                )
                for d in src
            ]
        for sk, sid, cls, f0, f1, t0, t1, conf, peak in items:
            key = (sk, sid)
            seen.add(key)
            values = {
                "case_id": case_id,
                "evidence_id": clip.evidence_id,
                "clip_id": clip.id,
                "run_id": run.id,
                "source_kind": sk,
                "source_row_id": sid,
                "kind": run.kind,
                "class_name": cls,
                "channel": clip.channel,
                "frame_index": f0,
                "end_frame_index": f1,
                "nominal_time_s": t0,
                "nominal_end_s": t1,
                "confidence": conf,
                "motion_score_peak": peak,
                "placement": pl["placement"],
                "unplaceable_reason": pl["reason"],
                "tz_status": pl["tz_status"],
                "assumed_timezone": pl["assumed_timezone"],
                "utc_lo": _shift(pl["start"]["lo"], t0) if pl["start"] else None,
                "utc_hi": _shift(pl["start"]["hi"], t0) if pl["start"] else None,
                "utc_end_lo": _shift(pl["start"]["lo"], t1) if pl["start"] else None,
                "utc_end_hi": _shift(pl["start"]["hi"], t1) if pl["start"] else None,
                "model_name": model_name,
                "model_sha256": model_sha,
                "clip_bitstream_sha256": clip.bitstream_sha256,
                "clip_mp4_sha256": run.mp4_sha256 or clip.mp4_sha256,
                "clip_start_offset": clip.start_offset,
                "clip_end_offset": clip.end_offset,
                "clip_extents_json": clip.extents_json or "[]",
                "search_text": _search_text(
                    cls, run.kind, clip.channel, clip.id, clip.evidence_id, model_name
                ),
                "label": TRIAGE_LABEL,
                "indexed_at": now,
            }
            row = existing.get(key)
            if row is None:
                db.add(IndexedEvent(**values))
            else:
                for k, v in values.items():
                    setattr(row, k, v)
            counts[run.kind] += 1
            counts[pl["placement"]] += 1
    removed = 0
    for key, row in existing.items():
        if key not in seen:
            db.delete(row)
            removed += 1
    db.flush()
    rows = db.execute(
        select(IndexedEvent.id, IndexedEvent.search_text).where(IndexedEvent.case_id == case_id)
    ).all()
    backend = fts.rebuild_case(db, case_id, [(r[0], r[1]) for r in rows])
    db.commit()
    return {
        "case_id": case_id,
        "events": len(rows),
        "by_kind": {k: counts[k] for k in ("motion", "objects", "faces")},
        "placed_events": counts["placed"],
        "unplaceable_events": counts["unplaceable"],
        "removed_stale": removed,
        "runs_indexed": len(runs),
        "fulltext_backend": backend,
        "indexed_at": now,
        "label": TRIAGE_LABEL,
    }


def index_after_run(db: Session, run: AnalyticsRun) -> dict | None:
    """Hook for app.main / the analytics runner: reindex the run's case after it completes."""
    if run.status != "completed":
        return None
    return index_case(db, run.case_id)
