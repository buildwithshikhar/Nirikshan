"""Evidence file picker and browser upload: confinement, limits, custody, roles, public flag."""

import hashlib
import os

import pytest

from tests.auth_support import bearer, login, make_user  # noqa: F401


@pytest.fixture
def roots(tmp_path, monkeypatch):
    root = tmp_path / "ev"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.dd").write_bytes(b"A" * 100)
    (root / "top.img").write_bytes(b"T" * 10)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.dd").write_bytes(b"S")
    os.symlink(outside / "secret.dd", root / "escape.dd")  # symlink escaping the root
    os.symlink(outside, root / "escdir")
    os.symlink(root / "top.img", root / "alias.img")  # symlink staying inside
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", str(root))
    return root


def test_picker_lists_roots_then_folder_and_hides_escapes(client, roots):
    r = client.get("/api/evidence-files").json()
    assert [e["path"] for e in r["entries"]] == [str(roots.resolve())]
    r = client.get("/api/evidence-files", params={"path": str(roots)}).json()
    names = {e["name"] for e in r["entries"]}
    assert {"sub", "top.img", "alias.img"} <= names
    assert "escape.dd" not in names and "escdir" not in names
    assert r["entries"][0]["kind"] == "dir"  # folders first
    sub = client.get("/api/evidence-files", params={"path": str(roots / "sub")}).json()
    assert sub["entries"][0]["name"] == "a.dd" and sub["entries"][0]["size"] == 100
    assert sub["parent"] == str(roots.resolve())


@pytest.mark.parametrize(
    "p", ["/etc", "..", "{root}/../outside", "{root}/escdir", "{root}/sub/../../"]
)
def test_picker_refuses_paths_outside_roots(client, roots, p):
    r = client.get("/api/evidence-files", params={"path": p.format(root=roots)})
    assert r.status_code in (403, 404)


def test_picker_without_roots_says_unavailable(client, monkeypatch):
    monkeypatch.delenv("NIRIKSHAN_EVIDENCE_ROOTS", raising=False)
    assert client.get("/api/evidence-files").json()["available"] is False


def _case(client):
    return client.post(
        "/api/cases", json={"case_number": "UP-1", "title": "t", "description": ""}
    ).json()["id"]


def test_upload_streams_hashes_records_custody_and_is_acquirable(client, roots):
    cid = _case(client)
    data = os.urandom(300_000)
    r = client.post(
        f"/api/cases/{cid}/uploads",
        params={"filename": "orig image.dd"},
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sha256"] == hashlib.sha256(data).hexdigest() and body["size_bytes"] == len(data)
    from pathlib import Path

    stored = Path(body["path"])
    assert stored.parent == roots.resolve() / "incoming" and stored.name.startswith("upload-")
    assert "orig" not in stored.name and stored.read_bytes() == data
    assert oct(stored.parent.stat().st_mode & 0o777) == "0o700"
    entries = client.get(f"/api/cases/{cid}/custody").json()
    e = next(x for x in entries if x["action"] == "file_uploaded_via_browser")
    assert "uploaded via browser" in e["details_json"] and "orig image.dd" in e["details_json"]
    # the stored file can be acquired like any other source (it is inside the evidence roots)
    acq = client.post(
        f"/api/cases/{cid}/evidence",
        json={"source_path": body["path"], "label": "up", "write_blocker": "unknown"},
    )
    assert acq.status_code == 201 and acq.json()["sha256"] == body["sha256"]


@pytest.mark.parametrize("name", ["../x.dd", "a/b.dd", "a\\b.dd", "..", "bad\x00.dd", ""])
def test_upload_rejects_path_tricks(client, roots, name):
    cid = _case(client)
    r = client.post(f"/api/cases/{cid}/uploads", params={"filename": name}, content=b"x")
    assert r.status_code in (400, 422)
    assert not (roots / "incoming").exists() or not list((roots / "incoming").iterdir())


def test_upload_limit_enforced_and_partial_file_removed(client, roots, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_MAX_UPLOAD_BYTES", "1000")
    cid = _case(client)
    r = client.post(f"/api/cases/{cid}/uploads", params={"filename": "big.dd"}, content=b"x" * 5000)
    assert r.status_code == 413
    inc = roots / "incoming"
    assert not inc.exists() or list(inc.iterdir()) == []


def test_upload_empty_refused(client, roots):
    cid = _case(client)
    assert (
        client.post(
            f"/api/cases/{cid}/uploads", params={"filename": "e.dd"}, content=b""
        ).status_code
        == 400
    )


def test_public_instance_disables_uploads_and_block_devices(client, roots, monkeypatch):
    cid = _case(client)
    monkeypatch.setenv("NIRIKSHAN_PUBLIC_INSTANCE", "1")
    monkeypatch.setenv("NIRIKSHAN_ALLOW_BLOCK_DEVICES", "1")
    assert (
        client.post(
            f"/api/cases/{cid}/uploads", params={"filename": "a.dd"}, content=b"x"
        ).status_code
        == 403
    )
    assert client.get("/api/uploads/limits").json()["available"] is False
    caps = client.get("/api/acquisition/capabilities").json()
    assert caps["block_device"]["available"] is False


def test_readonly_role_cannot_upload_or_browse(client, roots, no_dev_auth, session):
    client.headers.pop("X-Examiner", None)
    ex = make_user(session, "exam-one", "examiner")
    ro = make_user(session, "read-one", "readonly")
    ex_h = bearer(login(client, ex.username))
    cid = client.post(
        "/api/cases", json={"case_number": "UP-2", "title": "t", "description": ""}, headers=ex_h
    ).json()["id"]
    from app.auth.access import add_member

    add_member(session, cid, ro, "test")
    ro_h = bearer(login(client, ro.username))
    assert (
        client.post(
            f"/api/cases/{cid}/uploads", params={"filename": "a.dd"}, content=b"x", headers=ro_h
        ).status_code
        == 403
    )
    assert (
        client.get("/api/evidence-files", params={"path": str(roots)}, headers=ro_h).status_code
        == 403
    )
    ok = client.post(
        f"/api/cases/{cid}/uploads", params={"filename": "a.dd"}, content=b"x", headers=ex_h
    )
    assert ok.status_code == 201
