import os
import stat

import pytest

from app import evidence
from app.evidence import AcquisitionError, PathNotAllowed


def _open(path):
    fd, kind, size, resolved = evidence.open_source_readonly(str(path))
    os.close(fd)
    return kind, size, resolved


def test_file_inside_root_allowed(image):
    kind, size, resolved = _open(image)
    assert kind == "file" and resolved == image.resolve()


def test_no_roots_configured_denies_everything(image, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", "")
    with pytest.raises(PathNotAllowed, match="no evidence roots"):
        _open(image)


def test_file_outside_root_rejected(image, tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", str(root))
    with pytest.raises(PathNotAllowed, match="outside"):
        _open(image)


def test_dotdot_traversal_rejected(image, tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", str(root))
    with pytest.raises(PathNotAllowed):
        _open(f"{root}/../{image.name}")


def test_sibling_directory_with_common_prefix_rejected(tmp_path, monkeypatch):
    (tmp_path / "ev").mkdir()
    (tmp_path / "ev2").mkdir()
    f = tmp_path / "ev2" / "x.dd"
    f.write_bytes(b"x")
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", str(tmp_path / "ev"))
    with pytest.raises(PathNotAllowed):
        _open(f)


def test_symlink_inside_root_pointing_outside_rejected(tmp_path, monkeypatch):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.dd").write_bytes(b"s")
    (root / "link.dd").symlink_to(outside / "secret.dd")
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", str(root))
    with pytest.raises(PathNotAllowed):
        _open(root / "link.dd")


def test_symlink_dir_escape_rejected(tmp_path, monkeypatch):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "a.dd").write_bytes(b"s")
    (root / "d").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", str(root))
    with pytest.raises(PathNotAllowed):
        _open(root / "d" / "a.dd")


def test_symlink_staying_inside_root_allowed(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.dd").write_bytes(b"abc")
    (root / "alias.dd").symlink_to(root / "real.dd")
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", str(root))
    assert _open(root / "alias.dd")[2] == (root / "real.dd").resolve()


def test_multiple_roots_pathsep(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (b / "x.dd").write_bytes(b"x")
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", os.pathsep.join([str(a), str(b)]))
    assert _open(b / "x.dd")[0] == "file"


def test_missing_source_is_plain_acquisition_error(tmp_path):
    with pytest.raises(AcquisitionError) as e:
        _open(tmp_path / "nope")
    assert not isinstance(e.value, PathNotAllowed)


def test_block_device_requires_explicit_flag(image, monkeypatch):
    """Mocked S_IFBLK stat on a file-backed fixture; real devices UNVERIFIED."""

    class FakeStat:
        st_mode = stat.S_IFBLK | 0o440
        st_size = 0

    real = os.stat
    monkeypatch.setattr(
        evidence.os,
        "stat",
        lambda p, *a, **k: FakeStat() if str(p) == str(image.resolve()) else real(p),
    )
    with pytest.raises(PathNotAllowed, match="block devices are disabled"):
        _open(image)
    monkeypatch.setenv("NIRIKSHAN_ALLOW_BLOCK_DEVICES", "1")
    assert _open(image)[0] == "block_device"


def test_api_returns_403_for_outside_root(client, image, tmp_path, monkeypatch):
    c = client.post("/api/cases", json={"case_number": "R-1", "title": "t"}).json()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", str(other))
    r = client.post(
        f"/api/cases/{c['id']}/evidence",
        json={"source_path": str(image), "label": "l", "write_blocker": "no"},
    )
    assert r.status_code == 403 and "outside" in r.json()["detail"]
    assert client.get(f"/api/cases/{c['id']}/evidence").json() == []
    s = client.get("/api/system").json()
    assert s["evidence_roots"] == [str(other.resolve())] and s["block_devices_allowed"] is False
