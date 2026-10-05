import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app import analyze as analyze_mod
from app import custody, evidence
from app.carving.export import FfmpegMissing
from app.models import Clip, CustodyEntry, Evidence
from tests import vendor_images as V
from tests.media import filler


def make_image(streams, tmp_path, *, extra_prefix=b"", damage=False):
    """noise | zeros | H.264 clip | zeros | H.265 clip | zeros | noise. Returns (path, truth)."""
    a, b = bytearray(streams["h264_main_b"]), streams["h265_main"]
    if damage:
        a[6000:6600] = filler(600, 77)
    a = bytes(a)
    pre = extra_prefix + filler(40_000, 1)
    img = pre + b"\x00" * 8192 + a + b"\x00" * 8192 + b + b"\x00" * 4096 + filler(9000, 2)
    sa = len(pre) + 8192
    sb = sa + len(a) + 8192
    p = tmp_path / "synthetic_dvr.dd"
    p.write_bytes(img)
    return p, {"a": (sa, sa + len(a), a), "b": (sb, sb + len(b), b)}


@pytest.fixture
def case(client):
    return client.post("/api/cases", json={"case_number": "P2-1", "title": "carve"}).json()


def acquire(client, case, path):
    r = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"source_path": str(path), "label": "synthetic", "write_blocker": "yes"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_analyze_carves_exact_clips_with_hashes_and_custody(
    client, case, streams, tmp_path, session
):
    path, truth = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    r = client.post(f"/api/evidence/{ev['id']}/analyze")
    assert r.status_code == 201, r.text
    run = r.json()
    assert (
        run["status"] == "completed" and run["vendor_matches"] == []
    )  # unknown vendor still carves
    clips = [c for c in run["clips"] if c["kind"] == "clip"]
    assert [c["codec"] for c in clips] == ["h264", "h265"]
    for c, key in zip(clips, "ab", strict=True):
        s, e, raw = truth[key]
        assert (c["start_offset"], c["end_offset"]) == (s, e) and c["size_bytes"] == len(raw)
        assert json.loads(c["extents_json"]) == [[s, e]]
        assert c["bitstream_sha256"] == hashlib.sha256(raw).hexdigest()
        assert c["decode_status"] == "ok" and c["has_video"] and c["packets"] == 50
        row = session.get(Clip, c["id"])
        assert hashlib.sha256(Path(row.mp4_path).read_bytes()).hexdigest() == c["mp4_sha256"]
        assert os.stat(row.mp4_path).st_mode & 0o222 == 0, "exported clips are read-only"
    actions = [e.action for e in session.scalars(select(CustodyEntry).order_by(CustodyEntry.seq))]
    assert actions.count("clip_carved") == 2 and actions[-1] == "carve_completed"
    assert "evidence_verified" in actions[actions.index("evidence_acquired") + 1 :]
    assert custody.verify_chain(session, case["id"])["ok"]
    entry = session.scalars(
        select(CustodyEntry).where(CustodyEntry.action == "clip_carved")
    ).first()
    d = json.loads(entry.details_json)
    assert entry.tool_version and entry.examiner == "Insp. Test" and entry.evidence_id == ev["id"]
    assert d["extents"] and d["bitstream_sha256"] and d["mp4_sha256"] and d["ffmpeg_version"]
    done = json.loads(
        session.scalars(select(CustodyEntry).where(CustodyEntry.action == "carve_completed"))
        .one()
        .details_json
    )
    assert done["counts"]["clips"] == 2 and done["identify_mb_per_s"] and done["carve_mb_per_s"]


def test_carve_reads_only_through_open_verified(client, case, streams, tmp_path, monkeypatch):
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    calls = []
    real = evidence.open_verified

    def spy(db, e, examiner):
        calls.append(e.id)
        return real(db, e, examiner)

    monkeypatch.setattr(analyze_mod, "open_verified", spy)
    assert client.post(f"/api/evidence/{ev['id']}/analyze").status_code == 201
    assert calls == [ev["id"]]


def test_tampered_evidence_blocks_carving_and_is_logged(client, case, streams, tmp_path, session):
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    img = session.get(Evidence, ev["id"]).image_path
    os.chmod(img, 0o644)
    with open(img, "r+b") as f:
        f.seek(100)
        f.write(b"\xff")
    r = client.post(f"/api/evidence/{ev['id']}/analyze")
    assert r.status_code == 409 and "failed verification" in r.json()["detail"]
    assert session.scalars(select(Clip)).all() == []
    runs = client.get(f"/api/evidence/{ev['id']}/runs").json()
    assert runs[0]["status"] == "failed" and "IntegrityError" in runs[0]["error"]
    acts = [e.action for e in session.scalars(select(CustodyEntry).order_by(CustodyEntry.seq))]
    assert acts[-2:] == ["evidence_verified", "carve_failed"]


