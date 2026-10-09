"""Full-text search backend for the event index.

SQLite with the FTS5 extension: a separate `ai_events_fts` virtual table (rowid = event id),
created on first use. Anything else (Postgres, or SQLite built without FTS5): a portable
fallback that ANDs one case-insensitive substring match per term over `ai_events.search_text`
(ILIKE on Postgres, LIKE on SQLite, which is case-insensitive for ASCII). The fallback has no
ranking and no stemming; the response always names the backend used.

User terms never reach FTS5 query syntax: each term is reduced to [a-z0-9_] and double-quoted.
"""

import re

from sqlalchemy import DDL, event, text
from sqlalchemy.orm import Session

from app.events.models import IndexedEvent

FTS_TABLE = "ai_events_fts"
TERM_RE = re.compile(r"[a-z0-9_]+")

# Dropping ai_events (tests, resets) also drops the FTS shadow table on SQLite.
event.listen(
    IndexedEvent.__table__,
    "before_drop",
    DDL(f"DROP TABLE IF EXISTS {FTS_TABLE}").execute_if(dialect="sqlite"),
)


def terms(raw: str) -> list[str]:
    return TERM_RE.findall(raw.lower())


def _sqlite(db: Session) -> bool:
    return db.get_bind().dialect.name == "sqlite"


def ensure(db: Session) -> bool:
    """Create the FTS5 table if possible. True when FTS5 is usable on this connection."""
    if not _sqlite(db):
        return False
    try:
        db.execute(
            text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} "
                "USING fts5(body, case_id UNINDEXED)"
            )
        )
        return True
    except Exception:  # noqa: BLE001 - SQLite without FTS5: fall back to LIKE
        db.rollback()
        return False


def backend_name(db: Session) -> str:
    if ensure(db):
        return "sqlite-fts5"
    return "postgres-ilike" if db.get_bind().dialect.name == "postgresql" else "like-fallback"


def rebuild_case(db: Session, case_id: int, rows: list[tuple[int, str]]) -> str:
    """Replace the FTS rows of one case. Returns the backend name."""
    if not ensure(db):
        return backend_name(db)
    db.execute(text(f"DELETE FROM {FTS_TABLE} WHERE case_id = :c"), {"c": case_id})
    if rows:
        db.execute(
            text(f"INSERT INTO {FTS_TABLE}(rowid, body, case_id) VALUES (:id, :body, :c)"),
            [{"id": i, "body": b, "c": case_id} for i, b in rows],
        )
    return "sqlite-fts5"


def matching_ids(db: Session, case_id: int, words: list[str]) -> set[int] | None:
    """Event ids matching all terms via FTS5, or None when FTS5 is unavailable (caller uses the
    LIKE/ILIKE fallback in SQL)."""
    if not words or not ensure(db):
        return None
    q = " ".join(f'"{w}"' for w in words)
    res = db.execute(
        text(f"SELECT rowid FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH :q AND case_id = :c"),
        {"q": q, "c": case_id},
    )
    return {r[0] for r in res}


def like_clauses(words: list[str]):
    col = IndexedEvent.search_text
    return [col.ilike("%" + w.replace("_", "/_") + "%", escape="/") for w in words]
