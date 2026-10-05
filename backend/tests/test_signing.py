import stat

import pytest

from app import signing
from app.signing import SigningKeyError


def test_key_generated_once_with_0600_and_reused(tmp_path):
    k1 = signing.public_key_hex()
    path = signing.key_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert signing.public_key_hex() == k1
    assert tmp_path / "keys" == path.parent


def test_sign_verify_and_wrong_message_or_key_fails():
    sig = signing.sign(b"msg")
    pub = signing.public_key()
    assert signing.verify(pub, b"msg", sig)
    assert not signing.verify(pub, b"other", sig)
    assert not signing.verify(pub, b"msg", "zz")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    assert not signing.verify(Ed25519PrivateKey.generate().public_key(), b"msg", sig)


def test_key_dir_inside_data_dir_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NIRIKSHAN_KEY_DIR", str(tmp_path / "data" / "keys"))
    with pytest.raises(SigningKeyError, match="outside"):
        signing.public_key()


def test_loose_key_permissions_are_refused():
    signing.public_key()
    signing.key_path().chmod(0o644)
    with pytest.raises(SigningKeyError, match="chmod 600"):
        signing.public_key()