def test_vendor_signature_reported_with_offsets_and_tier_confidence(
    client, case, streams, tmp_path
):
    hik = V.hikvision(size=1 << 16)
    path, truth = make_image(streams, tmp_path, extra_prefix=hik)
    ev = acquire(client, case, path)
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    m = run["vendor_matches"][0]
    assert (m["vendor"], m["tier"], m["confidence"]) == ("Hikvision", "B", "medium")
    assert any(h["offset"] == 0x200 for h in m["evidence"])
    assert len([c for c in run["clips"] if c["kind"] == "clip"]) == 2


def test_failed_decodes_and_orphans_are_listed_not_hidden(client, case, streams, tmp_path):
    path, _ = make_image(streams, tmp_path, damage=True)
    ev = acquire(client, case, path)
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    bad = [c for c in run["clips"] if c["decode_status"] == "decode_errors"]
    assert bad and json.loads(bad[0]["decode_errors_json"])
    assert run["stats"]["decode_errors"] == len(bad)
    # an IRAP without parameter sets becomes a listed orphan
    units = streams["h264_baseline"]
    idr_only = units[units.index(b"\x65") - 4 :]
    p2 = tmp_path / "orph.dd"
    p2.write_bytes(b"\x00" * 100 + idr_only[:20000])
    ev2 = acquire(client, case, p2)
    run2 = client.post(f"/api/evidence/{ev2['id']}/analyze").json()
    orphans = [c for c in run2["clips"] if c["kind"] == "orphan"]
    assert orphans and "parameter sets" in orphans[0]["reason"] and not orphans[0]["has_video"]


def test_runs_list_and_get_and_params(client, case, streams, tmp_path):
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    r = client.post(f"/api/evidence/{ev['id']}/analyze", json={"max_pad": 32, "join_gap": 1000})
    run = r.json()
    assert run["params"]["max_pad"] == 32 and run["params"]["join_gap"] == 1000
    assert client.get(f"/api/runs/{run['id']}").json()["id"] == run["id"]
    assert [x["id"] for x in client.get(f"/api/evidence/{ev['id']}/runs").json()] == [run["id"]]
    assert client.get("/api/runs/999").status_code == 404
    assert client.post(f"/api/evidence/{ev['id']}/analyze", json={"max_pad": -1}).status_code == 422
    assert client.post("/api/evidence/999/analyze").status_code == 404


def test_missing_ffmpeg_gives_503_and_no_run(client, case, streams, tmp_path, monkeypatch):
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)

    def boom(name):
        raise FfmpegMissing(f"{name} not found on PATH (brew install ffmpeg)")

    monkeypatch.setattr(analyze_mod, "tool", boom)
    r = client.post(f"/api/evidence/{ev['id']}/analyze")
    assert r.status_code == 503 and "brew install ffmpeg" in r.json()["detail"]
    assert client.get(f"/api/evidence/{ev['id']}/runs").json() == []


def test_video_endpoint_serves_playable_bytes_with_range_support(client, case, streams, tmp_path):
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    clip = client.post(f"/api/evidence/{ev['id']}/analyze").json()["clips"][0]
    full = client.get(f"/api/clips/{clip['id']}/video")
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
    assert hashlib.sha256(full.content).hexdigest() == clip["mp4_sha256"]
    part = client.get(f"/api/clips/{clip['id']}/video", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert client.get("/api/clips/999/video").status_code == 404


def test_clip_verify_detects_modified_export(client, case, streams, tmp_path, session):
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    clip = client.post(f"/api/evidence/{ev['id']}/analyze").json()["clips"][0]
    assert client.post(f"/api/clips/{clip['id']}/verify").json()["ok"] is True
    mp4 = session.get(Clip, clip["id"]).mp4_path
    os.chmod(mp4, 0o644)
    with open(mp4, "ab") as f:
        f.write(b"x")
    assert client.post(f"/api/clips/{clip['id']}/verify").json()["ok"] is False
    assert session.scalars(select(CustodyEntry).where(CustodyEntry.action == "clip_verified")).all()


def test_bounded_memory_analysis_of_a_large_sparse_image(client, case, streams, tmp_path):
    """128 MiB image (mostly zeros) with one clip in the middle; checks correctness at size."""
    import tracemalloc

    data = streams["h264_baseline"]
    p = tmp_path / "large.dd"
    with open(p, "wb") as f:
        f.seek(64 * 1024 * 1024)
        f.write(data)
        f.seek(128 * 1024 * 1024 - 1)
        f.write(b"\x00")
    ev = acquire(client, case, p)
    tracemalloc.start()
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    clips = [c for c in run["clips"] if c["kind"] == "clip"]
    assert len(clips) == 1 and clips[0]["start_offset"] == 64 * 1024 * 1024
    assert clips[0]["bitstream_sha256"] == hashlib.sha256(data).hexdigest()
    assert peak < 48 * 1024 * 1024
