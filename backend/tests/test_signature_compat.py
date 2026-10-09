"""Custody signatures created by an OLDER cryptography release must still verify.

tests/fixtures/custody_signature_fixture.json was generated with cryptography 46.0.7 before the
dependency upgrade (see tests/make_custody_fixture.py). The fixed key in it is a public test
constant. Ed25519 signatures are deterministic (RFC 8032), so a re-signature must also match.
"""

import json
from pathlib import Path

import cryptography
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app import custody, signing
from app.models import Case, CustodyEntry

FIX = json.loads(
    (Path(__file__).parent / "fixtures" / "custody_signature_fixture.json").read_text()
)


@pytest.fixture
def fixture_key(monkeypatch, tmp_path):
    kd = tmp_path / "fixturekeys"
    kd.mkdir(mode=0o700)
    p = kd / signing.KEY_FILE
    p.write_text(FIX["private_key_pem"])
    p.chmod(0o600)
    monkeypatch.setenv("NIRIKSHAN_KEY_DIR", str(kd))
    return kd


def test_fixture_was_made_by_an_older_release():
    old = tuple(int(x) for x in FIX["generated_with"].split()[1].split(".")[:2])
    assert old <= tuple(int(x) for x in cryptography.__version__.split(".")[:2]), FIX[
        "generated_with"
    ]


def test_stored_signatures_verify_with_the_current_library(fixture_key):
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(FIX["public_key_hex"]))
    assert signing.key_id(pub) == FIX["key_id"]
    for e in FIX["entries"]:
        assert signing.verify(pub, e["entry_hash"].encode(), e["signature"]), e["seq"]


def test_current_library_reproduces_the_old_signatures(fixture_key):
    key = serialization.load_pem_private_key(FIX["private_key_pem"].encode(), password=None)
    assert isinstance(key, Ed25519PrivateKey)
    for e in FIX["entries"]:
        assert key.sign(e["entry_hash"].encode()).hex() == e["signature"]


def test_whole_stored_chain_verifies_through_verify_chain(client, session, fixture_key):
    session.add(Case(id=1, case_number="FIXTURE-1", title="signature fixture", examiner="fixture"))
    session.commit()
    for e in FIX["entries"]:
        session.add(CustodyEntry(**e))
    session.commit()
    res = custody.verify_chain(session, 1)
    assert res["ok"] and res["entries"] == 3 and res["key_id"] == FIX["key_id"], res


def test_a_flipped_signature_byte_in_the_stored_chain_is_detected(client, session, fixture_key):
    session.add(Case(id=1, case_number="FIXTURE-1", title="signature fixture", examiner="fixture"))
    session.commit()
    for e in FIX["entries"]:
        row = dict(e)
        if row["seq"] == 2:
            sig = row["signature"]
            row["signature"] = ("0" if sig[0] != "0" else "1") + sig[1:]
        session.add(CustodyEntry(**row))
    session.commit()
    res = custody.verify_chain(session, 1)
    assert not res["ok"] and {f["reason"] for f in res["failures"]} == {"invalid signature"}
