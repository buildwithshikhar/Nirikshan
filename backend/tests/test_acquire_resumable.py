"""Resumable acquisition, checkpoint verification and bad-sector handling (fault injection)."""

import errno
import hashlib
import json
import os
import stat

import pytest

from app import custody
from app.acquire import resumable
from app.acquire.models import AcquisitionSession
from app.evidence import AcquisitionError
from app.models import Case, CustodyEntry, Evidence
from tests import stream2  # noqa: F401  (mounts routers, registers tables)

CH = resumable.MIN_CHUNK  # 64 KiB


@pytest.fixture
def case_id(session):
    c = Case(case_number="R-1", title="t", examiner="e")
    session.add(c)
    session.commit()
    return c.id


@pytest.fixture
def src(tmp_path):
    p = tmp_path / "disk.dd"
    p.write_bytes(os.urandom(CH * 5 + 777))
    return p


def _start(session, cid, path, **kw):
    return resumable.start(session, cid, str(path), "HDD", "yes", "Insp. Test", chunk_size=CH, **kw)


def _actions(session, cid):
    return [e.action for e in session.query(CustodyEntry).filter_by(case_id=cid).order_by("seq")]


def test_complete_acquisition_hashes_and_checkpoints(session, case_id, src):
    data = src.read_bytes()
    sess = _start(session, case_id, src)
    ev = session.get(Evidence, sess.evidence_id)
    assert sess.status == "completed" and ev.status == "acquired"
    assert ev.sha256 == hashlib.sha256(data).hexdigest()
    assert ev.md5 == hashlib.md5(data).hexdigest()
    assert open(ev.image_path, "rb").read() == data
    assert stat.S_IMODE(os.stat(ev.image_path).st_mode) == 0o444
    hashes = json.loads(sess.chunk_sha256_json)
    assert len(hashes) == 6
    assert hashes[0] == hashlib.sha256(data[:CH]).hexdigest()
    assert json.loads(sess.bad_ranges_json) == []
    entry = session.query(CustodyEntry).filter_by(action="evidence_acquired").one()
    d = json.loads(entry.details_json)
    assert d["zero_filled"] is False and d["resumes"] == 0 and d["sha256"] == ev.sha256
    assert custody.verify_chain(session, case_id)["ok"]


def test_interrupt_then_resume_gives_the_source_hash(session, case_id, src):
    data = src.read_bytes()
    sess = _start(session, case_id, src, stop_after_chunks=2)
    assert sess.status == "interrupted" and sess.bytes_done == 2 * CH
    ev = session.get(Evidence, sess.evidence_id)
    assert ev.status == "acquiring" and ev.sha256 == ""
    sess = resumable.resume(session, sess, "Insp. Test", stop_after_chunks=1)
    assert sess.status == "interrupted" and sess.bytes_done == 3 * CH
    sess = resumable.resume(session, sess, "Insp. Test")
    ev = session.get(Evidence, sess.evidence_id)
    assert sess.status == "completed" and sess.resumes == 2
    assert ev.sha256 == hashlib.sha256(data).hexdigest()
    acts = _actions(session, case_id)
    assert acts.count("acquisition_interrupted") == 2 and acts.count("acquisition_resumed") == 2
    resumed = session.query(CustodyEntry).filter_by(action="acquisition_resumed").first()
    d = json.loads(resumed.details_json)
    assert d["prefix_verified"] is True and d["source_spot_check_chunk"] == 1
    with pytest.raises(resumable.ResumeRefused):
        resumable.resume(session, sess, "Insp. Test")  # completed sessions do not resume


def test_unconfirmed_tail_bytes_are_truncated_on_resume(session, case_id, src):
    data = src.read_bytes()
    sess = _start(session, case_id, src, stop_after_chunks=1)
    with open(sess.partial_path, "ab") as f:  # a crash after write, before the checkpoint
        f.write(b"\xff" * 1000)
    sess = resumable.resume(session, sess, "Insp. Test")
    ev = session.get(Evidence, sess.evidence_id)
    assert ev.sha256 == hashlib.sha256(data).hexdigest()
    d = json.loads(
        session.query(CustodyEntry).filter_by(action="acquisition_resumed").one().details_json
    )
    assert d["truncated_unconfirmed_bytes"] == 1000


