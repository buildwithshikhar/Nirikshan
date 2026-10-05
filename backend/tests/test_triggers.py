import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import custody
from app.models import AuditEntry, Case
from app.triggers import drop_triggers


@pytest.fixture
def seeded(client, session):
    c = Case(case_number="T-1", title="t", examiner="e")
    session.add(c)
    session.commit()
    custody.append_entry(session, c.id, "note", "e", {})
    client.get("/api/cases")  # produces an audit row
    assert session.query(AuditEntry).count() >= 1
    return c.id


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE custody_entries SET examiner='x'",
        "DELETE FROM custody_entries",
        "UPDATE audit_log SET examiner='x'",
        "DELETE FROM audit_log",
    ],
)
def test_direct_sql_changes_are_rejected(session, seeded, sql):
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text(sql))
        session.commit()
    session.rollback()
    assert session.execute(text("SELECT count(*) FROM custody_entries")).scalar() >= 1


def test_orm_update_and_delete_are_rejected(session, seeded):
    from app.models import CustodyEntry

    row = session.query(CustodyEntry).first()
    row.examiner = "tampered"
    with pytest.raises(DBAPIError):
        session.commit()
    session.rollback()
    session.delete(session.query(CustodyEntry).first())
    with pytest.raises(DBAPIError):
        session.commit()
    session.rollback()


def test_inserts_still_work_and_chain_stays_valid(session, seeded):
    custody.append_entry(session, seeded, "note2", "e", {})
    assert custody.verify_chain(session, seeded)["ok"]


def test_chain_detects_tampering_once_triggers_are_dropped(session, seeded):
    """Triggers are a speed bump, not the integrity guarantee: an owner can drop them."""
    drop_triggers(session)
    session.execute(text("UPDATE custody_entries SET examiner='x'"))
    session.commit()
    assert not custody.verify_chain(session, seeded)["ok"]
