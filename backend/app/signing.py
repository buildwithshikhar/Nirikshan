"""Ed25519 signing key for the custody log.

The private key lives in key_dir() (default ~/.nirikshan/keys), outside every case workspace, and
is generated on first use with mode 0600. Whoever holds this file can forge custody entries; back
it up and protect it separately from case data (see docs/ARCHITECTURE.md).
"""

import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.config import data_dir, key_dir

KEY_FILE = "custody_ed25519.pem"


class SigningKeyError(RuntimeError):
    pass


def _raw(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(pub: Ed25519PublicKey) -> str:
    return hashlib.sha256(_raw(pub)).hexdigest()[:16]


def _load_or_create() -> Ed25519PrivateKey:
    kd, dd = key_dir(), data_dir()
    if kd == dd or dd in kd.parents:
        raise SigningKeyError(f"signing key dir {kd} must be outside the data dir {dd}")
    path = kd / KEY_FILE
    if path.exists():
        if path.stat().st_mode & 0o077:
            raise SigningKeyError(f"{path} must not be accessible by group/others (chmod 600)")
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise SigningKeyError(f"{path} is not an Ed25519 key")
        return key
    kd.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return key


def private_key() -> Ed25519PrivateKey:
    return _load_or_create()


def public_key() -> Ed25519PublicKey:
    return private_key().public_key()


def public_key_hex() -> str:
    return _raw(public_key()).hex()


def sign(message: bytes) -> str:
    return private_key().sign(message).hex()


def verify(pub: Ed25519PublicKey, message: bytes, signature_hex: str) -> bool:
    try:
        pub.verify(bytes.fromhex(signature_hex), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def key_path() -> Path:
    return key_dir() / KEY_FILE
