import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import cli, schema
from app.models import SchemaMeta


def fresh():
    return create_engine("sqlite://")


def test_fresh_database_is_created_and_stamped():
    e = fresh()
    assert schema.check_and_init(e) == schema.SCHEMA_VERSION
    names = set(inspect(e).get_table_names())
    assert {"schema_meta", "cases", "clips", "custody_entries"} <= names
    with Session(e) as db:
        assert db.get(SchemaMeta, 1).version == schema.SCHEMA_VERSION
    assert schema.check_and_init(e) == schema.SCHEMA_VERSION  # idempotent on a current DB


def test_unversioned_old_database_is_refused_and_left_untouched():
    e = fresh()
    with e.begin() as c:
        c.execute(text("CREATE TABLE cases (id INTEGER PRIMARY KEY, case_number TEXT)"))
        c.execute(text("INSERT INTO cases VALUES (1, 'OLD-1')"))
    with pytest.raises(schema.SchemaError, match="reset-db --yes") as exc:
        schema.check_and_init(e)
    assert "created before versioning" in str(exc.value)
    names = set(inspect(e).get_table_names())
    assert names == {"cases"}  # nothing was created or altered
    with e.connect() as c:
        assert c.execute(text("SELECT case_number FROM cases")).scalar() == "OLD-1"


def test_wrong_version_is_refused():
    e = fresh()
    schema.check_and_init(e)
    with Session(e) as db:
        db.get(SchemaMeta, 1).version = schema.SCHEMA_VERSION - 1
        db.commit()
    with pytest.raises(schema.SchemaError, match=f"found version {schema.SCHEMA_VERSION - 1}"):
        schema.check_and_init(e)


def test_missing_version_row_is_refused():
    e = fresh()
    schema.check_and_init(e)
    with e.begin() as c:
        c.execute(text("DELETE FROM schema_meta"))
    with pytest.raises(schema.SchemaError, match="found version None"):
        schema.check_and_init(e)


def test_reset_recreates_a_clean_current_schema():
    e = fresh()
    with e.begin() as c:
        c.execute(text("CREATE TABLE cases (id INTEGER PRIMARY KEY, legacy TEXT)"))
    schema.reset(e)
    assert schema.check_and_init(e) == schema.SCHEMA_VERSION
    cols = {c["name"] for c in inspect(e).get_columns("cases")}
    assert "case_number" in cols and "legacy" not in cols


def test_app_startup_refuses_an_outdated_database(monkeypatch):
    """The FastAPI lifespan runs the guard: an old database stops the app from starting."""
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app

    old = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with old.begin() as c:
        c.execute(text("CREATE TABLE cases (id INTEGER PRIMARY KEY)"))
    monkeypatch.setattr("app.main.engine", old)
    with pytest.raises(schema.SchemaError):
        with TestClient(app):
            pass
    assert db.engine is not old


def test_cli_reset_requires_confirmation_and_hides_the_password(client, session, capsys):
    from app.models import Case

    session.add(Case(case_number="X", title="t", examiner="e"))
    session.commit()
    assert cli.main(["reset-db"]) == 2
    err = capsys.readouterr().err
    assert (
        "Refusing" in err
        and "DROPS every table" in err
        and "workspaces on disk are not deleted" in err
    )
    assert session.query(Case).count() == 1
    assert cli.main(["reset-db", "--yes"]) == 0
    out = capsys.readouterr().out
    assert f"schema version {schema.SCHEMA_VERSION}" in out and "NOT removed" in out
    session.expire_all()
    assert session.query(Case).count() == 0


def test_system_endpoint_reports_schema_version(client):
    assert client.get("/api/system").json()["schema_version"] == schema.SCHEMA_VERSION
