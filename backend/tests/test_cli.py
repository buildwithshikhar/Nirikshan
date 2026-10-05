import json

from app import cli, custody
from app.models import Case


def _case(session):
    c = Case(case_number="CLI-1", title="t", examiner="e")
    session.add(c)
    session.commit()
    custody.append_entry(session, c.id, "note", "e", {})
    return c.id


def test_head_prints_hash_and_exits_zero(session, capsys):
    cid = _case(session)
    expected = custody.verify_chain(session, cid)["head_hash"]
    assert cli.main(["head", str(cid)]) == 0
    out = capsys.readouterr().out
    assert expected in out and "VALID" in out and "outside this system" in out


def test_head_json_output(session, capsys):
    cid = _case(session)
    assert cli.main(["head", str(cid), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["entries"] == 1 and len(data["head_hash"]) == 64


def test_head_exits_nonzero_on_invalid_chain(session, capsys):
    from sqlalchemy import text

    from app.triggers import drop_triggers

    cid = _case(session)
    drop_triggers(session)
    session.execute(text("UPDATE custody_entries SET examiner='x'"))
    session.commit()
    assert cli.main(["head", str(cid)]) == 1
    assert "INVALID" in capsys.readouterr().out


def test_head_unknown_case(session, capsys):
    assert cli.main(["head", "999"]) == 2
