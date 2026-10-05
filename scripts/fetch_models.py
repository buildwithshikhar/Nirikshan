#!/usr/bin/env python3
"""Download the analytics models into backend/models/ and verify their SHA-256.

Run once, with network access, from the repo root or backend/:
    python scripts/fetch_models.py
The application never downloads anything at runtime.
"""

import hashlib
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.analytics.registry import MODELS, models_dir, sha256_file  # noqa: E402


def _ssl_context():
    """System CA bundle, or certifi's when the interpreter has none (python.org macOS builds)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch(spec) -> bool:
    dest = models_dir() / spec.filename
    if dest.is_file() and sha256_file(dest) == spec.sha256:
        print(f"ok (already present): {spec.name} {dest}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    print(f"downloading {spec.name} <- {spec.url}")
    h = hashlib.sha256()
    try:
        resp = urllib.request.urlopen(spec.url, timeout=120, context=_ssl_context())  # noqa: S310
    except urllib.error.URLError as exc:
        print(
            f"download failed ({exc.reason}). On macOS python.org builds run "
            "'Install Certificates.command' or 'pip install certifi'; checksums are still verified."
        )
        return False
    with resp as r, open(tmp, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != spec.sha256:
        tmp.unlink()
        print(f"CHECKSUM MISMATCH for {spec.name}: got {h.hexdigest()}, expected {spec.sha256}")
        return False
    os.replace(tmp, dest)
    print(f"ok: {spec.name} {dest} sha256={spec.sha256} licence={spec.licence}")
    return True


def main() -> int:
    results = [fetch(s) for s in MODELS.values()]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
