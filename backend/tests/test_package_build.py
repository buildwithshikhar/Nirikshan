"""Signed evidence package: contents, determinism, offline verification and tamper detection."""

import io
import json
import zipfile

import pytest
from sqlalchemy import select

from app import cli
from app.models import CustodyEntry
from app.package import build as builder
from app.package import crypto
from app.package.models import Package
from app.package.verify import PackageError, verify_package
from tests.test_analyze import acquire, make_image


@pytest.fixture
def pkg_case(client, streams, tmp_path):
    case = client.post("/api/cases", json={"case_number": "PKG-1", "title": "package"}).json()
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    r = client.post(f"/api/evidence/{ev['id']}/analyze")
    assert r.status_code == 201, r.text
    assert client.post(f"/api/cases/{case['id']}/report").status_code == 201
    return case


def _make(client, case, **body):
    r = client.post(f"/api/cases/{case['id']}/package", json=body or None)
    assert r.status_code == 201, r.text
    return r.json()


def _path(session, pkg):
    return session.get(Package, pkg["id"]).file_path


def test_package_contents_custody_and_verification(client, pkg_case, session, capsys):
    pkg = _make(client, pkg_case)
    path = _path(session, pkg)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
    assert names == sorted(names)
    for required in (
        "README.txt", "SHA256SUMS", "manifest.json", "manifest.sig", "package_public_key.pem",
        "case/evidence.json", "case/clips.csv", "case/runs.json", "export/case.jsonld",
        "export/timeline.csv", "export/timeline.json", "custody/custody_log.json",
        "custody/custody_verification.json", "reports/reports.json",
    ):  # fmt: skip
        assert required in names, required
    assert sum(n.startswith("reports/report_") for n in names) == 1
    assert sum(n.endswith(".mp4") for n in names) == 2  # both carved clips
    # manifest facts
    assert manifest["custody"]["chain_ok"] is True and len(manifest["custody"]["head_hash"]) == 64
    assert manifest["tool_version"] and manifest["parsers"] and manifest["analytics_models"]
    assert "has been validated on a real device" in manifest["data_origin"]["statement"]
    assert {f["path"] for f in manifest["files"]} == set(names) - {"manifest.json", "manifest.sig"}
    # custody entry written after the build, naming the file hash
    last = session.scalars(
        select(CustodyEntry)
        .where(CustodyEntry.case_id == pkg_case["id"])
        .order_by(CustodyEntry.seq.desc())
    ).first()
    assert last.action == "package_created" and pkg["sha256"] in last.details_json
    assert manifest["custody"]["head_hash"] == last.prev_hash
    # download re-hashes, offline verification passes and names the key
    d = client.get(f"/api/packages/{pkg['id']}/download")
    assert d.status_code == 200 and d.headers["content-type"] == "application/zip"
    assert cli.main(["verify-package", path, "--expect-key-id", pkg["key_id"]]) == 0
    out = capsys.readouterr().out
    assert "RESULT: VERIFIED" in out and "OK   reports/report_" in out
    assert client.get("/api/package-key").json()["key_id"] == pkg["key_id"]
    assert client.get(f"/api/cases/{pkg_case['id']}/packages").json()[0]["id"] == pkg["id"]


def test_csv_cells_are_formula_safe():
    assert builder.csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert builder.csv_safe("@x") == "'@x" and builder.csv_safe("-1") == "'-1"
    assert builder.csv_safe(-1) == "-1" and builder.csv_safe("ok") == "ok"


def test_build_is_deterministic(client, pkg_case, session):
    def once():
        buf = io.BytesIO()
        builder.build(
            session, pkg_case["id"], buf, created_at="2026-10-09T00:00:00+00:00",
            created_by="Insp. Test", ntp="unknown",
        )  # fmt: skip
        return buf.getvalue()

    a, b = once(), once()
    assert a == b
    with zipfile.ZipFile(io.BytesIO(a)) as zf:
        assert {i.date_time for i in zf.infolist()} == {builder.ZIP_EPOCH}


