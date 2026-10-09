"""Native/standard-export ingest: hashed copy + ffprobe description, no vendor claim."""

import hashlib
import json
import os  # noqa: F401
import random
import subprocess

import pytest

from app.carving.export import find_tool
from tests import stream2  # noqa: F401

FFMPEG = find_tool("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def make(path, vcodec, extra=()):
    subprocess.run(
        [FFMPEG, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=160x120:rate=10", "-t", "1", "-c:v", vcodec, *extra, str(path)],
        check=True,
    )  # fmt: skip
    return path


@pytest.fixture
def case(client):
    return client.post("/api/cases", json={"case_number": "NX-1", "title": "exports"}).json()


@pytest.mark.parametrize(
    "name,vcodec,fmt,codec",
    [
        ("clip.mp4", "libx264", "mov,mp4,m4a,3gp,3g2,mj2", "h264"),
        ("clip.mkv", "libx264", "matroska,webm", "h264"),
        ("clip.avi", "mpeg4", "avi", "mpeg4"),
        ("clip.ts", "libx264", "mpegts", "h264"),
        ("clip.h264", "libx264", "h264", "h264"),  # raw elementary stream (probe score 51)
    ],
)
def test_ingest_standard_exports(client, case, tmp_path, name, vcodec, fmt, codec):
    p = make(tmp_path / name, vcodec)
    r = client.post(
        f"/api/cases/{case['id']}/native-exports",
        json={"source_path": str(p), "label": name, "write_blocker": "unknown"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    ev = body["acquisition"]["evidence"]
    assert ev["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    ne = body["native_export"]
    assert ne["probe_status"] == "recognised" and ne["kind"] == "native_export"
    assert ne["container"]["format_name"] == fmt
    dur = ne["container"]["duration_s"]
    assert dur is None if fmt == "h264" else 0.8 <= dur <= 1.3  # raw streams carry no duration
    v = [s for s in ne["streams"] if s["codec_type"] == "video"][0]
    assert v["codec_name"] == codec and (v["width"], v["height"]) == (160, 120)
    assert ne["vendor_claim"] is None
    again = client.get(f"/api/evidence/{ev['id']}/native-export").json()
    assert again["container"] == ne["container"]
    custody = client.get(f"/api/cases/{case['id']}/custody").json()
    probed = [e for e in custody if e["action"] == "native_export_probed"]
    d = json.loads(probed[0]["details_json"])
    assert d["vendor_claim"].startswith("none") and d["sha256"] == ev["sha256"]


def test_unrecognised_file_stays_acquired_but_flagged(client, case, tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(random.Random(5).randbytes(5000))
    r = client.post(
        f"/api/cases/{case['id']}/native-exports",
        json={"source_path": str(p), "label": "blob"},
    )
    assert r.status_code == 201
    ne = r.json()["native_export"]
    assert ne["probe_status"] == "unrecognised" and ne["probe_error"]
    assert r.json()["acquisition"]["evidence"]["status"] == "acquired"


def test_native_export_absent_for_disk_images(client, case, image):
    ev = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"source_path": str(image), "label": "d", "write_blocker": "yes"},
    ).json()
    r = client.get(f"/api/evidence/{ev['id']}/native-export").json()
    assert r["available"] is False and r["reason"]
