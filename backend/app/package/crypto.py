"""Optional passphrase encryption of an evidence package (streamed, chunked AES-256-GCM).

Byte format (docs/package.md "Encrypted container"):

    offset  size  field
    0       8     magic b"NRKPKG01"
    8       1     scrypt log2(N)   (default 17: N = 131072, ~128 MiB, deliberately slow)
    9       1     scrypt r         (8)
    10      1     scrypt p         (1)
    11      16    salt             (random)
    27      7     nonce prefix     (random)
    34      4     chunk size C     (uint32 big-endian, default 1 MiB)
    38      ...   chunks

    key   = scrypt(passphrase, salt, N, r, p, dklen=32)
    chunk i (i = 0, 1, ...): AES-256-GCM(key, nonce_i, plaintext_i, aad=header[0:38])
            = ciphertext_i (len(plaintext_i) bytes) || tag (16 bytes)
    nonce_i = prefix (7) || i as uint32 big-endian (4) || last-flag (1: 0x01 final chunk, else 0x00)
    Every chunk but the last carries exactly C plaintext bytes; the last carries 0..C bytes
    (an empty input is one empty final chunk).

The counter stops reordering, the last-flag stops truncation and extension, the header as AAD
stops parameter tampering. Any failure raises DecryptionError (fail closed); nothing partial is
returned as valid.
"""

from __future__ import annotations

import os
import struct
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.keystore import KeyStoreError, scrypt_key

MAGIC = b"NRKPKG01"
HEADER_LEN = 38
TAG = 16
DEFAULT_LOG2N, R, P = 17, 8, 1
DEFAULT_CHUNK = 1 << 20
MAX_CHUNK = 64 << 20
MIN_PASSPHRASE = 12


class DecryptionError(Exception):
    pass


def is_encrypted(path) -> bool:
    with open(path, "rb") as f:
        return f.read(8) == MAGIC


def _nonce(prefix: bytes, i: int, last: bool) -> bytes:
    if i >= 1 << 32:
        raise ValueError("too many chunks")
    return prefix + struct.pack(">I", i) + (b"\x01" if last else b"\x00")


def encrypt_stream(
    src: BinaryIO,
    dst: BinaryIO,
    passphrase: bytes,
    *,
    log2n: int = DEFAULT_LOG2N,
    chunk: int = DEFAULT_CHUNK,
) -> None:
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(f"package passphrase must be at least {MIN_PASSPHRASE} characters")
    salt, prefix = os.urandom(16), os.urandom(7)
    header = MAGIC + bytes([log2n, R, P]) + salt + prefix + struct.pack(">I", chunk)
    aead = AESGCM(scrypt_key(passphrase, salt, log2n, R, P))
    dst.write(header)
    i = 0
    cur = src.read(chunk)
    while True:
        nxt = src.read(chunk)
        last = not nxt
        dst.write(aead.encrypt(_nonce(prefix, i, last), cur, header))
        if last:
            return
        cur, i = nxt, i + 1


def decrypt_stream(src: BinaryIO, dst: BinaryIO, passphrase: bytes) -> None:
    header = src.read(HEADER_LEN)
    if len(header) != HEADER_LEN or header[:8] != MAGIC:
        raise DecryptionError("not a Nirikshan encrypted package (bad magic)")
    log2n, r, p = header[8], header[9], header[10]
    salt, prefix = header[11:27], header[27:34]
    (chunk,) = struct.unpack(">I", header[34:38])
    if not 1 <= chunk <= MAX_CHUNK:
        raise DecryptionError("invalid chunk size in header")
    try:
        aead = AESGCM(scrypt_key(passphrase, salt, log2n, r, p))
    except KeyStoreError as exc:
        raise DecryptionError(str(exc)) from None
    i = 0
    cur = src.read(chunk + TAG)
    while True:
        if len(cur) < TAG:
            raise DecryptionError("truncated package (missing final chunk)")
        nxt = src.read(chunk + TAG)
        last = not nxt
        if not last and len(cur) != chunk + TAG:
            raise DecryptionError("malformed chunk length")
        try:
            dst.write(aead.decrypt(_nonce(prefix, i, last), cur, header))
        except InvalidTag:
            raise DecryptionError(
                "decryption failed: wrong passphrase, or the file was modified or truncated"
            ) from None
        if last:
            return
        cur, i = nxt, i + 1
