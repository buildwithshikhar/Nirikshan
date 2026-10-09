"""Correlation API: camera topology + floor plan, external logs, link suggestions and decisions.

Every mutation requires an examiner and writes a custody entry.
"""

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import custody
from app.analytics import TRIAGE_LABEL
from app.clock import utc_now_iso
from app.config import data_dir
from app.correlation import LINK_LABEL, links, service
from app.correlation.models import CameraTopology, CorrelationLink, ExternalLog, ExternalLogEntry
from app.models import Case
from app.routes import DbSession, Examiner
from app.timeline.timestamps import TzError, get_zone

router = APIRouter(prefix="/api")

MAX_FLOORPLAN_BYTES = 5 * 1024 * 1024
IMAGE_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n", "png"),
    "image/jpeg": (b"\xff\xd8\xff", "jpg"),
}
NO_APPEARANCE = (
    "Links use time windows, the examiner's camera topology and detection class only. No "
    "appearance, face or re-identification matching is performed."
)


class Node(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    label: str = Field(default="", max_length=200)
    evidence_id: int | None = None
    channel: int | None = None
    x: float | None = None
    y: float | None = None


class Edge(BaseModel):
    a: str
    b: str
    max_transit_s: float | None = Field(default=None, gt=0, le=86400)


class TopologyIn(BaseModel):
    nodes: list[Node] = Field(max_length=500)
    edges: list[Edge] = Field(default_factory=list, max_length=5000)
    coordinate_units: str = Field(default="", max_length=40)
    notes: str = ""


class ColumnMap(BaseModel):
    time: str = Field(min_length=1)
    event: str | None = None
    location: str | None = None


class ExternalLogIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    authorization_note: str = Field(
        min_length=1, description="legal authority / consent under which the log was obtained"
    )
    timezone: str = Field(
        min_length=1, max_length=64, description="IANA zone; required, no default"
    )
    time_format: str = Field(min_length=2, max_length=64, description="strptime wall-clock format")
    mapping: ColumnMap
    location_nodes: dict[str, str] = Field(default_factory=dict)
    delimiter: str = Field(default=",", min_length=1, max_length=1)


class GenerateIn(BaseModel):
    window_s: float = Field(gt=0, le=86400)
    require_same_class: bool = True
    segment_gap_s: float = Field(default=2.0, ge=0, le=3600)
    include_external_logs: bool = True


class DecisionIn(BaseModel):
    decision: Literal["accept", "reject"]
    note: str = Field(min_length=1)


def _case(db, case_id: int) -> Case:
    c = db.get(Case, case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    return c


def _topology_out(t: CameraTopology | None, case_id: int) -> dict:
    if t is None:
        return {"case_id": case_id, "defined": False, "nodes": [], "edges": [], "floorplan": None}
    return {
        "case_id": case_id,
        "defined": True,
        "nodes": json.loads(t.nodes_json),
        "edges": json.loads(t.edges_json),
        "coordinate_units": t.coordinate_units,
        "notes": t.notes,
        "examiner": t.examiner,
        "updated_at": t.updated_at,
        "floorplan": (
            {
                "sha256": t.floorplan_sha256,
                "content_type": t.floorplan_content_type,
                "size_bytes": t.floorplan_size,
                "url": f"/api/cases/{case_id}/correlation/floorplan",
            }
            if t.floorplan_sha256
            else None
        ),
    }


@router.get("/cases/{case_id}/correlation/topology")
def get_topology(case_id: int, db: DbSession):
    _case(db, case_id)
    return _topology_out(service.topology_of(db, case_id), case_id)


@router.put("/cases/{case_id}/correlation/topology")
def put_topology(case_id: int, body: TopologyIn, db: DbSession, examiner: Examiner):
    _case(db, case_id)
    nodes = [n.model_dump() for n in body.nodes]
    edges = [e.model_dump() for e in body.edges]
    try:
        service.validate_topology(nodes, edges)
    except service.TopologyError as e:
        raise HTTPException(422, str(e)) from e
    t = service.topology_of(db, case_id)
    before = _topology_out(t, case_id)
    if t is None:
        t = CameraTopology(case_id=case_id, examiner=examiner)
        db.add(t)
    t.nodes_json, t.edges_json = json.dumps(nodes), json.dumps(edges)
    t.coordinate_units, t.notes, t.examiner = body.coordinate_units, body.notes, examiner
    t.updated_at = utc_now_iso()
    db.commit()
    after = _topology_out(t, case_id)
    custody.append_entry(
        db, case_id, "camera_topology_set", examiner, {"before": before, "after": after}
    )
    return after


@router.put("/cases/{case_id}/correlation/floorplan")
async def put_floorplan(case_id: int, request: Request, db: DbSession, examiner: Examiner):
    """Raw image body (Content-Type image/png or image/jpeg, at most 5 MiB)."""
    _case(db, case_id)
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in IMAGE_MAGIC:
        raise HTTPException(415, "floor plan must be image/png or image/jpeg")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FLOORPLAN_BYTES:
        raise HTTPException(413, f"floor plan larger than {MAX_FLOORPLAN_BYTES} bytes")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_FLOORPLAN_BYTES:
            raise HTTPException(413, f"floor plan larger than {MAX_FLOORPLAN_BYTES} bytes")
    magic, ext = IMAGE_MAGIC[ctype]
    if not bytes(buf).startswith(magic):
        raise HTTPException(415, f"body does not start with the {ctype} signature")
    sha = hashlib.sha256(buf).hexdigest()
    folder = data_dir() / "correlation" / f"case_{case_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"floorplan_{sha}.{ext}"
    path.write_bytes(bytes(buf))
    t = service.topology_of(db, case_id)
    if t is None:
        t = CameraTopology(case_id=case_id, examiner=examiner)
        db.add(t)
    previous = t.floorplan_sha256 or None
    t.floorplan_path, t.floorplan_sha256 = str(path), sha
    t.floorplan_content_type, t.floorplan_size = ctype, len(buf)
    t.updated_at = utc_now_iso()
    db.commit()
    details = {
        "sha256": sha,
        "size_bytes": len(buf),
        "content_type": ctype,
        "previous_sha256": previous,
    }
    custody.append_entry(db, case_id, "floorplan_uploaded", examiner, details)
    return {**details, "url": f"/api/cases/{case_id}/correlation/floorplan"}


@router.get("/cases/{case_id}/correlation/floorplan")
def get_floorplan(case_id: int, db: DbSession):
    _case(db, case_id)
    t = service.topology_of(db, case_id)
    if t is None or not t.floorplan_sha256:
        raise HTTPException(404, "No floor plan uploaded")
    try:
        data = open(t.floorplan_path, "rb").read()
    except OSError as e:
        raise HTTPException(404, "Stored floor plan file is missing") from e
    if hashlib.sha256(data).hexdigest() != t.floorplan_sha256:
        raise HTTPException(409, "Stored floor plan no longer matches its recorded SHA-256")
    return FileResponse(
        t.floorplan_path,
        media_type=t.floorplan_content_type,
        headers={"X-Content-SHA256": t.floorplan_sha256},
    )


def _log_out(r: ExternalLog) -> dict:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "filename": r.filename,
        "sha256": r.sha256,
        "size_bytes": r.size_bytes,
        "timezone": r.timezone,
        "time_format": r.time_format,
        "resolution_s": r.resolution_s,
        "mapping": json.loads(r.mapping_json),
        "authorization_note": r.authorization_note,
        "row_count": r.row_count,
        "rows_unplaced": r.rows_unplaced,
        "examiner": r.examiner,
        "imported_at": r.imported_at,
    }


@router.post("/cases/{case_id}/correlation/external-logs", status_code=201)
def import_external_log(case_id: int, body: ExternalLogIn, db: DbSession, examiner: Examiner):
    _case(db, case_id)
    raw = body.content.encode("utf-8")
    if len(raw) > service.MAX_LOG_BYTES:
        raise HTTPException(413, f"log larger than {service.MAX_LOG_BYTES} bytes")
    tz = body.timezone.strip()
    try:
        get_zone(tz)
    except TzError as e:
        raise HTTPException(422, str(e)) from e
    if "%z" in body.time_format or "%Z" in body.time_format:
        raise HTTPException(
            422, "time_format must be a wall-clock format; give the zone in 'timezone' instead"
        )
    if not body.authorization_note.strip():
        raise HTTPException(422, "authorization_note is required")
    topo = service.topology_of(db, case_id)
    known = {n["id"] for n in json.loads(topo.nodes_json)} if topo else set()
    bad = sorted({v for v in body.location_nodes.values() if v not in known})
    if bad:
        raise HTTPException(422, f"location_nodes refer to unknown topology nodes: {bad}")
    try:
        entries, headers = service.parse_log(
            body.content,
            body.mapping.model_dump(),
            tz,
            body.time_format,
            body.location_nodes,
            body.delimiter,
        )
    except (ValueError, UnicodeError) as e:
        raise HTTPException(422, str(e)) from e
    sha = hashlib.sha256(raw).hexdigest()
    folder = data_dir() / "correlation" / f"case_{case_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"extlog_{sha}.csv"
    path.write_bytes(raw)
    log = ExternalLog(
        case_id=case_id,
        filename=body.filename,
        sha256=sha,
        size_bytes=len(raw),
        stored_path=str(path),
        timezone=tz,
        time_format=body.time_format,
        resolution_s=service.resolution_of(body.time_format),
        mapping_json=json.dumps(
            {
                **body.mapping.model_dump(),
                "location_nodes": body.location_nodes,
                "delimiter": body.delimiter,
                "headers": headers,
            },
            sort_keys=True,
        ),
        authorization_note=body.authorization_note.strip(),
        row_count=len(entries),
        rows_unplaced=sum(1 for e in entries if not e["utc_lo"]),
        examiner=examiner,
    )
    db.add(log)
    db.flush()
    for e in entries:
        db.add(ExternalLogEntry(log_id=log.id, case_id=case_id, **e))
    db.commit()
    out = _log_out(log)
    custody.append_entry(db, case_id, "external_log_imported", examiner, out)
    return out


@router.get("/cases/{case_id}/correlation/external-logs")
def list_external_logs(case_id: int, db: DbSession):
    _case(db, case_id)
    rows = db.scalars(
        select(ExternalLog).where(ExternalLog.case_id == case_id).order_by(ExternalLog.id)
    )
    return [_log_out(r) for r in rows]


@router.get("/correlation/external-logs/{log_id}")
def get_external_log(log_id: int, db: DbSession):
    log = db.get(ExternalLog, log_id)
    if log is None:
        raise HTTPException(404, "External log not found")
    rows = db.scalars(
        select(ExternalLogEntry)
        .where(ExternalLogEntry.log_id == log_id)
        .order_by(ExternalLogEntry.row_number)
    ).all()
    out = _log_out(log)
    out["entries"] = [
        {
            "id": r.id,
            "row_number": r.row_number,
            "raw_time": r.raw_time,
            "event_text": r.event_text,
            "location": r.location,
            "node_id": r.node_id,
            "utc_lo": r.utc_lo,
            "utc_hi": r.utc_hi,
            "flags": r.flags,
            "unplaced_reason": r.unplaced_reason or None,
            "raw": json.loads(r.raw_json),
        }
        for r in rows
    ]
    return out


def _link_out(r: CorrelationLink) -> dict:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "status": r.status,
        "a": json.loads(r.a_json),
        "b": json.loads(r.b_json),
        "rules": [{"rule": k, "detail": d} for k, d in json.loads(r.rules_json)],
        "explanation": r.explanation,
        "gap_s_min": r.gap_s_min,
        "gap_s_max": r.gap_s_max,
        "decided_by": r.decided_by or None,
        "decided_at": r.decided_at or None,
        "decision_note": r.decision_note or None,
        "params": json.loads(r.params_json),
        "label": r.label,
        "triage_label": TRIAGE_LABEL,
    }


