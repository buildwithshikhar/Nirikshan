"""Offline package verification: no database, no network, no Nirikshan keys needed.

Checks, in order (each failure is reported with the file it concerns):
1. encrypted container: passphrase present and correct (else PackageError: fail closed);
2. zip structure: readable, no duplicate names, no absolute or '..' paths;
3. manifest.json and manifest.sig present; the Ed25519 signature over the exact manifest bytes
   verifies with the public key named in the manifest, and package_public_key.pem is that key;
4. optional --expect-key-id: the signing key is the one recorded outside the package;
5. every file listed in the manifest is present with the listed size and SHA-256;
6. no file is present that the manifest does not list.
A valid signature with an unexpected key only shows internal consistency: anyone can re-sign a
modified package with their own key, which is why the key id must be compared (README.txt).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.package import crypto

MANIFEST, SIGNATURE, PUBKEY = "manifest.json", "manifest.sig", "package_public_key.pem"


class PackageError(Exception):
    """The package cannot be checked at all (unreadable, encrypted without passphrase, ...)."""


def _key_id(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def _hash_member(zf: zipfile.ZipFile, name: str) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with zf.open(name) as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def verify_package(
    path: str | Path,
    *,
    passphrase: bytes | None = None,
    ask_passphrase: Callable[[], bytes] | None = None,
    expect_key_id: str | None = None,
) -> dict:
    path = Path(path)
    if not path.is_file():
        raise PackageError(f"{path}: no such file")
    encrypted = crypto.is_encrypted(path)
    tmp = None
    try:
        target = path
        if encrypted:
            if not passphrase and ask_passphrase is not None:
                passphrase = ask_passphrase()
            if not passphrase:
                raise PackageError(
                    "encrypted package: a passphrase is required (NIRIKSHAN_PACKAGE_PASSPHRASE "
                    "or an interactive prompt); nothing was verified"
                )
            fd, tmp = tempfile.mkstemp(prefix="nrkpkg-", suffix=".zip")
            os.chmod(tmp, 0o600)
            try:
                with open(path, "rb") as src, os.fdopen(fd, "wb") as dst:
                    crypto.decrypt_stream(src, dst, passphrase)
            except crypto.DecryptionError as exc:
                raise PackageError(str(exc)) from None
            target = Path(tmp)
        return _verify_zip(target, encrypted, expect_key_id)
    finally:
        if tmp is not None:
            Path(tmp).unlink(missing_ok=True)


def _verify_zip(path: Path, encrypted: bool, expect_key_id: str | None) -> dict:
    failures: list[dict] = []
    lines: list[str] = []

    def fail(p: str, reason: str) -> None:
        failures.append({"path": p, "reason": reason})
        lines.append(f"FAIL {p}: {reason}")

    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PackageError(f"not a readable zip package ({exc})") from None
    with zf:
        names = [i.filename for i in zf.infolist()]
        for n in sorted({n for n in names if names.count(n) > 1}):
            fail(n, "duplicate entry name in the zip")
        for n in names:
            if n.startswith("/") or ".." in Path(n).parts or "\\" in n:
                fail(n, "unsafe path in the zip")
        if MANIFEST not in names or SIGNATURE not in names:
            raise PackageError("manifest.json or manifest.sig is missing; nothing can be verified")
        mbytes = zf.read(MANIFEST)
        sig = zf.read(SIGNATURE)
        try:
            manifest = json.loads(mbytes)
            key_hex = manifest["package_signing_key"]["public_key_hex"]
            raw = bytes.fromhex(key_hex)
            pub = Ed25519PublicKey.from_public_bytes(raw)
        except (ValueError, KeyError, TypeError) as exc:
            raise PackageError(f"manifest.json is not a valid package manifest ({exc})") from None
        kid = _key_id(raw)
        try:
            pub.verify(sig, mbytes)
            sig_ok = True
            lines.append(f"OK   {SIGNATURE}: Ed25519 signature over {MANIFEST} (key_id {kid})")
        except InvalidSignature:
            sig_ok = False
            fail(SIGNATURE, f"signature does not verify over {MANIFEST} (key_id {kid})")
        if PUBKEY in names:
            try:
                pem_key = serialization.load_pem_public_key(zf.read(PUBKEY))
                pem_raw = pem_key.public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                )
                if pem_raw != raw:
                    fail(PUBKEY, "differs from the key named in manifest.json")
            except ValueError:
                fail(PUBKEY, "not a readable public key")
        key_match = None
        if expect_key_id:
            key_match = expect_key_id.strip().lower() == kid
            if key_match:
                lines.append(f"OK   signing key id matches the expected {kid}")
            else:
                fail(SIGNATURE, f"signing key id {kid} is not the expected {expect_key_id}")
        else:
            lines.append(
                f"NOTE signing key id {kid}: compare it with the id recorded outside the package"
            )
        listed = {}
        for f in manifest.get("files", []):
            listed[f["path"]] = f
        present = set(names) - {MANIFEST, SIGNATURE}
        for p in sorted(listed):
            f = listed[p]
            if p not in present:
                fail(p, "listed in the manifest but missing from the package")
                continue
            sha, size = _hash_member(zf, p)
            if sha != f["sha256"]:
                fail(p, f"SHA-256 mismatch (manifest {f['sha256']}, file {sha})")
            elif size != f["size"]:
                fail(p, f"size mismatch (manifest {f['size']}, file {size})")
            else:
                lines.append(f"OK   {p}")
        for p in sorted(present - set(listed)):
            fail(p, "present in the package but not listed in the manifest")
    return {
        "ok": not failures,
        "encrypted": encrypted,
        "signature_ok": sig_ok,
        "key_id": kid,
        "key_id_matches_expected": key_match,
        "files_listed": len(listed),
        "failures": failures,
        "lines": lines,
        "case_number": manifest.get("case", {}).get("case_number"),
        "custody_head_hash": manifest.get("custody", {}).get("head_hash"),
        "created_at": manifest.get("created_at"),
        "data_origin": manifest.get("data_origin", {}).get("statement"),
    }
