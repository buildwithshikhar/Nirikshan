"""Single-pass MD5 + SHA-256."""

import hashlib
from dataclasses import dataclass
from typing import BinaryIO

CHUNK = 4 * 1024 * 1024


@dataclass(frozen=True)
class Digests:
    md5: str
    sha256: str
    size: int


def hash_stream(src: BinaryIO, sink: BinaryIO | None = None) -> Digests:
    """Read src to EOF once, updating both digests; optionally write the same bytes to sink."""
    md5, sha = hashlib.md5(usedforsecurity=False), hashlib.sha256()
    size = 0
    while chunk := src.read(CHUNK):
        md5.update(chunk)
        sha.update(chunk)
        size += len(chunk)
        if sink is not None:
            sink.write(chunk)
    return Digests(md5.hexdigest(), sha.hexdigest(), size)


def hash_file(path) -> Digests:
    with open(path, "rb") as f:
        return hash_stream(f)
