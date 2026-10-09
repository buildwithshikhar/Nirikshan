"""Execute a parsed query over the event index, and build template summaries."""

from __future__ import annotations

import json
import operator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import TRIAGE_LABEL
from app.events import SUMMARY_LABEL, fts
from app.events.grammar import Query, match_time
from app.events.models import IndexedEvent
from app.timeline.timestamps import parse_iso_utc

_OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "=": operator.eq,
    "!=": operator.ne,
}
SOURCE_NOTE = (
    "Byte range of the carved clip in the acquired evidence image; per-frame byte offsets are not "
    "mapped (frame_index is the decoded frame number of the exported clip)."
)


def hit(e: IndexedEvent, time_match: str | None = None) -> dict:
    return {
        "event_id": e.id,
        "case_id": e.case_id,
        "evidence_id": e.evidence_id,
        "clip_id": e.clip_id,
        "run_id": e.run_id,
        "kind": e.kind,
        "class_name": e.class_name,
        "camera": e.channel,
        "frame_index": e.frame_index,
        "end_frame_index": e.end_frame_index,
        "nominal_time_s": e.nominal_time_s,
        "nominal_end_s": e.nominal_end_s,
        "confidence": e.confidence,
        "motion_score_peak": e.motion_score_peak,
        "placement": e.placement,
        "unplaceable_reason": e.unplaceable_reason or None,
        "tz_status": e.tz_status,
        "assumed_timezone": e.assumed_timezone,
        "utc": (
            {"lo": e.utc_lo, "hi": e.utc_hi, "end_lo": e.utc_end_lo, "end_hi": e.utc_end_hi}
            if e.placement == "placed"
            else None
        ),
        "time_match": time_match,
        "model": {"name": e.model_name, "sha256": e.model_sha256 or None},
        "clip_hashes": {
            "bitstream_sha256": e.clip_bitstream_sha256,
            "mp4_sha256": e.clip_mp4_sha256,
        },
        "source": {
            "clip_start_offset": e.clip_start_offset,
            "clip_end_offset": e.clip_end_offset,
            "extents": json.loads(e.clip_extents_json or "[]"),
            "note": SOURCE_NOTE,
            "frame_byte_offset": {
                "available": False,
                "reason": "decoded frames are not mapped back to evidence byte offsets "
                "(see docs/ROUND_D_DEFERRED.md)",
            },
        },
        "links": {
            "video": f"/api/clips/{e.clip_id}/video",
            "video_at": f"/api/clips/{e.clip_id}/video#t={e.nominal_time_s:.3f}",
            "analytics_run": f"/api/analytics/{e.run_id}",
            "frame_index": e.frame_index,
        },
        "label": TRIAGE_LABEL,
    }


def search(db: Session, case_id: int, q: Query, limit: int, offset: int) -> dict:
    stmt = select(IndexedEvent).where(IndexedEvent.case_id == case_id)
    if q.classes:
        stmt = stmt.where(IndexedEvent.class_name.in_(sorted(q.classes)))
    if q.cameras:
        stmt = stmt.where(IndexedEvent.channel.in_(sorted(q.cameras)))
    if q.clips:
        stmt = stmt.where(IndexedEvent.clip_id.in_(sorted(q.clips)))
    if q.evidence:
        stmt = stmt.where(IndexedEvent.evidence_id.in_(sorted(q.evidence)))
    if q.kinds:
        stmt = stmt.where(IndexedEvent.kind.in_(sorted(q.kinds)))
    for op, v in q.confidence:
        stmt = stmt.where(IndexedEvent.confidence.is_not(None))
        stmt = stmt.where(_OPS[op](IndexedEvent.confidence, v))
    if q.placement:
        stmt = stmt.where(IndexedEvent.placement == q.placement)
    backend = fts.backend_name(db)
    ids = fts.matching_ids(db, case_id, q.text) if q.text else None
    if q.text and ids is None:
        stmt = stmt.where(*fts.like_clauses(q.text))
    stmt = stmt.order_by(
        IndexedEvent.utc_lo.is_(None),
        IndexedEvent.utc_lo,
        IndexedEvent.clip_id,
        IndexedEvent.nominal_time_s,
        IndexedEvent.id,
    )
    rows = db.scalars(stmt).all()
    if ids is not None:
        rows = [e for e in rows if e.id in ids]
    excluded_clips: set[int] = set()
    no_zone_clips: set[int] = set()
    hits: list[tuple[IndexedEvent, str | None]] = []
    for e in rows:
        if not q.has_time:
            hits.append((e, None))
            continue
        if e.placement != "placed":
            excluded_clips.add(e.clip_id)
            continue
        zone = q.zone or e.assumed_timezone
        if not zone:
            no_zone_clips.add(e.clip_id)
            continue
        m = match_time(q, parse_iso_utc(e.utc_lo), parse_iso_utc(e.utc_end_hi or e.utc_hi), zone)
        if m:
            hits.append((e, m))
    page = hits[offset : offset + limit]
    notes = []
    if q.has_time:
        notes.append(
            f"{len(excluded_clips)} clip(s) excluded as unplaceable: time-of-day and date clauses "
            "apply only to clips the timeline places in absolute time (no default timezone)."
        )
        if no_zone_clips:
            notes.append(
                f"{len(no_zone_clips)} placed clip(s) excluded: their evidence has a UTC epoch "
                "basis but no device timezone, so a device-local time of day is undefined; add "
                "'utc' or 'tz <zone>' to the query to include them."
            )
        notes.append(
            "'overlaps_boundary' hits have an uncertainty interval that crosses the window edge."
        )
    if q.confidence:
        notes.append("Motion events carry no confidence and never match a confidence clause.")
    return {
        "case_id": case_id,
        "interpreted": q.describe(),
        "total": len(hits),
        "offset": offset,
        "limit": limit,
        "hits": [hit(e, m) for e, m in page],
        "excluded_unplaceable_clips": len(excluded_clips) if q.has_time else 0,
        "excluded_unplaceable_clip_ids": sorted(excluded_clips),
        "excluded_no_device_timezone_clip_ids": sorted(no_zone_clips),
        "fulltext_backend": backend,
        "notes": notes,
        "label": TRIAGE_LABEL,
    }


