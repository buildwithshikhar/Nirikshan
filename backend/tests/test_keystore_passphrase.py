"""Signing keys at rest: optional passphrase protection (scrypt + AES-256-GCM)."""

import pytest

from app import cli, custody, keystore, signing
from app.models import Case


def test_default_is_plaintext_pem_as_before():
    signing.public_key()
    assert keystore.status("custody_ed25519")["state"] == "plaintext"
    assert signing.key_path().exists()


def test_created_protected_when_passphrase_set(monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_KEY_PASSPHRASE", "a long key passphrase")
    pub = signing.public_key_hex()
    pem, enc = keystore.paths("custody_ed25519")
    assert enc.exists() and not pem.exists()
    assert enc.stat().st_mode & 0o777 == 0o600
    blob = enc.read_bytes()
    assert blob[:8] == keystore.MAGIC and len(blob) == keystore.HEADER_LEN + 48
    assert signing.public_key_hex() == pub  # stable across loads


def test_protected_key_fails_closed(monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_KEY_PASSPHRASE", "a long key passphrase")
    signing.public_key()
    monkeypatch.delenv("NIRIKSHAN_KEY_PASSPHRASE")
    with pytest.raises(keystore.KeyStoreError, match="passphrase-protected"):
        signing.public_key()
    monkeypatch.setenv("NIRIKSHAN_KEY_PASSPHRASE", "the wrong passphrase")
    with pytest.raises(keystore.KeyStoreError, match="wrong passphrase") as e:
        signing.public_key()
    assert "the wrong passphrase" not in str(e.value)


def test_tampered_header_or_ciphertext_fails(monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_KEY_PASSPHRASE", "a long key passphrase")
    signing.public_key()
    _, enc = keystore.paths("custody_ed25519")
    good = enc.read_bytes()
    for pos in (12, 30, 50, len(good) - 1):  # salt, nonce, ciphertext, tag
        bad = bytearray(good)
        bad[pos] ^= 1
        with pytest.raises(keystore.KeyStoreError):
            keystore.decrypt_key(bytes(bad), b"a long key passphrase")


def test_passphrase_file_preferred(monkeypatch, tmp_path):
    f = tmp_path / "pp"
    f.write_text("from the file\n")
    monkeypatch.setenv("NIRIKSHAN_KEY_PASSPHRASE_FILE", str(f))
    monkeypatch.setenv("NIRIKSHAN_KEY_PASSPHRASE", "ignored")
    assert keystore.env_passphrase() == b"from the file"


def test_protect_existing_key_keeps_identity_and_chain(session, monkeypatch, capsys):
    c = Case(case_number="K-1", title="t", examiner="e")
    session.add(c)
    session.commit()
    custody.append_entry(session, c.id, "note", "e", {})
    kid = signing.key_id(signing.public_key())
    monkeypatch.setenv("NIRIKSHAN_KEY_PASSPHRASE", "a long key passphrase")
    assert cli.main(["protect-key", "--key", "custody"]) == 0
    assert keystore.status("custody_ed25519")["state"] == "protected"
    assert signing.key_id(signing.public_key()) == kid
    custody.append_entry(session, c.id, "note2", "e", {})
    assert custody.verify_chain(session, c.id)["ok"]
    assert cli.main(["key-status"]) == 0
    assert "protected" in capsys.readouterr().out


def test_both_forms_present_is_refused(monkeypatch):
    signing.public_key()
    pem, enc = keystore.paths("custody_ed25519")
    enc.write_bytes(b"x")
    enc.chmod(0o600)
    with pytest.raises(keystore.KeyStoreError, match="both"):
        signing.public_key()
