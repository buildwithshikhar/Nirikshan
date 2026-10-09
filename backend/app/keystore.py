"""Ed25519 private keys at rest: plaintext PKCS8 PEM (legacy default) or passphrase-protected.

Protected format (`<stem>.key.enc`, 87 bytes, documented in docs/security/auth.md "Keys at rest"):

    offset  size  field
    0       8     magic  b"NRKKEY01"
    8       1     scrypt log2(N)        (default 15, i.e. N = 32768)
    9       1     scrypt r              (default 8)
    10      1     scrypt p              (default 1)
    11      16    salt (random, per file)
    27      12    AES-GCM nonce (random, per file)
    39      48    AES-256-GCM ciphertext of the 32-byte raw Ed25519 private key + 16-byte tag

    key = scrypt(passphrase, salt, N, r, p, dklen=32); AAD = bytes 0..38 (the header), so a
    changed parameter, salt or nonce fails authentication like a changed ciphertext does.

The passphrase comes from NIRIKSHAN_KEY_PASSPHRASE_FILE (preferred: a 0600 file, first line) or
NIRIKSHAN_KEY_PASSPHRASE, or from an interactive prompt in the CLI. It is never logged, stored or
put in an exception message. Decrypted keys are cached in process memory for the life of the
process (the server signs every custody entry; re-deriving scrypt per entry would cost ~0.1 s).
Protection is against a copied key file or backup; it does not protect against anyone who can
read this process's memory or environment (same user / root).
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import data_dir, key_dir

MAGIC = b"NRKKEY01"
HEADER_LEN = 8 + 3 + 16 + 12
KEY_LOG2N, KEY_R, KEY_P = 15, 8, 1
SCRYPT_MAXMEM = 256 * 1024 * 1024


class KeyStoreError(RuntimeError):
    """Raised for every key problem. Messages never contain the passphrase."""


def scrypt_key(passphrase: bytes, salt: bytes, log2n: int, r: int, p: int) -> bytes:
    if not 10 <= log2n <= 22 or not 1 <= r <= 32 or not 1 <= p <= 16:
        raise KeyStoreError("scrypt parameters out of the accepted range")
    return hashlib.scrypt(
        passphrase, salt=salt, n=1 << log2n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=32
    )


def env_passphrase() -> bytes | None:
    """Passphrase from the environment (file first). None when neither variable is set."""
    path = os.getenv("NIRIKSHAN_KEY_PASSPHRASE_FILE", "").strip()
    if path:
        try:
            raw = Path(path).expanduser().read_bytes()
        except OSError as exc:
            raise KeyStoreError(
                f"cannot read NIRIKSHAN_KEY_PASSPHRASE_FILE ({exc.strerror})"
            ) from None
        line = raw.splitlines()[0] if raw else b""
        if not line:
            raise KeyStoreError("NIRIKSHAN_KEY_PASSPHRASE_FILE is empty")
        return line
    val = os.getenv("NIRIKSHAN_KEY_PASSPHRASE")
    if val:
        return val.encode()
    return None


def encrypt_key(key: Ed25519PrivateKey, passphrase: bytes, log2n: int = KEY_LOG2N) -> bytes:
    if not passphrase:
        raise KeyStoreError("empty passphrase")
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + bytes([log2n, KEY_R, KEY_P]) + salt + nonce
    raw = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    k = scrypt_key(passphrase, salt, log2n, KEY_R, KEY_P)
    return header + AESGCM(k).encrypt(nonce, raw, header)


def decrypt_key(blob: bytes, passphrase: bytes) -> Ed25519PrivateKey:
    if len(blob) != HEADER_LEN + 48 or blob[:8] != MAGIC:
        raise KeyStoreError("not a Nirikshan protected key file (bad magic or length)")
    log2n, r, p = blob[8], blob[9], blob[10]
    salt, nonce = blob[11:27], blob[27:39]
    k = scrypt_key(passphrase, salt, log2n, r, p)
    try:
        raw = AESGCM(k).decrypt(nonce, blob[HEADER_LEN:], blob[:HEADER_LEN])
    except InvalidTag:
        raise KeyStoreError("wrong passphrase, or the protected key file was modified") from None
    return Ed25519PrivateKey.from_private_bytes(raw)


_cache: dict[tuple, Ed25519PrivateKey] = {}
_lock = threading.Lock()


def paths(stem: str) -> tuple[Path, Path]:
    kd = key_dir()
    return kd / f"{stem}.pem", kd / f"{stem}.key.enc"


def _check_dirs() -> None:
    kd, dd = key_dir(), data_dir()
    if kd == dd or dd in kd.parents:
        raise KeyStoreError(f"signing key dir {kd} must be outside the data dir {dd}")


def _check_mode(path: Path) -> None:
    if path.stat().st_mode & 0o077:
        raise KeyStoreError(f"{path} must not be accessible by group/others (chmod 600)")


def _write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def load_or_create(stem: str, passphrase: bytes | None = None) -> Ed25519PrivateKey:
    """Load `<stem>` from key_dir(), creating it on first use (protected when a passphrase is
    available, plaintext PEM otherwise). A protected key without a passphrase fails closed."""
    _check_dirs()
    pem_path, enc_path = paths(stem)
    if passphrase is None:
        passphrase = env_passphrase()
    if pem_path.exists() and enc_path.exists():
        raise KeyStoreError(
            f"both {pem_path.name} and {enc_path.name} exist in {pem_path.parent}; remove the "
            "plaintext copy after confirming the protected one loads"
        )
    if enc_path.exists():
        _check_mode(enc_path)
        if not passphrase:
            raise KeyStoreError(
                f"{enc_path} is passphrase-protected; set NIRIKSHAN_KEY_PASSPHRASE_FILE "
                "(or NIRIKSHAN_KEY_PASSPHRASE) to unlock it"
            )
        st = enc_path.stat()
        ck = (
            str(enc_path),
            st.st_ino,
            st.st_mtime_ns,
            st.st_size,
            hashlib.sha256(passphrase).digest(),
        )
        with _lock:
            hit = _cache.get(ck)
        if hit is not None:
            return hit
        key = decrypt_key(enc_path.read_bytes(), passphrase)
        with _lock:
            _cache.clear()  # one live entry per (file, passphrase); old ones are dropped
            _cache[ck] = key
        return key
    if pem_path.exists():
        _check_mode(pem_path)
        key = serialization.load_pem_private_key(pem_path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise KeyStoreError(f"{pem_path} is not an Ed25519 key")
        return key
    key = Ed25519PrivateKey.generate()
    if passphrase:
        _write_exclusive(enc_path, encrypt_key(key, passphrase))
    else:
        _write_exclusive(pem_path, _pem(key))
    return key


def protect(stem: str, passphrase: bytes) -> Path:
    """Convert an existing plaintext PEM to the protected format and remove the PEM. The
    protected file is written and read back (same public key) before the plaintext is unlinked.
    Unlinking does not scrub old disk blocks or backups: see docs/security/auth.md."""
    _check_dirs()
    pem_path, enc_path = paths(stem)
    if enc_path.exists():
        raise KeyStoreError(f"{enc_path} already exists")
    if not pem_path.exists():
        raise KeyStoreError(f"{pem_path} does not exist (nothing to protect)")
    key = load_or_create(stem, passphrase=b"")  # plaintext path only
    _write_exclusive(enc_path, encrypt_key(key, passphrase))
    back = decrypt_key(enc_path.read_bytes(), passphrase)
    raw = serialization.Encoding.Raw, serialization.PublicFormat.Raw
    if back.public_key().public_bytes(*raw) != key.public_key().public_bytes(*raw):
        enc_path.unlink()
        raise KeyStoreError("round-trip check failed; plaintext key left in place")
    pem_path.unlink()
    return enc_path


def status(stem: str) -> dict:
    pem_path, enc_path = paths(stem)
    state = (
        "protected"
        if enc_path.exists()
        else "plaintext"
        if pem_path.exists()
        else "absent (created on first use)"
    )
    return {"key": stem, "state": state, "dir": str(pem_path.parent)}
