import json
from datetime import datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from app import custody, signing
from app.custody import GENESIS, compute_hash
from app.models import Case, CustodyEntry
from app.triggers import drop_triggers


@pytest.fixture(autouse=True)
def _db_owner_tampering(session):
    """Tamper tests simulate a DB owner who removed the append-only triggers."""
    drop_triggers(session)


def _case(session):
    c = Case(case_number="C-1", title="t", examiner="e")
    session.add(c)
    session.commit()
    for i in range(4):
        custody.append_entry(session, c.id, "note", "e", {"i": i})
    return c.id


def _rows(session, cid):
    return session.scalars(
        select(CustodyEntry).where(CustodyEntry.case_id == cid).order_by(CustodyEntry.seq)
    ).all()


def _reasons(session, cid):
    return {f["reason"] for f in custody.verify_chain(session, cid)["failures"]}


def test_valid_chain_and_entry_metadata(session):
    cid = _case(session)
    r = custody.verify_chain(session, cid)
    assert r["ok"] and r["entries"] == 4 and r["failures"] == []
    rows = _rows(session, cid)
    assert rows[0].prev_hash == GENESIS and rows[1].prev_hash == rows[0].entry_hash
    e = rows[0]
    assert (
        e.examiner == "e"
        and e.tool_version
        and e.ntp_status in ("synchronized", "not_synchronized", "unknown")
    )
    assert datetime.fromisoformat(e.timestamp_utc).utcoffset().total_seconds() == 0
    assert r["head_hash"] == rows[-1].entry_hash


def test_edited_content_detected(session):
    cid = _case(session)
    row = _rows(session, cid)[1]
    row.details_json = json.dumps({"i": 999})
    session.commit()
    assert "entry_hash does not match entry contents" in _reasons(session, cid)


def test_deleted_middle_entry_detected(session):
    cid = _case(session)
    session.delete(_rows(session, cid)[1])
    session.commit()
    reasons = _reasons(session, cid)
    assert any("sequence gap" in r for r in reasons)
    assert "prev_hash does not match previous entry_hash" in reasons


def test_reordered_entries_detected(session):
    cid = _case(session)
    a, b = _rows(session, cid)[1:3]
    a.seq, b.seq = 99, a.seq
    session.commit()
    a.seq = b.seq + 1  # keep unique
    session.commit()
    assert not custody.verify_chain(session, cid)["ok"]


def test_forged_signature_detected(session):
    cid = _case(session)
    row = _rows(session, cid)[2]
    row.signature = "00" * 64
    session.commit()
    assert _reasons(session, cid) == {"invalid signature"}


def _recompute_chain(session, cid, key=None):
    prev = GENESIS
    for e in _rows(session, cid):
        e.prev_hash = prev
        e.entry_hash = compute_hash(e)
        if key is not None:
            e.signature = key.sign(e.entry_hash.encode()).hex()
        prev = e.entry_hash
    session.commit()


def test_recomputed_chain_without_key_fails_on_signatures_only(session):
    cid = _case(session)
    _rows(session, cid)[1].details_json = json.dumps({"i": "forged"})
    _recompute_chain(session, cid)  # attacker fixes all hashes but cannot sign
    r = custody.verify_chain(session, cid)
    assert not r["ok"]
    assert {f["reason"] for f in r["failures"]} == {"invalid signature"}


def test_recomputed_and_resigned_with_attacker_key_fails_on_key_id(session):
    cid = _case(session)
    _rows(session, cid)[1].details_json = json.dumps({"i": "forged"})
    attacker = Ed25519PrivateKey.generate()
    _recompute_chain(session, cid, attacker)
    for e in _rows(session, cid):
        e.key_id = signing.key_id(attacker.public_key())
    session.commit()
    reasons = _reasons(session, cid)
    assert any(r.startswith("signed with unknown key") for r in reasons)


def test_attacker_key_id_spoof_still_fails_signature(session):
    cid = _case(session)
    _recompute_chain(session, cid, Ed25519PrivateKey.generate())
    kid = signing.key_id(signing.public_key())
    for e in _rows(session, cid):
        e.key_id = kid
    session.commit()
    assert _reasons(session, cid) == {"invalid signature"}


def test_tail_truncation_is_not_detectable_but_head_hash_changes(session):
    cid = _case(session)
    head = custody.verify_chain(session, cid)["head_hash"]
    session.delete(_rows(session, cid)[-1])
    session.commit()
    r = custody.verify_chain(session, cid)
    assert r["ok"] and r["head_hash"] != head  # documented limitation