@router.post("/cases/{case_id}/correlation/links/generate")
def generate_links(case_id: int, body: GenerateIn, db: DbSession, examiner: Examiner):
    _case(db, case_id)
    topo = service.topology_of(db, case_id)
    nodes = json.loads(topo.nodes_json) if topo else []
    edges = json.loads(topo.edges_json) if topo else []
    if not nodes or not edges:
        raise HTTPException(
            409, "define a camera topology with at least one edge first (links need adjacency)"
        )
    segs, stats = service.event_segments(db, case_id, nodes, body.segment_gap_s)
    snaps = {s.key: s.snapshot() for s in segs}
    obs = [links.Observation(s.key, s.camera, s.class_name, s.utc_lo, s.utc_hi) for s in segs]
    if body.include_external_logs:
        ext, ext_snaps, ext_stats = service.external_observations(db, case_id)
        obs += ext
        snaps.update(ext_snaps)
        stats["external"] = ext_stats
    found = links.candidates(obs, links.adjacency(edges), body.window_s, body.require_same_class)
    params = body.model_dump()
    existing = {
        (r.a_key, r.b_key): r
        for r in db.scalars(select(CorrelationLink).where(CorrelationLink.case_id == case_id))
    }
    keep = set()
    created = updated = 0
    for c in found:
        keep.add((c.a, c.b))
        row = existing.get((c.a, c.b))
        values = {
            "a_json": json.dumps(snaps[c.a]),
            "b_json": json.dumps(snaps[c.b]),
            "rules_json": json.dumps([list(r) for r in c.rules]),
            "explanation": c.explanation(),
            "gap_s_min": c.gap_s_min,
            "gap_s_max": c.gap_s_max,
            "params_json": json.dumps(params, sort_keys=True),
        }
        if row is None:
            db.add(CorrelationLink(case_id=case_id, a_key=c.a, b_key=c.b, **values))
            created += 1
        elif row.status == "suggested":
            for k, v in values.items():
                setattr(row, k, v)
            updated += 1
    dropped = 0
    for key, row in existing.items():
        if key not in keep and row.status == "suggested":
            db.delete(row)
            dropped += 1
    db.commit()
    out = {
        "case_id": case_id,
        "params": params,
        "candidates": len(found),
        "created": created,
        "updated": updated,
        "dropped_stale_suggestions": dropped,
        "decided_links_kept": sum(1 for r in existing.values() if r.status != "suggested"),
        "inputs": stats,
        "note": NO_APPEARANCE,
        "label": LINK_LABEL,
    }
    custody.append_entry(db, case_id, "correlation_links_generated", examiner, out)
    return out


