"""Ed25519 signing key for the custody log.

The private key lives in key_dir() (default ~/.nirikshan/keys), outside every case workspace, and
is generated on first use with mode 0600, optionally passphrase-protected (app.keystore,
docs/security/auth.md). Whoever holds this file can forge custody entries; back
it up and protect it separately from case data (see docs/ARCHITECTURE.md).
"""

import hashlib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app import keystore
from app.config import key_dir
from app.keystore import KeyStoreError

KEY_STEM = "custody_ed25519"
KEY_FILE = f"{KEY_STEM}.pem"  # plaintext form; protected form is f"{KEY_STEM}.key.enc"


SigningKeyError = KeyStoreError  # kept for callers/tests that import it from here


def _raw(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(pub: Ed25519PublicKey) -> str:
    return hashlib.sha256(_raw(pub)).hexdigest()[:16]


def _load_or_create() -> Ed25519PrivateKey:
    """Plaintext PEM (default) or passphrase-protected file: see app.keystore."""
    return keystore.load_or_create(KEY_STEM)


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
