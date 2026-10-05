import hashlib
import os
import stat

import pytest

from app import custody, evidence
from app.evidence import AcquisitionError, IntegrityError
from app.models import Case, CustodyEntry, Evidence


@pytest.fixture
def case_id(session):
    c = Case(case_number="E-1", title="t", examiner="e")
    session.add(c)
    session.commit()
    return c.id


def _acquire(session, cid, path, wb="yes"):
    return evidence.acquire(session, cid, str(path), "HDD1", wb, "Insp. Test")


def test_acquire_hashes_copy_and_custody(session, case_id, image):
    data = image.read_bytes()
    ev = _acquire(session, case_id, image, "unknown")
    assert ev.status == "acquired" and ev.source_type == "file"
    assert ev.md5 == hashlib.md5(data).hexdigest()
    assert ev.sha256 == hashlib.sha256(data).hexdigest()
    assert ev.size_bytes == len(data)
    assert open(ev.image_path, "rb").read() == data
    assert stat.S_IMODE(os.stat(ev.image_path).st_mode) == 0o444
    entry = session.query(CustodyEntry).filter_by(action="evidence_acquired").one()
    assert '"write_blocker_used":"unknown"' in entry.details_json
    assert ev.sha256 in entry.details_json and ev.md5 in entry.details_json
    assert custody.verify_chain(session, case_id)["ok"]


def test_source_is_opened_read_only_and_left_untouched(session, case_id, image, monkeypatch):
    before = (image.read_bytes(), image.stat().st_mtime_ns)
    flags = []
    real_open = os.open

    def spy(path, f, *a, **k):
        flags.append((str(path), f))
        return real_open(path, f, *a, **k)

    monkeypatch.setattr(evidence.os, "open", spy)
    _acquire(session, case_id, image)
    src_flags = [f for p, f in flags if p == str(image)]
    assert src_flags and all(f & (os.O_WRONLY | os.O_RDWR | os.O_CREAT) == 0 for f in src_flags)
    assert (image.read_bytes(), image.stat().st_mtime_ns) == before


def test_read_only_source_file_is_acquirable(session, case_id, image):
    image.chmod(0o444)
    assert _acquire(session, case_id, image).status == "acquired"


def test_block_device_path_uses_readonly_open_and_lseek_size(session, case_id, image, monkeypatch):
    """File-backed fixture + mocked S_IFBLK stat. Real-disk acquisition is UNVERIFIED."""
    real_stat = os.stat
    size = image.stat().st_size

    class FakeStat:
        st_mode = stat.S_IFBLK | 0o440
        st_size = 0  # block devices report 0; size must come from lseek

    monkeypatch.setattr(
        evidence.os, "stat", lambda p, *a, **k: FakeStat() if str(p) == str(image) else real_stat(p)
    )
    ev = _acquire(session, case_id, image)
    assert ev.source_type == "block_device" and ev.size_bytes == size


def test_classify_rejects_directories_and_char_devices():
    assert evidence.classify(stat.S_IFREG) == "file"
    for mode in (stat.S_IFDIR, stat.S_IFCHR, stat.S_IFIFO):
        with pytest.raises(AcquisitionError):
            evidence.classify(mode)


def test_missing_and_directory_sources_rejected(session, case_id, tmp_path):
    with pytest.raises(AcquisitionError):
        _acquire(session, case_id, tmp_path / "nope")
    with pytest.raises(AcquisitionError):
        _acquire(session, case_id, tmp_path)
    assert session.query(Evidence).count() == 0


def test_verify_passes_then_detects_single_byte_flip(session, case_id, image):
    ev = _acquire(session, case_id, image)
    assert evidence.verify_evidence(session, ev, "x")["ok"]
    os.chmod(ev.image_path, 0o644)
    with open(ev.image_path, "r+b") as f:  # simulate tampering/bit rot
        f.seek(1000)
        b = f.read(1)
        f.seek(1000)
        f.write(bytes([b[0] ^ 1]))
    res = evidence.verify_evidence(session, ev, "x")
    assert not res["ok"] and res["observed"]["sha256"] != ev.sha256
    assert ev.status == "integrity_failed" and ev.last_verify_ok == 0
    verifies = session.query(CustodyEntry).filter_by(action="evidence_verified").all()
    assert [('"ok":true' in v.details_json) for v in verifies] == [True, False]


def test_verify_reports_missing_image(session, case_id, image):
    ev = _acquire(session, case_id, image)
    os.chmod(ev.image_path, 0o644)
    os.remove(ev.image_path)
    res = evidence.verify_evidence(session, ev, "x")
    assert not res["ok"] and res["error"]


def test_open_verified_gates_analysis_on_integrity(session, case_id, image):
    ev = _acquire(session, case_id, image)
    with evidence.open_verified(session, ev, "x") as f:
        assert f.mode == "rb" and f.read(4) == bytes([0, 1, 2, 3])
    os.chmod(ev.image_path, 0o644)
    with open(ev.image_path, "ab") as f:
        f.write(b"!")
    with pytest.raises(IntegrityError):
        with evidence.open_verified(session, ev, "x"):
            pytest.fail("analysis must not run on a failed image")


def test_failed_acquisition_is_logged_and_leaves_no_image(session, case_id, image, monkeypatch):
    monkeypatch.setattr(evidence, "hash_file", lambda p: evidence.Digests("0" * 32, "0" * 64, 1))
    with pytest.raises(AcquisitionError):
        _acquire(session, case_id, image)
    ev = session.query(Evidence).one()
    assert ev.status == "failed" and not (evidence.image_dir(case_id) / f"{ev.id}.img").exists()
    assert session.query(CustodyEntry).filter_by(action="acquisition_failed").count() == 1


@pytest.mark.skipif(not os.getenv("NIRIKSHAN_BIG_TEST"), reason="opt-in 1 GB run")
def test_one_gib_image(session, case_id, tmp_path):
    p = tmp_path / "big.dd"
    chunk = os.urandom(1024 * 1024)
    h = hashlib.sha256()
    with open(p, "wb") as f:
        for _ in range(1024):
            f.write(chunk)
            h.update(chunk)
    ev = _acquire(session, case_id, p)
    assert ev.size_bytes == 1 << 30 and ev.sha256 == h.hexdigest()
    assert evidence.verify_evidence(session, ev, "x")["ok"]