@router.get("/cases/{case_id}/correlation/links")
def list_links(
    case_id: int,
    db: DbSession,
    status: Annotated[Literal["suggested", "accepted", "rejected"] | None, Query()] = None,
):
    _case(db, case_id)
    q = select(CorrelationLink).where(CorrelationLink.case_id == case_id)
    if status:
        q = q.where(CorrelationLink.status == status)
    rows = db.scalars(q.order_by(CorrelationLink.gap_s_min, CorrelationLink.id)).all()
    return {
        "case_id": case_id,
        "links": [_link_out(r) for r in rows],
        "note": NO_APPEARANCE,
        "label": LINK_LABEL,
    }


@router.post("/correlation/links/{link_id}/decision")
def decide_link(link_id: int, body: DecisionIn, db: DbSession, examiner: Examiner):
    row = db.get(CorrelationLink, link_id)
    if row is None:
        raise HTTPException(404, "Link not found")
    if not body.note.strip():
        raise HTTPException(422, "a decision note is required")
    before = row.status
    row.status = "accepted" if body.decision == "accept" else "rejected"
    row.decided_by, row.decided_at, row.decision_note = examiner, utc_now_iso(), body.note.strip()
    db.commit()
    out = _link_out(row)
    custody.append_entry(
        db,
        row.case_id,
        "correlation_link_decided",
        examiner,
        {
            "link_id": row.id,
            "before": before,
            "after": row.status,
            "note": row.decision_note,
            "link": out,
        },
    )
    return out