def test_resume_refused_when_partial_copy_was_altered(session, case_id, src):
    sess = _start(session, case_id, src, stop_after_chunks=2)
    with open(sess.partial_path, "r+b") as f:
        f.seek(10)
        f.write(b"X")
    with pytest.raises(resumable.ResumeRefused, match="chunk 0"):
        resumable.resume(session, sess, "Insp. Test")
    assert sess.status == "failed"
    assert session.get(Evidence, sess.evidence_id).status == "failed"
    assert "acquisition_resume_refused" in _actions(session, case_id)


def test_resume_refused_when_source_size_changed(session, case_id, src):
    sess = _start(session, case_id, src, stop_after_chunks=2)
    with open(src, "ab") as f:
        f.write(b"more")
    with pytest.raises(resumable.ResumeRefused, match="source changed"):
        resumable.resume(session, sess, "Insp. Test")


def test_resume_refused_when_source_bytes_changed(session, case_id, src):
    sess = _start(session, case_id, src, stop_after_chunks=2)
    raw = bytearray(src.read_bytes())
    raw[CH + 5] ^= 0xFF  # inside the last checkpointed chunk; same size
    src.write_bytes(bytes(raw))
    with pytest.raises(resumable.ResumeRefused, match="re-read differs"):
        resumable.resume(session, sess, "Insp. Test")


class Faulty:
    """Fault injection: raises EIO for any read touching [bad_lo, bad_hi). `transient` makes each
    bad sector fail only on its first read (a retry succeeds)."""

    def __init__(self, bad_lo, bad_hi, transient=False):
        self.lo, self.hi, self.transient = bad_lo, bad_hi, transient
        self.failed: set[int] = set()

    def factory(self, fd, size):
        def read(off, n):
            if off < self.hi and off + n > self.lo:
                key = (off, n)
                if not self.transient or key not in self.failed:
                    self.failed.add(key)
                    raise OSError(errno.EIO, "Input/output error")
            return os.pread(fd, n, off)

        return read


