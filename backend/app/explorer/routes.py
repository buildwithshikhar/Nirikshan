"""Storage explorer API: bounded hex reads, region map, partition/FS signatures, anomalies."""

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.explorer import gate, partitions, regions
from app.explorer.models import RawReadAudit
from app.models import CarveRun, Clip
from app.routes import DbSession, Examiner

router = APIRouter(prefix="/api")
MAX_HEX = 4096
BENIGN = {"generic_includes_extra_bytes", "frame_count_mismatch"}  # same set as validation


@router.get("/evidence/{evidence_id}/hex")
def hex_read(
    evidence_id: int,
    db: DbSession,
    examiner: Examiner,
    offset: Annotated[int, Query(ge=0)] = 0,
    length: Annotated[int, Query(ge=1, le=MAX_HEX)] = 512,
):
    ev = gate.get_evidence(db, evidence_id)
    g = gate.check(ev)
    if offset >= ev.size_bytes:
        raise HTTPException(416, f"offset {offset} is beyond the image size {ev.size_bytes}")
    n = min(length, ev.size_bytes - offset)
    with gate.open_image(ev) as f:
        f.seek(offset)
        data = f.read(n)
    digest = hashlib.sha256(data).hexdigest()
    db.add(
        RawReadAudit(
            case_id=ev.case_id,
            evidence_id=ev.id,
            examiner=examiner,
            offset=offset,
            length=len(data),
            bytes_sha256=digest,
        )
    )
    db.commit()
    return {
        "evidence_id": ev.id,
        "offset": offset,
        "length": len(data),
        "requested_length": length,
        "max_length": MAX_HEX,
        "image_size": ev.size_bytes,
        "hex": data.hex(),
        "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in data),
        "bytes_sha256": digest,
        "integrity": g,
        "audit": "recorded in raw_read_audit; not custody-logged per read",
    }


def _run(db, evidence_id: int, run_id: int | None) -> CarveRun | None:
    q = select(CarveRun).where(CarveRun.evidence_id == evidence_id, CarveRun.status == "completed")
    if run_id is not None:
        run = db.get(CarveRun, run_id)
        if run is None or run.evidence_id != evidence_id:
            raise HTTPException(404, "Run not found for this evidence")
        return run
    return db.scalars(q.order_by(CarveRun.id.desc())).first()


@router.get("/evidence/{evidence_id}/partitions")
def partition_table(evidence_id: int, db: DbSession):
    ev = gate.get_evidence(db, evidence_id)
    g = gate.check(ev)
    with gate.open_image(ev) as f:
        out = partitions.detect(f, ev.size_bytes)
    return out | {"evidence_id": ev.id, "integrity": g}


@router.get("/evidence/{evidence_id}/regions")
def region_map(
    evidence_id: int,
    db: DbSession,
    run_id: int | None = None,
    scan_bytes: Annotated[int, Query(ge=0, le=regions.MAX_SCAN)] = regions.DEFAULT_SCAN,
    max_regions: Annotated[int, Query(ge=1, le=regions.MAX_REGIONS)] = regions.DEFAULT_MAX_REGIONS,
):
    ev = gate.get_evidence(db, evidence_id)
    g = gate.check(ev)
    run = _run(db, ev.id, run_id)
    clips = (
        db.scalars(select(Clip).where(Clip.run_id == run.id).order_by(Clip.start_offset)).all()
        if run
        else []
    )
    with gate.open_image(ev) as f:
        pt = partitions.detect(f, ev.size_bytes)
        zeros, scanned = regions.zero_blocks(f, ev.size_bytes, scan_bytes)
    iv = regions.intervals_from_run(run, clips) + regions.intervals_from_partitions(pt)
    regs = regions.build(iv, ev.size_bytes, zeros, scanned)
    notes = [
        f"zero/unknown classification covers bytes [0, {scanned}) in {regions.BLOCK}-byte blocks; "
        "the rest is 'not_scanned' (raise scan_bytes up to "
        f"{regions.MAX_SCAN} to scan more)",
        "clip spans run from the first to the last payload extent (vendor headers inside them)",
    ]
    if run is None:
        notes.append("no completed analysis run: clips, orphans and vendor structures are absent")
    return {
        "evidence_id": ev.id,
        "run_id": run.id if run else None,
        "image_size": ev.size_bytes,
        "scanned_bytes": scanned,
        "block_size": regions.BLOCK,
        "summary": regions.summary(regs, ev.size_bytes),
        "region_count": len(regs),
        "truncated": len(regs) > max_regions,
        "regions": [
            {"start": s, "end": e, "bytes": e - s, "kind": k, **({"ref": r} if r else {})}
            for s, e, k, r in regs[:max_regions]
        ],
        "integrity": g,
        "notes": notes,
    }


@router.get("/evidence/{evidence_id}/anomalies")
def anomalies(evidence_id: int, db: DbSession, run_id: int | None = None):
    """Structural anomalies: parser inconsistencies/warnings and parser-vs-generic disagreements
    stored with the run, decode failures of stored clips, and partition-table anomalies."""
    ev = gate.get_evidence(db, evidence_id)
    g = gate.check(ev)
    run = _run(db, ev.id, run_id)
    items: list[dict] = []
    if run is not None:
        for p in json.loads(run.parse_json or "[]"):
            src = f"{p['parser']} parser ({p['status']})"
            for msg in p.get("inconsistencies", []):
                items.append(
                    {
                        "severity": "warning",
                        "kind": "parser_inconsistency",
                        "source": src,
                        "detail": msg,
                    }
                )
            for msg in p.get("warnings", []):
                items.append(
                    {"severity": "info", "kind": "parser_warning", "source": src, "detail": msg}
                )
            for d in (p.get("crosscheck") or {}).get("disagreements", []):
                items.append(
                    {
                        "severity": "info" if d["kind"] in BENIGN else "warning",
                        "kind": f"crosscheck_{d['kind']}",
                        "source": f"{p['parser']} parser vs generic carver",
                        "offset": d.get("offset"),
                        "detail": d,
                        **(
                            {"note": "expected header absorption, benign"}
                            if d["kind"] in BENIGN
                            else {}
                        ),
                    }
                )
        for c in db.scalars(
            select(Clip).where(
                Clip.run_id == run.id,
                Clip.kind == "clip",
                Clip.decode_status.in_(("decode_errors", "export_failed")),
            )
        ):
            items.append(
                {
                    "severity": "warning",
                    "kind": f"clip_{c.decode_status}",
                    "source": f"clip {c.id} ({c.engine})",
                    "offset": c.start_offset,
                    "detail": json.loads(c.decode_errors_json)[:3] or c.error,
                }
            )
    with gate.open_image(ev) as f:
        pt = partitions.detect(f, ev.size_bytes)
    for a in pt["anomalies"]:
        items.append(
            {
                "severity": "warning",
                "kind": a["kind"],
                "source": "partition table",
                "offset": a.get("offset"),
                "detail": a,
            }
        )
    return {
        "evidence_id": ev.id,
        "run_id": run.id if run else None,
        "count": len(items),
        "warnings": sum(1 for i in items if i["severity"] == "warning"),
        "anomalies": items,
        "integrity": g,
        "note": None if run else "no completed analysis run: only partition anomalies are shown",
    }
