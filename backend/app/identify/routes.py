import json
import time

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app import __version__, custody
from app.evidence import IntegrityError, open_verified
from app.identify import engine
from app.identify.models import DeviceIdentification
from app.models import Evidence
from app.routes import DbSession, Examiner
from app.vendors import default_registry

router = APIRouter(prefix="/api")


def registry_key() -> str:
    return ",".join(f"{p.vendor}:{p.parser_version}" for p in default_registry().parsers)


@router.get("/evidence/{evidence_id}/identification")
def identification(evidence_id: int, db: DbSession, examiner: Examiner, refresh: bool = False):
    """Device intelligence. Computed once per (image hash, tool version, parser versions) from the
    hash-verified image, stored, custody-logged; later calls return the stored result unless
    `refresh=true`."""
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    key = registry_key()
    if not refresh:
        row = db.scalars(
            select(DeviceIdentification)
            .where(
                DeviceIdentification.evidence_id == ev.id,
                DeviceIdentification.evidence_sha256 == ev.sha256,
                DeviceIdentification.tool_version == __version__,
                DeviceIdentification.registry_key == key,
            )
            .order_by(DeviceIdentification.id.desc())
        ).first()
        if row is not None:
            return json.loads(row.result_json) | {"stored_id": row.id, "cached": True}
    t0 = time.perf_counter()
    try:
        with open_verified(db, ev, examiner) as f:
            result = engine.identify(f, ev.size_bytes)
    except IntegrityError as exc:
        raise HTTPException(409, str(exc)) from exc
    result |= {"evidence_id": ev.id, "evidence_sha256": ev.sha256, "tool_version": __version__}
    row = DeviceIdentification(
        case_id=ev.case_id,
        evidence_id=ev.id,
        evidence_sha256=ev.sha256,
        tool_version=__version__,
        registry_key=key,
        examiner=examiner,
        result_json=json.dumps(result),
        elapsed_ms=int((time.perf_counter() - t0) * 1000),
    )
    db.add(row)
    db.commit()
    custody.append_entry(
        db,
        ev.case_id,
        "device_identified",
        examiner,
        {
            "identification_id": row.id,
            "manufacturer": result["manufacturer"]["value"],
            "manufacturer_status": result["manufacturer"]["status"],
            "matches": result["matches"],
            "routing": result["routing"]["engine"],
            "parsers": key,
        },
        ev.id,
    )
    return result | {"stored_id": row.id, "cached": False}