def test_bad_sectors_are_zero_filled_mapped_and_hashed_as_copy(
    session, case_id, src, monkeypatch
):
    data = src.read_bytes()
    lo, hi = CH + 1000, CH + 3000  # sectors 2..5 of chunk 1 (512-byte sectors 1024..3072)
    monkeypatch.setattr(resumable, "READER_FACTORY", Faulty(lo, hi).factory)
    sess = _start(session, case_id, src)
    ev = session.get(Evidence, sess.evidence_id)
    s0, s1 = (lo // 512) * 512, -(-hi // 512) * 512
    assert json.loads(sess.bad_ranges_json) == [[s0, s1, "Input/output error"]]
    expected = data[:s0] + bytes(s1 - s0) + data[s1:]
    copy = open(ev.image_path, "rb").read()
    assert copy == expected
    assert ev.sha256 == hashlib.sha256(expected).hexdigest() != hashlib.sha256(data).hexdigest()
    d = json.loads(
        session.query(CustodyEntry).filter_by(action="evidence_acquired").one().details_json
    )
    assert d["zero_filled"] is True and d["bad_sector_bytes"] == s1 - s0
    assert d["bad_sector_map"] == [[s0, s1, "Input/output error"]]
    assert "zero-filled copy" in d["hash_scope"]
    out = resumable.session_out(sess)["bad_sector_map"]
    assert out["range_count"] == 1 and out["ranges"][0]["bytes"] == s1 - s0


def test_transient_read_error_recovered_by_retry(session, case_id, src, monkeypatch):
    data = src.read_bytes()
    monkeypatch.setattr(
        resumable, "READER_FACTORY", Faulty(2 * CH, 2 * CH + 10, transient=True).factory
    )
    sess = _start(session, case_id, src, retries=1)
    ev = session.get(Evidence, sess.evidence_id)
    assert json.loads(sess.bad_ranges_json) == []
    assert ev.sha256 == hashlib.sha256(data).hexdigest()


def test_no_retries_turns_a_transient_error_into_a_bad_sector(session, case_id, src, monkeypatch):
    monkeypatch.setattr(
        resumable, "READER_FACTORY", Faulty(2 * CH, 2 * CH + 10, transient=True).factory
    )
    sess = _start(session, case_id, src, retries=0)
    # first chunk read fails, then the per-sector read of the first sector also fails once
    assert json.loads(sess.bad_ranges_json) == [[2 * CH, 2 * CH + 512, "Input/output error"]]


def test_resume_skips_spot_check_on_a_chunk_with_read_errors(session, case_id, src, monkeypatch):
    monkeypatch.setattr(resumable, "READER_FACTORY", Faulty(CH + 10, CH + 20).factory)
    sess = _start(session, case_id, src, stop_after_chunks=2)
    sess = resumable.resume(session, sess, "Insp. Test")
    assert sess.status == "completed"
    d = json.loads(
        session.query(CustodyEntry).filter_by(action="acquisition_resumed").one().details_json
    )
    assert d["source_spot_check_chunk"] is None


def test_bad_parameters_rejected(session, case_id, src):
    with pytest.raises(AcquisitionError, match="chunk_size"):
        resumable.start(session, case_id, str(src), "x", "yes", "e", chunk_size=1000)
    with pytest.raises(AcquisitionError, match="retries"):
        resumable.start(session, case_id, str(src), "x", "yes", "e", chunk_size=CH, retries=9)
    assert session.query(AcquisitionSession).count() == 0


# ---- API ------------------------------------------------------------------------------------


def _case(client):
    return client.post("/api/cases", json={"case_number": "RA-1", "title": "resumable"}).json()


def test_api_acquire_bad_sectors_and_capabilities(client, src, monkeypatch):
    c = _case(client)
    monkeypatch.setattr(resumable, "READER_FACTORY", Faulty(0, 600).factory)
    r = client.post(
        f"/api/cases/{c['id']}/acquisitions",
        json={"source_path": str(src), "label": "HDD", "write_blocker": "yes", "chunk_size": CH},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "completed" and body["evidence"]["status"] == "acquired"
    assert body["bad_sector_map"]["ranges"] == [
        {"start": 0, "end": 1024, "bytes": 1024, "error": "Input/output error"}
    ]
    ev_id = body["evidence_id"]
    bs = client.get(f"/api/evidence/{ev_id}/bad-sectors").json()
    assert bs["available"] and bs["zero_filled"] and bs["bytes"] == 1024
    assert client.get(f"/api/acquisitions/{body['id']}").json()["status"] == "completed"
    assert client.post(f"/api/acquisitions/{body['id']}/resume").status_code == 409
    assert len(client.get(f"/api/cases/{c['id']}/acquisitions").json()) == 1
    cap = client.get("/api/acquisition/capabilities").json()
    assert cap["ewf"]["available"] is False and "LGPL" in cap["ewf"]["reason"]
    assert cap["block_device"]["verified_on_real_disks"] is False
    assert client.get("/api/acquisition/ewf").json()["available"] is False


def test_api_single_pass_evidence_has_empty_bad_sector_map(client, src):
    c = _case(client)
    ev = client.post(
        f"/api/cases/{c['id']}/evidence",
        json={"source_path": str(src), "label": "x", "write_blocker": "yes"},
    ).json()
    bs = client.get(f"/api/evidence/{ev['id']}/bad-sectors").json()
    assert bs["available"] and bs["ranges"] == [] and bs["method"] == "single-pass acquisition"


def test_api_rejects_outside_roots_and_bad_chunk(client, src):
    c = _case(client)
    r = client.post(
        f"/api/cases/{c['id']}/acquisitions",
        json={"source_path": "/etc/hosts", "label": "x", "write_blocker": "yes"},
    )
    assert r.status_code == 403
    r = client.post(
        f"/api/cases/{c['id']}/acquisitions",
        json={"source_path": str(src), "label": "x", "write_blocker": "yes", "chunk_size": 7},
    )
    assert r.status_code == 400
