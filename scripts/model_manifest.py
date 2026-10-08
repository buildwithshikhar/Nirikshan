#!/usr/bin/env python3
"""Write or verify a SHA-256 manifest for the analytics models (air-gapped transfer).

    python scripts/model_manifest.py write  [--dir backend/models] [--out backend/models/SHA256SUMS]
    python scripts/model_manifest.py verify [--dir backend/models] [--manifest .../SHA256SUMS]

The manifest uses the `sha256sum` format ("<hex>  <filename>"), so on the target machine
`cd models && sha256sum -c SHA256SUMS` works without Python. `verify` additionally compares
every file against the checksum pinned in app/analytics/registry.py, so a manifest that was
altered together with its files still fails. Exit 0 = all good, 1 = mismatch or missing file.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pinned() -> dict[str, str]:
    """filename -> SHA-256 pinned in the code (the single source of truth)."""
    from app.analytics.registry import MODELS

    return {spec.filename: spec.sha256 for spec in MODELS.values()}


def cmd_write(dirpath: Path, out: Path) -> int:
    files = sorted(p for p in dirpath.glob("*.onnx") if p.is_file())
    if not files:
        print(f"no .onnx files in {dirpath}; run scripts/fetch_models.py first", file=sys.stderr)
        return 1
    lines = [f"{sha256_file(p)}  {p.name}" for p in files]
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out} ({len(lines)} files)")
    return 0


def cmd_verify(dirpath: Path, manifest: Path) -> int:
    if not manifest.is_file():
        print(f"manifest not found: {manifest}", file=sys.stderr)
        return 1
    expected_code = pinned()
    listed: dict[str, str] = {}
    for line in manifest.read_text().splitlines():
        if line.strip():
            digest, _, name = line.partition("  ")
            listed[name.strip()] = digest.strip().lower()
    ok = True
    for name, digest in sorted(listed.items()):
        p = dirpath / name
        if not p.is_file():
            print(f"MISSING  {name}")
            ok = False
            continue
        got = sha256_file(p)
        if got != digest:
            print(f"FAILED   {name}: file {got} != manifest {digest}")
            ok = False
        elif name in expected_code and expected_code[name] != got:
            print(f"FAILED   {name}: file {got} != pinned in registry.py {expected_code[name]}")
            ok = False
        else:
            print(f"OK       {name} {got}")
    for name in sorted(set(expected_code) - set(listed)):
        print(f"NOT LISTED  {name} (pinned in registry.py but absent from the manifest)")
        ok = False
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_dir = ROOT / "backend" / "models"
    w = sub.add_parser("write")
    w.add_argument("--dir", type=Path, default=default_dir)
    w.add_argument("--out", type=Path, default=default_dir / "SHA256SUMS")
    v = sub.add_parser("verify")
    v.add_argument("--dir", type=Path, default=default_dir)
    v.add_argument("--manifest", type=Path, default=default_dir / "SHA256SUMS")
    a = ap.parse_args()
    if a.cmd == "write":
        return cmd_write(a.dir, a.out)
    return cmd_verify(a.dir, a.manifest)


if __name__ == "__main__":
    sys.exit(main())