def _span(vals: list[str | None], pick) -> str | None:
    vals = [v for v in vals if v]
    return pick(vals, key=parse_iso_utc) if vals else None


def summaries(db: Session, case_id: int, by: str) -> dict:
    rows = db.scalars(
        select(IndexedEvent)
        .where(IndexedEvent.case_id == case_id)
        .order_by(IndexedEvent.clip_id, IndexedEvent.nominal_time_s, IndexedEvent.id)
    ).all()
    groups: dict[tuple, list[IndexedEvent]] = {}
    for e in rows:
        key = (e.clip_id,) if by == "clip" else (e.evidence_id, e.channel)
        groups.setdefault(key, []).append(e)
    out = []
    for key, evs in groups.items():
        classes: dict[str, list[IndexedEvent]] = {}
        for e in evs:
            classes.setdefault(e.class_name, []).append(e)
        per_class = []
        sentences = []
        for cls in sorted(classes):
            ce = classes[cls]
            placed = [e for e in ce if e.placement == "placed"]
            n_clips = len({e.clip_id for e in ce})
            item = {
                "class_name": cls,
                "kind": ce[0].kind,
                "count": len(ce),
                "clips": n_clips,
                "nominal_first_s": min(e.nominal_time_s for e in ce),
                "nominal_last_s": max(e.nominal_end_s for e in ce),
                "placed_count": len(placed),
                "utc_earliest_lo": _span([e.utc_lo for e in placed], min),
                "utc_latest_hi": _span([e.utc_end_hi for e in placed], max),
                "max_confidence": max(
                    (e.confidence for e in ce if e.confidence is not None), default=None
                ),
            }
            per_class.append(item)
            noun = "motion interval" if cls == "motion" else f"{cls.replace('_', ' ')} detection"
            s = f"{item['count']} {noun}{'s' if item['count'] != 1 else ''}"
            if by == "clip":
                t0, t1 = item["nominal_first_s"], item["nominal_last_s"]
                s += f" between {t0:.2f} s and {t1:.2f} s of the clip"
            else:
                s += f" across {n_clips} clip{'s' if n_clips != 1 else ''}"
            if item["utc_earliest_lo"]:
                lo, hi = item["utc_earliest_lo"], item["utc_latest_hi"]
                s += f"; placed ones span UTC {lo} to {hi} (uncertainty bounds)"
            if len(placed) < len(ce):
                s += f"; {len(ce) - len(placed)} without absolute time (clip unplaceable)"
            sentences.append(s)
        head = (
            f"Clip {key[0]} (camera {evs[0].channel if evs[0].channel is not None else 'unknown'})"
            if by == "clip"
            else f"Evidence {key[0]}, camera {key[1] if key[1] is not None else 'unknown'}"
        )
        out.append(
            {
                "group": {"clip_id": key[0]}
                if by == "clip"
                else {"evidence_id": key[0], "camera": key[1]},
                "classes": per_class,
                "text": head + ": " + "; ".join(sentences) + ".",
                "label": SUMMARY_LABEL,
            }
        )
    return {
        "case_id": case_id,
        "by": by,
        "label": SUMMARY_LABEL,
        "triage_label": TRIAGE_LABEL,
        "template": (
            "<group>: <count> <class> detection(s) between <first> s and <last> s of the clip "
            "[; placed ones span UTC <lo> to <hi>] [; <n> without absolute time]"
        ),
        "events_indexed": len(rows),
        "summaries": out,
    }
