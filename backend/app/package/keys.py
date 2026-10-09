"""Package signing key: a separate Ed25519 key (key_dir()/package_ed25519.*), stored like the
custody key (plaintext PEM by default, optionally passphrase-protected: app.keystore). Kept
separate so a package key can be handed to a different custodian or rotated without touching
the custody chain."""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import keystore, signing

STEM = "package_ed25519"


def private_key() -> Ed25519PrivateKey:
    return keystore.load_or_create(STEM)


def public_key_hex() -> str:
    return (
        private_key()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )


def public_key_pem() -> bytes:
    return (
        private_key()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )


def key_id() -> str:
    return signing.key_id(private_key().public_key())


def sign(message: bytes) -> bytes:
    return private_key().sign(message)
