"""Correlation plumbing: topology validation, observation building, external log parsing.

Only this module reads database rows; it hands `links.candidates` Observations that contain
nothing but key, camera, class and UTC interval.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.correlation.links import EXTERNAL, Observation
from app.correlation.models import CameraTopology, ExternalLogEntry
from app.events.models import IndexedEvent
from app.timeline.timestamps import DST_AMBIGUOUS, DST_GAP, iso, localize, parse_iso_utc

MAX_LOG_BYTES = 5 * 1024 * 1024
MAX_LOG_ROWS = 100_000


class TopologyError(ValueError):
    pass


def validate_topology(nodes: list[dict], edges: list[dict]) -> None:
    ids = [n["id"] for n in nodes]
    if len(set(ids)) != len(ids):
        raise TopologyError("node ids must be unique")
    cams = [(n.get("evidence_id"), n["channel"]) for n in nodes if n.get("channel") is not None]
    if len(set(cams)) != len(cams):
        raise TopologyError("each (evidence_id, channel) may belong to one node only")
    known = set(ids)
    seen = set()
    for e in edges:
        if e["a"] not in known or e["b"] not in known:
            raise TopologyError(f"edge {e['a']}-{e['b']} refers to an unknown node")
        if e["a"] == e["b"]:
            raise TopologyError("an edge must join two different nodes")
        pair = tuple(sorted((e["a"], e["b"])))
        if pair in seen:
            raise TopologyError(f"duplicate edge {pair[0]}-{pair[1]}")
        seen.add(pair)


def topology_of(db: Session, case_id: int) -> CameraTopology | None:
    return db.scalars(select(CameraTopology).where(CameraTopology.case_id == case_id)).first()


def node_for(nodes: list[dict], evidence_id: int, channel: int | None) -> str | None:
    """Exact (evidence, channel) node first; else a node with no evidence_id and that channel."""
    if channel is None:
        return None
    for n in nodes:
        if n.get("evidence_id") == evidence_id and n.get("channel") == channel:
            return n["id"]
    for n in nodes:
        if n.get("evidence_id") is None and n.get("channel") == channel:
            return n["id"]
    return None


@dataclass
class Segment:
    key: str
    camera: str
    class_name: str
    clip_id: int
    evidence_id: int
    channel: int | None
    event_ids: list[int]
    nominal_first_s: float
    nominal_last_s: float
    utc_lo: datetime
    utc_hi: datetime

    def snapshot(self) -> dict:
        return {
            "type": "event_segment",
            "key": self.key,
            "camera_node": self.camera,
            "class_name": self.class_name,
            "clip_id": self.clip_id,
            "evidence_id": self.evidence_id,
            "camera": self.channel,
            "event_ids": self.event_ids,
            "first_event_id": self.event_ids[0],
            "nominal_first_s": self.nominal_first_s,
            "nominal_last_s": self.nominal_last_s,
            "utc_lo": iso(self.utc_lo),
            "utc_hi": iso(self.utc_hi),
            "links": {"video_at": f"/api/clips/{self.clip_id}/video#t={self.nominal_first_s:.3f}"},
        }


def event_segments(
    db: Session, case_id: int, nodes: list[dict], segment_gap_s: float
) -> tuple[list[Segment], dict]:
    """Group placed events per (clip, class) into runs whose consecutive nominal times differ by
    at most segment_gap_s. Time and class only."""
    rows = db.scalars(
        select(IndexedEvent)
        .where(IndexedEvent.case_id == case_id)
        .order_by(
            IndexedEvent.clip_id,
            IndexedEvent.class_name,
            IndexedEvent.nominal_time_s,
            IndexedEvent.id,
        )
    ).all()
    stats = {"events": len(rows), "unplaceable_events": 0, "events_without_camera_node": 0}
    segs: list[Segment] = []
    cur: Segment | None = None
    for e in rows:
        if e.placement != "placed" or not e.utc_lo:
            stats["unplaceable_events"] += 1
            continue
        node = node_for(nodes, e.evidence_id, e.channel)
        if node is None:
            stats["events_without_camera_node"] += 1
            continue
        lo, hi = parse_iso_utc(e.utc_lo), parse_iso_utc(e.utc_end_hi or e.utc_hi)
        if (
            cur is not None
            and cur.clip_id == e.clip_id
            and cur.class_name == e.class_name
            and e.nominal_time_s - cur.nominal_last_s <= segment_gap_s
        ):
            cur.event_ids.append(e.id)
            cur.nominal_last_s = max(cur.nominal_last_s, e.nominal_end_s)
            cur.utc_lo, cur.utc_hi = min(cur.utc_lo, lo), max(cur.utc_hi, hi)
            continue
        cur = Segment(
            "",
            node,
            e.class_name,
            e.clip_id,
            e.evidence_id,
            e.channel,
            [e.id],
            e.nominal_time_s,
            e.nominal_end_s,
            lo,
            hi,
        )
        segs.append(cur)
    for s in segs:
        s.key = f"seg:clip{s.clip_id}:{s.class_name}:{s.event_ids[0]}"
    stats["segments"] = len(segs)
    return segs, stats


def external_observations(db: Session, case_id: int) -> tuple[list[Observation], dict, dict]:
    rows = db.scalars(
        select(ExternalLogEntry)
        .where(ExternalLogEntry.case_id == case_id)
        .order_by(ExternalLogEntry.id)
    ).all()
    obs, snaps = [], {}
    stats = {"entries": len(rows), "unplaced_entries": 0, "entries_without_node": 0}
    for r in rows:
        if not r.utc_lo:
            stats["unplaced_entries"] += 1
            continue
        if not r.node_id:
            stats["entries_without_node"] += 1
            continue
        key = f"ext:{r.log_id}:{r.row_number}"
        obs.append(
            Observation(key, r.node_id, EXTERNAL, parse_iso_utc(r.utc_lo), parse_iso_utc(r.utc_hi))
        )
        snaps[key] = {
            "type": "external_log_entry",
            "key": key,
            "log_id": r.log_id,
            "entry_id": r.id,
            "row_number": r.row_number,
            "camera_node": r.node_id,
            "raw_time": r.raw_time,
            "event_text": r.event_text,
            "location": r.location,
            "utc_lo": r.utc_lo,
            "utc_hi": r.utc_hi,
        }
    return obs, snaps, stats


def resolution_of(fmt: str) -> float:
    if "%f" in fmt:
        return 1e-6
    if "%S" in fmt or "%T" in fmt:
        return 1.0
    if "%M" in fmt or "%R" in fmt:
        return 60.0
    if "%H" in fmt or "%I" in fmt:
        return 3600.0
    return 86400.0


def parse_log(
    content: str,
    mapping: dict,
    tz: str,
    time_format: str,
    location_nodes: dict[str, str],
    delimiter: str,
) -> tuple[list[dict], list[str]]:
    """Rows -> entry dicts (utc bounds or unplaced reason). Raises ValueError on bad mapping."""
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    headers = reader.fieldnames or []
    for role in ("time", "event", "location"):
        col = mapping.get(role)
        if col and col not in headers:
            raise ValueError(f"mapped {role} column {col!r} not in CSV header {headers}")
    res = resolution_of(time_format)
    out = []
    for n, row in enumerate(reader, start=1):
        if n > MAX_LOG_ROWS:
            raise ValueError(f"more than {MAX_LOG_ROWS} rows")
        raw = (row.get(mapping["time"]) or "").strip()
        loc = (row.get(mapping["location"]) or "").strip() if mapping.get("location") else ""
        ent = {
            "row_number": n,
            "raw_time": raw[:100],
            "event_text": (row.get(mapping["event"]) or "").strip() if mapping.get("event") else "",
            "location": loc[:200],
            "node_id": location_nodes.get(loc),
            "utc_lo": None,
            "utc_hi": None,
            "flags": "",
            "unplaced_reason": "",
            "raw_json": json.dumps(row, sort_keys=True, default=str),
        }
        try:
            naive = datetime.strptime(raw, time_format)
        except ValueError as e:
            ent["unplaced_reason"] = f"time {raw!r} does not match format {time_format!r}: {e}"
            out.append(ent)
            continue
        r = localize(naive, tz)
        if not r.candidates:
            ent["flags"] = DST_GAP
            ent["unplaced_reason"] = f"local time {raw} does not exist in {tz} (DST gap)"
        else:
            ent["utc_lo"] = iso(r.candidates[0])
            ent["utc_hi"] = iso(r.candidates[-1] + timedelta(seconds=res))
            if DST_AMBIGUOUS in r.flags:
                ent["flags"] = DST_AMBIGUOUS
        out.append(ent)
    return out, headers
