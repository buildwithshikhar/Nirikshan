"""Schema version guard. There is no migrations framework yet: a database created by an older
version of the code is refused at startup instead of being half-upgraded by create_all (which adds
missing tables but never missing columns). Bump SCHEMA_VERSION whenever a table or column changes.

History: 1 = P1 evidence core; 2 = P2 carving tables; 3 = P4 (clips.engine/channel/parsed_json,
carve_runs.parse_json); 4 = schema_meta introduced; 5 = P6 analytics tables
(analytics_runs, detections, motion_intervals);
6 = P5 tables (time_assumptions, time_references, time_models, osd_checks);
7 = P7 reports table.
"""

from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import SchemaMeta

SCHEMA_VERSION = 7


class SchemaError(RuntimeError):
    pass


def _msg(found: str) -> str:
    return (
        f"The database schema is outdated or unversioned ({found}); this build needs schema "
        f"version {SCHEMA_VERSION}. There are no migrations yet. For a development database run "
        "`python -m app.cli reset-db --yes` (DESTROYS all rows; case workspaces on disk are kept) "
        "or point DATABASE_URL at a new database."
    )


def check_and_init(engine: Engine) -> int:
    """Fresh database: create all tables and stamp the version. Existing database: the stamped
    version must equal SCHEMA_VERSION or SchemaError is raised before anything is changed."""
    tables = set(inspect(engine).get_table_names())
    if not tables:
        Base.metadata.create_all(engine)
        _stamp(engine)
        return SCHEMA_VERSION
    if SchemaMeta.__tablename__ not in tables:
        raise SchemaError(_msg("no schema_meta table: created before versioning"))
    with Session(engine) as db:
        row = db.scalars(select(SchemaMeta)).first()
    if row is None or row.version != SCHEMA_VERSION:
        raise SchemaError(_msg(f"found version {None if row is None else row.version}"))
    Base.metadata.create_all(engine)  # nothing to add for a current database; harmless
    return SCHEMA_VERSION


def _stamp(engine: Engine) -> None:
    with Session(engine) as db:
        db.add(SchemaMeta(id=1, version=SCHEMA_VERSION))
        db.commit()


def reset(engine: Engine) -> None:
    """Drop every known table and recreate the current schema (development only)."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    _stamp(engine)
