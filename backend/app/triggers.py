"""Database-level append-only enforcement for custody_entries and audit_log.

BEFORE UPDATE / BEFORE DELETE triggers (and TRUNCATE on Postgres) abort the statement. This stops
accidental or casual direct-SQL edits. It does NOT stop a database owner/superuser, who can drop
the triggers; that case is what the hash chain + signatures detect (see docs/ARCHITECTURE.md).
"""

from sqlalchemy import DDL, Table, event, text

from app.models import AuditEntry, CustodyEntry

PROTECTED = (CustodyEntry.__table__, AuditEntry.__table__)

_PG_FUNCTION = DDL(
    "CREATE OR REPLACE FUNCTION nirikshan_reject_mutation() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION '%% is append-only', TG_TABLE_NAME; END; $$ LANGUAGE plpgsql"
)


def _trigger_name(table: Table, op: str) -> str:
    return f"{table.name}_no_{op.lower()}"


def _register(table: Table) -> None:
    event.listen(table, "after_create", _PG_FUNCTION.execute_if(dialect="postgresql"))
    for op in ("UPDATE", "DELETE"):
        name = _trigger_name(table, op)
        event.listen(
            table,
            "after_create",
            DDL(
                f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {op} ON {table.name} "
                f"BEGIN SELECT RAISE(ABORT, '{table.name} is append-only'); END"
            ).execute_if(dialect="sqlite"),
        )
        event.listen(
            table,
            "after_create",
            DDL(
                f"CREATE TRIGGER {name} BEFORE {op} ON {table.name} "
                "FOR EACH ROW EXECUTE FUNCTION nirikshan_reject_mutation()"
            ).execute_if(dialect="postgresql"),
        )
    event.listen(
        table,
        "after_create",
        DDL(
            f"CREATE TRIGGER {table.name}_no_truncate BEFORE TRUNCATE ON {table.name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION nirikshan_reject_mutation()"
        ).execute_if(dialect="postgresql"),
    )


for _t in PROTECTED:
    _register(_t)


def drop_triggers(session) -> None:
    """Simulate a DB owner removing the protection (used by tamper-detection tests only)."""
    dialect = session.get_bind().dialect.name
    for table in PROTECTED:
        for op in ("update", "delete", "truncate"):
            name = f"{table.name}_no_{op}"
            if dialect == "sqlite":
                session.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
            else:
                session.execute(text(f"DROP TRIGGER IF EXISTS {name} ON {table.name}"))
    session.commit()
