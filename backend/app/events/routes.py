"""Event index API. The lead registers `router` in app.main (prefix /api is built in)."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app import custody
from app.analytics import TRIAGE_LABEL
from app.events import SUMMARY_LABEL, fts, grammar, indexer, search
from app.events.models import IndexedEvent
from app.models import Case
from app.routes import DbSession, Examiner

router = APIRouter(prefix="/api")


def _case(db, case_id: int) -> Case:
    c = db.get(Case, case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    return c


@router.get("/events/grammar")
def event_grammar():
    """The supported query grammar (deterministic, offline)."""
    return {**grammar.GRAMMAR, "label": TRIAGE_LABEL, "summary_label": SUMMARY_LABEL}


@router.post("/cases/{case_id}/events/reindex")
def reindex_events(case_id: int, db: DbSession, examiner: Examiner):
    """Rebuild the event index of a case from stored analytics rows (idempotent)."""
    _case(db, case_id)
    out = indexer.index_case(db, case_id)
    custody.append_entry(db, case_id, "ai_events_indexed", examiner, out)
    return out


@router.get("/cases/{case_id}/events/status")
def event_index_status(case_id: int, db: DbSession):
    _case(db, case_id)
    n, last = db.execute(
        select(func.count(IndexedEvent.id), func.max(IndexedEvent.indexed_at)).where(
            IndexedEvent.case_id == case_id
        )
    ).one()
    return {
        "case_id": case_id,
        "events": n,
        "indexed_at": last,
        "fulltext_backend": fts.backend_name(db),
        "label": TRIAGE_LABEL,
    }


@router.get("/cases/{case_id}/events/search")
def search_events(
    case_id: int,
    db: DbSession,
    q: Annotated[str, Query(max_length=500)] = "",
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _case(db, case_id)
    try:
        parsed = grammar.parse(q)
    except grammar.QueryError as e:
        raise HTTPException(422, e.to_dict()) from e
    out = search.search(db, case_id, parsed, limit, offset)
    out["query"] = q
    return out


@router.get("/cases/{case_id}/summaries")
def event_summaries(case_id: int, db: DbSession, by: Literal["clip", "camera"] = "clip"):
    _case(db, case_id)
    return search.summaries(db, case_id, by)
