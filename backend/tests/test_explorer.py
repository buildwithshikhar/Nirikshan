"""Storage explorer: bounded hex reads, partition/FS signatures, region map, anomalies."""

import io
import os
import struct
import uuid
import zlib

import pytest

from app.carving.export import find_tool
from app.explorer import partitions, regions
from app.explorer.models import RawReadAudit
from app.models import CustodyEntry, Evidence
from app.validation import layouts_honeywell as H
from app.validation.streams import StreamPool
from tests import stream2  # noqa: F401


@pytest.fixture(scope="module")
def pool():
    return StreamPool()


@pytest.fixture
def case(client):
    return client.post("/api/cases", json={"case_number": "EX-1", "title": "explorer"}).json()


def acquire(client, case, path):
    r = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"source_path": str(path), "label": "x", "write_blocker": "yes"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---- hex ------------------------------------------------------------------------------------


def test_hex_read_is_bounded_audited_and_not_custody_logged(client, case, image, session):
    ev = acquire(client, case, image)
    before = session.query(CustodyEntry).count()
    r = client.get(f"/api/evidence/{ev['id']}/hex?offset=16&length=32").json()
    assert r["hex"] == bytes(range(16, 48)).hex() and r["length"] == 32
    assert r["ascii"][:16] == "................"
    assert r["integrity"]["last_full_verification"]
    tail = client.get(f"/api/evidence/{ev['id']}/hex?offset={ev['size_bytes'] - 2}&length=100")
    assert tail.json()["length"] == 2 and bytes.fromhex(tail.json()["hex"]) == b"il"
    assert client.get(f"/api/evidence/{ev['id']}/hex?length=4097").status_code == 422
    assert client.get(f"/api/evidence/{ev['id']}/hex?offset=-1").status_code == 422
    assert client.get(f"/api/evidence/{ev['id']}/hex?offset={ev['size_bytes']}").status_code == 416
    rows = session.query(RawReadAudit).all()
    assert [(a.offset, a.length) for a in rows] == [(16, 32), (ev["size_bytes"] - 2, 2)]
    assert session.query(CustodyEntry).count() == before  # no custody entry per read


def test_hex_integrity_gate(client, case, image, session):
    ev = acquire(client, case, image)
    row = session.get(Evidence, ev["id"])
    os.chmod(row.image_path, 0o644)
    assert client.get(f"/api/evidence/{ev['id']}/hex").status_code == 409
    os.chmod(row.image_path, 0o444)
    assert client.get(f"/api/evidence/{ev['id']}/hex").status_code == 200
    row.last_verify_ok = 0
    session.commit()
    r = client.get(f"/api/evidence/{ev['id']}/hex")
    assert r.status_code == 409 and "verification" in r.json()["detail"]
    assert client.get("/api/evidence/999/hex").status_code == 404


# ---- partitions -----------------------------------------------------------------------------


def mbr_image() -> bytes:
    img = bytearray(4 << 20)

    def entry(i, status, ptype, lba, n):  # noqa: E306
        struct.pack_into(
            "<B3sB3sII", img, 446 + 16 * i, status, b"\0" * 3, ptype, b"\0" * 3, lba, n
        )

    entry(0, 0x80, 0x83, 2048, 2048)  # Linux, ext superblock below
    entry(1, 0x00, 0x07, 4096, 2048)  # NTFS
    entry(2, 0x00, 0x0C, 5000, 100)  # overlaps entry 1
    img[510:512] = b"\x55\xaa"
    p1 = 2048 * 512
    img[p1 + 1080 : p1 + 1082] = b"\x53\xef"
    struct.pack_into("<I", img, p1 + 1024 + 0x18, 2)  # 4096-byte blocks
    p2 = 4096 * 512
    img[p2 + 3 : p2 + 11] = b"NTFS    "
    img[p2 + 510 : p2 + 512] = b"\x55\xaa"
    return bytes(img)


def test_mbr_partitions_and_filesystem_signatures():
    data = mbr_image()
    r = partitions.detect(io.BytesIO(data), len(data))
    assert r["scheme"] == "mbr"
    parts = r["mbr"]["partitions"]
    assert [(p["type"], p["start_offset"]) for p in parts] == [
        ("0x83", 2048 * 512),
        ("0x07", 4096 * 512),
        ("0x0C", 5000 * 512),
    ]
    fs = {(f["fs"], f["partition_start"]) for f in r["filesystems"]}
    assert ("ext2/3/4", 2048 * 512) in fs and ("NTFS", 4096 * 512) in fs
    ext = next(f for f in r["filesystems"] if f["fs"] == "ext2/3/4")
    assert ext["offset"] == 2048 * 512 + 1080 and "4096" in ext["note"]
    kinds = {a["kind"] for a in r["anomalies"]}
    assert "mbr_partitions_overlap" in kinds


def gpt_image(corrupt_header=False, corrupt_entries=False) -> bytes:
    img = bytearray(1 << 20)
    img[510:512] = b"\x55\xaa"
    img[446 + 4] = 0xEE
    struct.pack_into("<II", img, 446 + 8, 1, 2047)
    ent = bytearray(128 * 128)
    t = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4").bytes_le
    ent[0:16] = t
    ent[16:32] = uuid.uuid4().bytes_le
    struct.pack_into("<QQQ", ent, 32, 64, 1000, 0)
    ent[56 : 56 + 8] = "data".encode("utf-16-le")
    img[1024 : 1024 + len(ent)] = ent
    h = bytearray(92)
    h[:8] = b"EFI PART"
    struct.pack_into("<II", h, 8, 0x10000, 92)
    struct.pack_into("<QQQQ", h, 24, 1, 2047, 34, 2014)
    h[56:72] = uuid.uuid4().bytes_le
    crc_e = zlib.crc32(bytes(ent)) ^ (1 if corrupt_entries else 0)
    struct.pack_into("<QIII", h, 72, 2, 128, 128, crc_e)
    struct.pack_into("<I", h, 16, zlib.crc32(bytes(h)) ^ (1 if corrupt_header else 0))
    img[512 : 512 + 92] = h
    img[64 * 512 + 1080 : 64 * 512 + 1082] = b"\x53\xef"
    return bytes(img)