def _rewrite(src: str, dst, mutate):
    """Copy a zip, letting mutate(name, data) return new bytes (or None to drop the entry)."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = mutate(info.filename, zin.read(info.filename))
            if data is not None:
                zout.writestr(info, data)
    return dst


def _flip(data: bytes) -> bytes:
    b = bytearray(data or b"\x00")
    b[len(b) // 2] ^= 0x01
    return bytes(b)


def test_tampering_any_file_is_detected_and_named(client, pkg_case, session, tmp_path):
    path = _path(session, _make(client, pkg_case))
    with zipfile.ZipFile(path) as zf:
        payload = [n for n in zf.namelist() if n not in ("manifest.json", "manifest.sig")]
    assert len(payload) > 15
    for name in payload:
        bad = _rewrite(
            path, tmp_path / "bad.zip", lambda n, d, name=name: _flip(d) if n == name else d
        )
        res = verify_package(bad)
        assert not res["ok"], name
        failed = {f["path"] for f in res["failures"]}
        if name == "package_public_key.pem":
            assert name in failed
        else:
            assert failed == {name}, (name, res["failures"])
            assert "SHA-256 mismatch" in res["failures"][0]["reason"]


def test_manifest_signature_added_and_removed_files(client, pkg_case, session, tmp_path):
    path = _path(session, _make(client, pkg_case))

    def edit_manifest(n, d):
        if n != "manifest.json":
            return d
        m = json.loads(d)
        m["created_by"] = "Someone Else"
        return builder.jdump(m)

    res = verify_package(_rewrite(path, tmp_path / "m.zip", edit_manifest))
    assert not res["signature_ok"] and res["failures"][0]["path"] == "manifest.sig"
    res = verify_package(
        _rewrite(path, tmp_path / "s.zip", lambda n, d: _flip(d) if n == "manifest.sig" else d)
    )
    assert not res["ok"] and not res["signature_ok"]
    res = verify_package(
        _rewrite(path, tmp_path / "r.zip", lambda n, d: None if n == "case/clips.csv" else d)
    )
    assert [f["path"] for f in res["failures"]] == ["case/clips.csv"]
    assert "missing" in res["failures"][0]["reason"]
    added = tmp_path / "a.zip"
    _rewrite(path, added, lambda n, d: d)
    with zipfile.ZipFile(added, "a") as zf:
        zf.writestr("extra/evil.txt", b"x")
    res = verify_package(added)
    assert [f["path"] for f in res["failures"]] == ["extra/evil.txt"]


def test_resigned_with_another_key_fails_key_id_check(client, pkg_case, session, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    pkg = _make(client, pkg_case)
    path = _path(session, pkg)
    other = Ed25519PrivateKey.generate()
    raw = other.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    with zipfile.ZipFile(path) as zf:
        m = json.loads(zf.read("manifest.json"))
    m["created_by"] = "Forger"
    m["package_signing_key"]["public_key_hex"] = raw.hex()
    mb = builder.jdump(m)

    def forge(n, d):
        return {"manifest.json": mb, "manifest.sig": other.sign(mb)}.get(n, d)

    forged = _rewrite(path, tmp_path / "f.zip", forge)
    res = verify_package(forged)  # internally consistent signature ...
    assert res["signature_ok"] and not res["ok"]  # ... but the shipped PEM no longer matches
    assert {f["path"] for f in res["failures"]} == {"package_public_key.pem"}
    res = verify_package(forged, expect_key_id=pkg["key_id"])
    assert any("not the expected" in f["reason"] for f in res["failures"])


def test_encrypted_package_fails_closed(client, pkg_case, session, tmp_path, monkeypatch, capsys):
    pp = "a long package passphrase"
    pkg = _make(client, pkg_case, passphrase=pp, include_clips=False)
    path = _path(session, pkg)
    assert pkg["encrypted"] and path.endswith(".zip.nrkenc") and crypto.is_encrypted(path)
    with pytest.raises(PackageError, match="passphrase is required"):
        verify_package(path)
    with pytest.raises(PackageError, match="decryption failed"):
        verify_package(path, passphrase=b"the wrong passphrase")
    res = verify_package(path, passphrase=pp.encode(), expect_key_id=pkg["key_id"])
    assert res["ok"] and res["encrypted"]
    assert not any(f["path"].endswith(".mp4") for f in json.loads(
        zipfile.ZipFile(io.BytesIO(_decrypt(path, pp))).read("manifest.json")
    )["files"])  # fmt: skip
    # CLI: missing passphrase -> exit 2, env passphrase -> 0
    monkeypatch.delenv("NIRIKSHAN_PACKAGE_PASSPHRASE", raising=False)
    assert cli.main(["verify-package", path]) == 2
    monkeypatch.setenv("NIRIKSHAN_PACKAGE_PASSPHRASE", pp)
    assert cli.main(["verify-package", path]) == 0
    # a flipped ciphertext byte anywhere fails closed
    blob = open(path, "rb").read()
    for pos in (20, 40, len(blob) // 2, len(blob) - 1):
        bad = tmp_path / "bad.nrkenc"
        bad.write_bytes(blob[:pos] + bytes([blob[pos] ^ 1]) + blob[pos + 1 :])
        with pytest.raises(PackageError):
            verify_package(bad, passphrase=pp.encode())
    assert (
        client.post(
            f"/api/cases/{pkg_case['id']}/package", json={"passphrase": "short"}
        ).status_code
        == 422
    )


def _decrypt(path, pp) -> bytes:
    out = io.BytesIO()
    with open(path, "rb") as f:
        crypto.decrypt_stream(f, out, pp.encode())
    return out.getvalue()


@pytest.mark.parametrize("size", [0, 1, 99, 100, 101, 1000])
def test_container_roundtrip_and_structure_attacks(size):
    pp = b"container test passphrase"
    data = bytes(range(256)) * 4
    data = data[:size]
    enc = io.BytesIO()
    crypto.encrypt_stream(io.BytesIO(data), enc, pp, log2n=10, chunk=100)
    blob = enc.getvalue()
    out = io.BytesIO()
    crypto.decrypt_stream(io.BytesIO(blob), out, pp)
    assert out.getvalue() == data
    step = 100 + crypto.TAG
    body = blob[crypto.HEADER_LEN :]
    chunks = [body[i : i + step] for i in range(0, len(body), step)]
    attacks = []
    if len(chunks) >= 2:
        attacks.append(blob[: crypto.HEADER_LEN] + b"".join(chunks[:-1]))  # drop final chunk
        attacks.append(blob[: crypto.HEADER_LEN] + chunks[1] + chunks[0] + b"".join(chunks[2:]))
    attacks.append(blob[:8] + bytes([blob[8] + 1]) + blob[9:])  # scrypt cost changed
    attacks.append(blob + chunks[-1])  # extended with a copy of the final chunk
    for bad in attacks:
        with pytest.raises(crypto.DecryptionError):
            crypto.decrypt_stream(io.BytesIO(bad), io.BytesIO(), pp)


def test_download_refuses_modified_package(client, pkg_case, session):
    import os

    pkg = _make(client, pkg_case, include_clips=False)
    path = _path(session, pkg)
    os.chmod(path, 0o644)
    with open(path, "ab") as f:
        f.write(b"x")
    assert client.get(f"/api/packages/{pkg['id']}/download").status_code == 409