def test_gpt_header_entries_crc_and_fs():
    data = gpt_image()
    r = partitions.detect(io.BytesIO(data), len(data))
    assert r["scheme"] == "gpt" and r["mbr"]["protective"]
    g = r["gpt"]
    assert g["header"]["header_crc32_ok"] and g["sector_size"] == 512
    (p,) = g["partitions"]
    assert p["type_name"] == "Linux filesystem data" and p["name"] == "data"
    assert (p["start_offset"], p["end_offset"]) == (64 * 512, 1001 * 512)
    assert [f["fs"] for f in r["filesystems"]] == ["ext2/3/4"]
    kinds = {a["kind"] for a in r["anomalies"]}
    assert "gpt_header_crc_mismatch" not in kinds and "gpt_entries_crc_mismatch" not in kinds
    assert "gpt_backup_header_missing" in kinds  # AlternateLBA 2047 points inside: absent


def test_gpt_crc_mismatches_are_anomalies():
    for kw, kind in (
        ({"corrupt_header": True}, "gpt_header_crc_mismatch"),
        ({"corrupt_entries": True}, "gpt_entries_crc_mismatch"),
    ):
        data = gpt_image(**kw)
        r = partitions.detect(io.BytesIO(data), len(data))
        assert kind in {a["kind"] for a in r["anomalies"]}


def test_no_partition_table_on_random_data():
    data = os.urandom(1 << 16)
    r = partitions.detect(io.BytesIO(data), len(data))
    assert r["scheme"] == "none detected" and r["mbr"] is None and r["gpt"] is None


# ---- region map (unit) ----------------------------------------------------------------------


def test_region_precedence_zero_unknown_and_not_scanned():
    size = 64 * 1024
    iv = [
        (4096, 12288, "carved_clip", {"clip_id": 1}),
        (8192, 9000, "structure", {"s": 1}),  # inside the clip: the clip wins
        (20000, 21000, "orphan", {"clip_id": 2}),
    ]
    zeros = [(0, 4096), (24576, 32768)]
    regs = regions.build(iv, size, zeros, scanned_end=40960)
    assert regs[0] == (0, 4096, "zero", {})
    assert regs[1] == (4096, 12288, "carved_clip", {"clip_id": 1})
    kinds = [k for _, _, k, _ in regs]
    assert kinds == ["zero", "carved_clip", "unknown", "orphan", "unknown", "zero", "unknown",
                     "not_scanned"]  # fmt: skip
    assert regs[0][0] == 0 and regs[-1][1] == size
    assert all(a[1] == b[0] for a, b in zip(regs, regs[1:], strict=False))  # contiguous


def test_zero_blocks_bounded_scan():
    data = bytes(8192) + b"x" * 4096 + bytes(4096)
    zeros, end = regions.zero_blocks(io.BytesIO(data), len(data), budget=12288)
    assert zeros == [(0, 8192)] and end == 12288


# ---- region map and anomalies over a real analysis run (needs ffmpeg) -----------------------


@pytest.mark.skipif(find_tool("ffmpeg") is None, reason="ffmpeg not installed")
def test_regions_and_anomalies_from_an_analysis_run(client, case, tmp_path, pool):
    img, _clips, _ = H.build_image(H._chunks([pool.get("h264_base_320")], [True]))
    p = tmp_path / "hw.img"
    p.write_bytes(bytes(img))
    ev = acquire(client, case, p)
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    assert run["status"] == "completed"
    r = client.get(f"/api/evidence/{ev['id']}/regions?scan_bytes=1048576").json()
    assert r["run_id"] == run["id"]
    regs = r["regions"]
    assert regs[0]["start"] == 0 and regs[-1]["end"] == ev["size_bytes"] and not r["truncated"]
    assert all(a["end"] == b["start"] for a, b in zip(regs, regs[1:], strict=False))
    kinds = set(r["summary"])
    assert {"parser_clip", "structure", "not_scanned"} <= kinds
    assert sum(v["bytes"] for v in r["summary"].values()) == ev["size_bytes"]
    gpt = [
        x for x in regs if x["kind"] == "structure" and x["ref"].get("structure") == "GPT header"
    ]
    assert gpt and gpt[0]["start"] == 512
    small = client.get(f"/api/evidence/{ev['id']}/regions?max_regions=1").json()
    assert small["truncated"] and len(small["regions"]) == 1
    a = client.get(f"/api/evidence/{ev['id']}/anomalies").json()
    assert a["run_id"] == run["id"]
    kinds = {x["kind"] for x in a["anomalies"]}
    assert "gpt_partition_beyond_image" in kinds  # partition 2 lies outside the test image
    assert all(x["severity"] in ("info", "warning") for x in a["anomalies"])
    pt = client.get(f"/api/evidence/{ev['id']}/partitions").json()
    assert pt["scheme"] == "gpt" and len(pt["gpt"]["partitions"]) == 2


def test_regions_without_run(client, case, image):
    ev = acquire(client, case, image)
    r = client.get(f"/api/evidence/{ev['id']}/regions").json()
    assert r["run_id"] is None and any("no completed analysis run" in n for n in r["notes"])
    assert set(r["summary"]) <= {"unknown", "zero", "not_scanned"}
    assert client.get(f"/api/evidence/{ev['id']}/anomalies").json()["count"] == 0
