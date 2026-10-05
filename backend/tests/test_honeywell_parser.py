"""Honeywell structured-parser tests.

The test images come from app.validation.layouts_honeywell, which is written from the SAME field
doc as the parser. Passing here is therefore a circular consistency check, not validation against
a real device. Corruption/fuzz tests check robustness, not correctness against hardware.
"""

import io
import json
import random
import struct
import zlib
from datetime import datetime, timezone

import pytest

from app import analyze as analyze_mod
from app.carving import nal
from app.carving.carve import CarveParams, Carver
from app.validation import layouts_honeywell as H
from app.validation.streams import StreamPool
from app.vendors import honeywell_fs
from app.vendors.base import ParserRegistry
from app.vendors.honeywell import HoneywellParser
from app.vendors.honeywell_fs import OPTIONS, HoneywellFsParser
from app.vendors.parse import crosscheck

PARSER = HoneywellFsParser()
HDR = 20


@pytest.fixture(scope="module")
def pool():
    return StreamPool()


def make(pool, spec=(("h264_base_320", True),)):
    """(image bytearray, clips, header offsets per chunk, streams)."""
    streams = [pool.get(n) for n, _ in spec]
    img, clips, _ = H.build_image(H._chunks(streams, [ix for _, ix in spec]))
    heads = [[p[0] - HDR for p in clips[f"c{i}"][1]] for i in range(len(spec))]
    return img, clips, heads, streams


def parse(data, **opts):
    return PARSER.parse(io.BytesIO(bytes(data)), len(data), opts)


def fields(r):
    return {f.name: f for f in r.fields}


def payload(data, c):
    return b"".join(bytes(data[a:b]) for a, b in c.extents)


# ---- parse correctness on the per-paper layout -------------------------------------------------


def test_machine_data_gpt_and_partition_fields_with_tags(pool):
    img, *_ = make(pool)
    r = parse(img)
    by = fields(r)
    assert r.status == "parsed" and r.parser == "Honeywell" and r.tier == "B"
    assert by["device_id"].value == "B011003AWFNRZEFKV" and by["device_id"].status == "parsed"
    assert by["model"].value == "HN350802xx" and by["model"].status == "parsed"
    assert by["machine_data_string_0x4400"].value == "sn private disk"
    assert by["machine_data_string_0x4400"].status == "unknown"
    assert by["machine_data_string_0x4420"].status == "unknown"
    assert by["gpt_header"].status == "inferred" and by["gpt_header"].value["header_crc32_ok"]
    assert (
        by["partition1_first_lba"].value == 40 and by["partition1_first_lba"].status == "inferred"
    )
    v = by["p1_video_data_offset"]
    assert v.value["raw_u32_le"] == 0x80000 and v.value["bytes_if_4k_units"] == 0x80000000
    assert v.status == "inferred" and "DERIVED" in v.note  # 4 KiB unit is the field doc's inference
    assert by["block_group_index"].value[0]["group_number"] == 1
    assert any("beyond the image" in w for w in r.warnings)  # compact image, documented offset


def test_unknown_fields_are_never_reported_as_parsed(pool):
    img, *_ = make(pool)
    r = parse(img)
    by = fields(r)
    for name in (
        "custom_header_constant",
        "checksum",
        "timezone",
        "padding_byte_value",
        "secondary_gpt",
        "partition2",
        "fixed_value",
        "h265_layout",
        "machine_data_string_0x4400",
    ):
        assert by[name].status == "unknown", name
    parsed = {n for n, f in by.items() if f.status == "parsed"}
    assert parsed == {
        "device_id",
        "model",
        "block_group_index",
        "video_block_list",
        "custom_header",
        "end_of_channel_delimiter",
    }
    clip_status = {f.name: f.status for f in r.clips[0].fields}
    assert clip_status["resolution"] == clip_status["clip_boundaries"] == "inferred"
    assert clip_status["frame_type"] == clip_status["timestamp"] == "parsed"


def test_clips_have_header_free_payload_extents_and_exact_frame_counts(pool):
    img, clips, heads, (s,) = make(pool)
    r = parse(img)
    (c,) = r.clips
    assert (c.codec, c.exportable, c.width, c.height) == ("h264", True, 320, 240)
    assert c.frames == s.frames == len(heads[0])
    assert c.key_frames == sum(1 for n in s.nals if n.irap)
    assert payload(img, c) == s.data  # 20-byte headers excluded, NAL data reassembles the stream
    assert all(b - a > 0 for a, b in c.extents)
    assert c.end_reason.startswith("end-of-channel delimiter")
    assert r.stats["frames"] == s.frames and r.stats["aligned_clip_starts"] == 1


def test_channel_comes_only_from_the_channel_index(pool):
    img, clips, heads, _ = make(pool, (("h264_base_320", True), ("h264_high_480", False)))
    r = parse(img)
    a, b = r.clips
    assert a.channel == 1
    cf = {f.name: f for f in a.fields}["channel"]
    assert cf.status == "inferred" and "id base" in cf.note
    assert b.channel is None  # no header channel field; deleted chunk has no index entry
    bf = {f.name: f for f in b.fields}["channel"]
    assert bf.status == "unknown" and "no channel field" in bf.note
    # erase the whole Channel Index: nobody gets a channel
    img[H.P1_ABS + 0x400000 : H.P1_ABS + 0x400000 + 64] = bytes(64)
    assert [c.channel for c in parse(img).clips] == [None, None]


def test_raw_timestamps_have_no_timezone_and_decode_is_plain(pool):
    img, clips, heads, _ = make(pool)
    r = parse(img)
    t = r.clips[0].timestamps[0]
    assert t.raw == H.BASE_US and t.offset == heads[0][0] + 12
    assert struct.unpack_from("<Q", img, t.offset)[0] == t.raw
    assert t.format == "unix microseconds (u64 LE)" and t.tz_basis == "not assumed"
    expect = datetime.fromtimestamp(H.BASE_US // 10**6, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    assert t.wall_clock_as_stored == expect  # plain epoch arithmetic, no zone suffix
    assert r.clips[0].timestamps[1].raw == H.BASE_US + 49 * H.FRAME_US
    assert all(x.tz_basis == "not assumed" for x in r.timestamps)
    assert not any("UTC" in x.wall_clock_as_stored for x in r.timestamps)


def test_time_basis_label_only_annotates(pool):
    img, *_ = make(pool)
    base = parse(img)
    for label in ("utc", "local"):
        r = parse(img, time_basis_label=label)
        t = r.clips[0].timestamps[0]
        assert t.tz_basis.startswith(label) and "examiner" in t.tz_basis
        b0 = base.clips[0].timestamps[0]
        assert (t.raw, t.wall_clock_as_stored, t.offset) == (
            b0.raw,
            b0.wall_clock_as_stored,
            b0.offset,
        )
        assert fields(r)["timezone"].status == "unknown"
    r = parse(img, time_basis_label="mars")
    assert r.clips[0].timestamps[0].tz_basis == "not assumed"
    assert any("time_basis_label" in w for w in r.warnings)


def test_options_and_schema(pool):
    img, clips, heads, (s,) = make(pool)
    # shift timestamps of frames >= 20 forward by 10 s (a recording gap)
    gap = bytearray(img)
    for h in heads[0][20:]:
        t = struct.unpack_from("<Q", gap, h + 12)[0]
        struct.pack_into("<Q", gap, h + 12, t + 10_000_000)
    tight, loose = parse(gap, max_time_gap_seconds=5), parse(gap, max_time_gap_seconds=60)
    assert tight.clips[0].frames == 20 and tight.clips[0].end_reason == "timestamp discontinuity"
    assert tight.orphans and tight.orphans[0].reason.startswith("non-key frames")
    assert len(tight.clips) >= 2 and len(loose.clips) == 1 and loose.clips[0].frames == s.frames
    rev = bytearray(img)  # time going backwards also splits
    for h in heads[0][20:]:
        t = struct.unpack_from("<Q", rev, h + 12)[0]
        struct.pack_into("<Q", rev, h + 12, t - 10_000_000)
    assert parse(rev, max_time_gap_seconds=60).clips[0].end_reason == "timestamp reversal"
    assert parse(img, min_clip_frames=1000).clips == []
    assert parse(img, min_clip_frames=1000).orphans[0].reason == "clip too short"
    assert parse(img, max_clips=0).warnings and parse(img, max_frames=7).stats["frames"] == 7
    assert parse(img, max_time_gap_seconds=1).options["max_time_gap_seconds"] == 1
    assert any("unknown options" in w for w in parse(img, bogus=1).warnings)
    assert set(OPTIONS) == set(PARSER.options_schema) and "time_basis_label" in OPTIONS
    assert OPTIONS["time_basis_label"]["default"] == "unspecified"


def test_video_scan_whole_image_and_format_candidate(pool):
    img, *_ = make(pool)
    # emulate the format signature of field doc 2.7: next == video offset, available == total
    struct.pack_into("<I", img, H.P1_ABS + 0x08, 0x80000)
    struct.pack_into("<I", img, H.P1_ABS + 0x10, 0x01BB33D1)
    img[H.P1_ABS + 0x40 : H.P1_ABS + 0x40 + 16] = bytes(16)
    r = parse(img, video_scan="whole_image")
    f = fields(r)["format_event_candidate"]
    assert f.status == "inferred" and r.clips and r.stats["video_scan_start"] == 0


# ---- corruption: never crash, never claim what was not parsed ----------------------------------


def test_wrong_magic_means_no_frames_and_fallback(pool):
    img, clips, heads, _ = make(pool)
    for h in heads[0]:
        img[h + 2] = 0x77  # `80 01 00` altered
    r = parse(img)
    assert r.status == "fallback" and not r.clips and "generic carving stands" in r.warnings[-1]


def test_one_bad_magic_ends_the_clip_before_the_bad_frame(pool):
    img, clips, heads, _ = make(pool)
    img[heads[0][10] + 1] = 0x00
    r = parse(img)
    assert r.status == "partial" and r.clips[0].frames == 9
    assert all(a < b for c in r.clips for a, b in c.extents)


def test_truncated_header_and_truncated_payload(pool):
    img, clips, heads, _ = make(pool)
    cut = parse(img[: heads[0][30] + 10])  # inside a custom header
    assert cut.clips and cut.clips[0].frames == 30 and cut.status == "partial"
    cut2 = parse(img[: heads[0][30] + 40])  # header present, payload cut
    assert cut2.clips[0].frames == 30 and any("beyond the image" in i for i in cut2.inconsistencies)
    assert parse(img[:100]).status == "fallback"


def test_bad_nal_length_fields(pool):
    img, clips, heads, _ = make(pool)
    good = parse(img).clips[0].frames
    for val in (0, 3, 0x7FFFFFFF, 0xFFFFFFFF):
        d = bytearray(img)
        struct.pack_into("<I", d, heads[0][5] + 8, val)
        r = parse(d)
        assert r.clips[0].frames == 5 and r.inconsistencies
    d = bytearray(img)  # off by one: lands inside the next header, not on it
    struct.pack_into("<I", d, heads[0][5] + 8, struct.unpack_from("<I", d, heads[0][5] + 8)[0] + 1)
    assert parse(d).clips[0].frames == 5 < good


def test_timestamps_out_of_plausible_range_are_rejected(pool):
    img, clips, heads, _ = make(pool)
    d = bytearray(img)
    struct.pack_into("<Q", d, heads[0][3] + 12, 5_000_000)  # 1970
    r = parse(d)
    assert r.clips[0].frames == 3 and any("timestamp outside" in i for i in r.inconsistencies)
    for h in heads[0]:
        struct.pack_into("<Q", d, h + 12, 0xFFFFFFFFFFFFFFFF)
    assert parse(d).status == "fallback"
    # the plausibility window is an option
    assert parse(img, ts_plausible_min_s=2_000_000_000).status == "fallback"


def test_index_entries_pointing_outside_the_image(pool):
    img, clips, heads, _ = make(pool)
    struct.pack_into("<I", img, H.P1_ABS + 0x400000 + 8, 0x7FFFFFFF)  # start far beyond the end
    r = parse(img)
    assert r.status == "partial" and r.clips[0].channel is None
    assert any("beyond_image" in i for i in r.inconsistencies)
    assert r.stats["channel_index"]["usable"] == 0


def test_headers_pointing_to_wrong_place_in_the_index_are_not_trusted(pool):
    img, clips, heads, _ = make(pool)
    start = struct.unpack_from("<I", img, H.P1_ABS + 0x400000 + 8)[0]
    struct.pack_into("<I", img, H.P1_ABS + 0x400000 + 8, start + 3)  # no header there
    r = parse(img)
    assert r.clips[0].channel is None and r.stats["channel_index"]["no_header_at_start"] == 1
    d = bytearray(img)
    d[H.P1_ABS + 0x400000 + 1] = 0x33  # undocumented stream type
    assert parse(d).stats["channel_index"]["bad_stream_type"] == 1


def test_gpt_damage_is_reported_and_video_still_parses(pool):
    img, clips, heads, (s,) = make(pool)
    d = bytearray(img)
    d[512:520] = bytes(8)  # signature gone
    r = parse(d)
    assert r.status == "partial" and any("signature" in i for i in r.inconsistencies)
    assert payload(d, r.clips[0]) == s.data and "gpt_header" in fields(r)
    assert fields(r)["gpt_header"].status == "unknown"
    d = bytearray(img)
    d[512 + 40] ^= 0xFF  # header CRC breaks
    assert any("header CRC32" in i for i in parse(d).inconsistencies)
    d = bytearray(img)
    d[2 * 512 + 40] ^= 0x01  # partition entry array CRC breaks
    assert any("entry array CRC32" in i for i in parse(d).inconsistencies)
    d = bytearray(img)  # Partition 1 first LBA != documented 40 (with a repaired CRC)
    struct.pack_into("<Q", d, 2 * 512 + 32, 41)
    arr = bytes(d[1024 : 1024 + 128 * 128])
    struct.pack_into("<I", d, 512 + 88, zlib.crc32(arr))
    hdr = bytearray(d[512 : 512 + 92])
    hdr[16:20] = bytes(4)
    struct.pack_into("<I", d, 512 + 16, zlib.crc32(bytes(hdr)))
    assert any("!= documented 40" in i for i in parse(d).inconsistencies)


def test_machine_data_missing_or_garbled(pool):
    img, clips, heads, (s,) = make(pool)
    d = bytearray(img)
    d[34 * 512 : 35 * 512] = bytes(512)
    r = parse(d)
    assert r.status == "partial" and any("Machine Data" in i for i in r.inconsistencies)
    assert "device_id" not in fields(r) and payload(d, r.clips[0]) == s.data
    d = bytearray(img)
    d[0x4440:0x4451] = bytes([0xFF]) * 17
    r = parse(d)
    assert "device_id" not in fields(r) and any("printable" in i for i in r.inconsistencies)
    assert "model" in fields(r)


def test_partition1_header_damage(pool):
    img, clips, heads, _ = make(pool)
    d = bytearray(img)
    d[H.P1_ABS : H.P1_ABS + 0x40] = bytes(0x40)
    r = parse(d)
    assert r.status == "partial" and any("all zero" in i for i in r.inconsistencies)
    assert r.clips and r.stats["video_scan_start"] == 0
    d = bytearray(img)
    struct.pack_into("<I", d, H.P1_ABS, 0x1234)  # Video Data Offset != 0x80000000
    r = parse(d)
    assert any("Video Data Offset" in i for i in r.inconsistencies) and r.clips
    d = bytearray(img)
    struct.pack_into("<I", d, H.P1_ABS + 0x10, 0x7FFFFFFF)  # available > total
    assert any("Available Memory" in i for i in parse(d).inconsistencies)


def test_nal_header_that_is_not_h264_is_neither_parsed_nor_exported(pool):
    img, clips, heads, _ = make(pool)
    for h in heads[0]:
        img[h + 24] = 0x40  # an HEVC VPS NAL header byte: H.265 layout is undocumented
    r = parse(img)
    assert r.status == "fallback" and not r.clips
    assert "H.265 layout is undocumented" in r.warnings[-1]
    assert fields(parse(make(pool)[0]))["h265_layout"].status == "unknown"


def test_no_checksum_is_claimed_or_verified(pool):
    img, clips, heads, (s,) = make(pool)
    base = parse(img)
    d = bytearray(img)
    # change payload bytes that stay valid (no zero run) and the unknown header bytes: a
    # verified checksum would reject something; the parser has nothing to verify
    a, b, _ = clips["c0"][1][3]
    d[a + 10] ^= 0x55
    for o in (H.P1_ABS + 0x04, H.P1_ABS + 0x0C, H.P1_ABS + 0x1C):
        d[o : o + 4] = b"\xff\xff\xff\xff"
    r = parse(d)
    assert r.clips[0].frames == base.clips[0].frames and r.status == base.status
    ck = fields(r)["checksum"]
    assert ck.status == "unknown" and "none is verified" in ck.note
    assert not any("crc" in i.lower() and "GPT" not in i for i in r.inconsistencies)
    assert not any("checksum" in f.name and f.status == "parsed" for f in r.fields)


def test_unknown_bytes_are_not_interpreted(pool):
    img, clips, heads, _ = make(pool)
    base = parse(img)
    d = bytearray(img)
    o = H.P1_ABS + 0x40  # Block Group Index: unknown +8..11, +0x0D..0x0F
    d[o + 8 : o + 12], d[o + 13 : o + 16] = b"\xff" * 4, b"\xff" * 3
    o = H.P1_ABS + 0x40000  # Video Block List: unknown +8..11, +14..15
    d[o + 8 : o + 12], d[o + 14 : o + 16] = b"\xff" * 4, b"\xff" * 2
    o = H.P1_ABS + 0x400000  # Channel Index: unknown +12..15
    d[o + 12 : o + 16] = b"\xff" * 4
    r = parse(d)
    assert [c.extents for c in r.clips] == [c.extents for c in base.clips]
    assert [(f.name, f.value) for f in r.fields] == [(f.name, f.value) for f in base.fields]
    assert r.status == base.status


def test_padding_after_delimiter_is_observed_not_assumed(pool):
    img, clips, heads, _ = make(pool)
    end = clips["c0"][1][-1][1] + 20
    nxt = -(-end // 4096) * 4096
    d = bytearray(img)
    d[end:nxt] = bytes([0xAA]) * (nxt - end)
    r = parse(d)
    pad = fields(r)["padding_byte_value"]
    assert pad.status == "unknown" and 0xAA in pad.value and r.clips[0].frames == 50


def test_corrupted_delimiter_rejects_the_last_frame(pool):
    img, clips, heads, _ = make(pool)
    end = clips["c0"][1][-1][1]
    d = bytearray(img)
    d[end : end + 20] = bytes([0xFF]) * 20
    r = parse(d)
    assert r.clips[0].frames == 49 and r.status == "partial"


def test_zeroed_region_splits_clips_and_does_not_leak_damaged_frames(pool):
    img, clips, heads, (s,) = make(pool)
    a = heads[0][20]
    img[a : a + 5000] = bytes(5000)
    r = parse(img)
    assert r.clips[0].frames == 20  # frames before the zeroed header
    for c in r.clips:  # every parsed byte equals the original stream bytes
        assert all(a2 < b2 for a2, b2 in c.extents)
    got = {a2: b2 for c in r.clips for a2, b2 in c.extents}
    for a2, b2, ss in clips["c0"][1]:
        if a2 in got:
            assert bytes(img[a2:b2]) == s.data[ss : ss + b2 - a2]


def test_fuzz_never_raises_and_status_is_valid(pool):
    base, clips, heads, _ = make(pool, (("h264_base_320", True), ("h264_high_480", True)))
    rnd = random.Random(11)
    zones = [
        (0, 0x5100),
        (H.P1_ABS + 0x40000, H.P1_ABS + 0x40100),
        (H.P1_ABS + 0x400000, H.P1_ABS + 0x400040),
    ]
    zones.append((heads[0][0] - 64, heads[0][0] + 40_000))
    for _ in range(80):
        d = bytearray(base)
        for _ in range(rnd.randrange(1, 40)):
            lo, hi = rnd.choice(zones)
            d[rnd.randrange(max(lo, 0), min(hi, len(d)))] = rnd.randrange(256)
        if rnd.random() < 0.3:
            d = d[: rnd.randrange(len(d))]
        r = parse(d)
        assert r.status in ("parsed", "partial", "fallback")
        for c in r.clips:
            assert c.extents and all(0 <= a < b <= len(d) for a, b in c.extents)
            assert c.frames > 0 and c.exportable
    for junk in (
        b"",
        b"\x00" * 5000,
        random.Random(2).randbytes(60_000),
        b"\x82\x80\x01\x00" * 3000,
    ):
        assert parse(junk).status == "fallback"


def test_parser_exception_becomes_fallback(pool, monkeypatch):
    img, *_ = make(pool)
    monkeypatch.setattr(
        honeywell_fs, "iter_frames", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    r = parse(img)
    assert r.status == "fallback" and "RuntimeError" in r.warnings[0] and not r.clips


def test_tier_and_identification_are_unchanged(pool):
    img, *_ = make(pool)
    assert PARSER.tier == "B" and PARSER.vendor == "Honeywell"
    assert isinstance(PARSER, HoneywellParser)
    reg = ParserRegistry([PARSER])
    (m,) = reg.identify(io.BytesIO(bytes(img)), len(img))
    assert m.vendor == "Honeywell" and m.tier == "B" and m.confidence == "medium"


# ---- real offsets on a sparse image ------------------------------------------------------------


def test_documented_offsets_on_a_sparse_image_only_read_structures(pool, tmp_path):
    s = pool.get("h264_base_320")
    data, pieces = H.chunk(s, 0, len(s.data), H.BASE_US)
    vdo = H.P1_ABS + 0x80000000
    size = vdo + len(data) + 4096
    p = tmp_path / "sparse.dd"
    with open(p, "wb") as f:
        f.truncate(size)
        f.seek(0)
        f.write(H._gpt(size // 512))
        f.seek(0x4400)
        f.write(H._machine_data())
        f.seek(H.P1_ABS)
        for off, v in ((0, 0x80000), (8, 0x80010), (0x10, 100), (0x18, 200)):
            f.seek(H.P1_ABS + off)
            f.write(struct.pack("<I", v))
        f.seek(H.P1_ABS + 0x400000)  # Channel Index entry: channel 5, main stream
        f.write(
            bytes([5, 0])
            + struct.pack("<H", len(data) // 4096)
            + struct.pack("<II", H.BASE_US // 10**6, 0x80000)
            + bytes(4)
        )
        # Record State, channel 1 subregion (field doc 2.4): count byte then anchors at +0x14
        base = H.P1_ABS + 0x40000000 + 0x20000
        f.seek(base)
        f.write(bytes([2]))
        f.seek(base + 0x14)
        f.write(struct.pack("<I", 1_749_999_600) + bytes(16))
        f.write(struct.pack("<I", 1_750_003_200) + bytes(16))
        f.seek(vdo)
        f.write(data)
    with open(p, "rb") as f:
        r = PARSER.parse(f, size, {})
    assert r.status == "parsed", (r.warnings, r.inconsistencies)
    assert r.stats["video_scan_start"] == vdo and len(r.clips) == 1
    c = r.clips[0]
    assert c.start == vdo + pieces[0][0] and c.channel == 5 and c.frames == s.frames
    assert not any("beyond the image" in w for w in r.warnings)
    (rs,) = r.stats["record_state"]
    assert rs["count_byte"] == 2 and rs["anchors_read"] == 2 and rs["off_hour"] == 0
    assert fields(r)["record_state"].status == "inferred"


# ---- cross-check against the generic carver ----------------------------------------------------


def generic_clips(data):
    carver = Carver(lambda o, n: data[o : o + n], CarveParams())
    return [
        c
        for c in carver.run(nal.scan(io.BytesIO(data), len(data)))
        if hasattr(c, "extents") and hasattr(c, "vcl_count")
    ]


def test_crosscheck_only_benign_disagreements_on_clean_image(pool):
    img, *_ = make(pool, (("h264_base_320", True), ("h264_high_480", True)))
    data = bytes(img)
    r = parse(data)
    xc = crosscheck(r.clips, generic_clips(data))
    kinds = {d["kind"] for d in xc["disagreements"]}
    # the generic carver absorbs the 20-byte headers between NAL units
    assert kinds <= {"generic_includes_extra_bytes", "frame_count_mismatch"}
    assert xc["parser_clips"] == 2 and xc["generic_clips"] == 2
    g = generic_clips(data)
    assert sum(e - s for c in g for s, e in c.extents) > sum(c.size for c in r.clips)


def test_crosscheck_reports_an_unexplained_generic_clip(pool):
    img, clips, heads, _ = make(pool, (("h264_base_320", True), ("h264_high_480", True)))
    data = bytes(img)
    r = parse(data, min_clip_frames=1000)  # parser keeps nothing, generic still finds both
    kinds = {d["kind"] for d in crosscheck(r.clips, generic_clips(data))["disagreements"]}
    assert kinds == {"generic_clip_not_explained_by_parser"}


# ---- pipeline integration (local registry; __init__ is not edited) -----------------------------


@pytest.fixture
def local_registry(monkeypatch):
    monkeypatch.setattr(analyze_mod, "default_registry", lambda: ParserRegistry([PARSER]))


def make_image_file(pool, tmp_path):
    img, *_ = make(pool, (("h264_base_320", True), ("h264_high_480", False)))
    p = tmp_path / "honeywell_like.dd"
    p.write_bytes(bytes(img))
    return p


def _acquire(client, case, path):
    r = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"source_path": str(path), "label": "hw-like", "write_blocker": "yes"},
    )
    return r.json()


def test_pipeline_runs_parser_beside_generic(client, pool, tmp_path, local_registry):
    case = client.post("/api/cases", json={"case_number": "H-1", "title": "hw"}).json()
    ev = _acquire(client, case, make_image_file(pool, tmp_path))
    r = client.post(
        f"/api/evidence/{ev['id']}/analyze",
        json={"parser_options": {"Honeywell": {"time_basis_label": "utc"}}},
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["vendor_matches"][0]["vendor"] == "Honeywell"
    (p,) = run["parsers"]
    assert p["tier"] == "B" and p["status"] == "parsed" and p["crosscheck"]["parser_clips"] == 2
    assert p["options"]["time_basis_label"] == "utc"
    parsed = [c for c in run["clips"] if c["engine"] == "Honeywell" and c["kind"] == "clip"]
    assert len(parsed) == 2 and {c["engine"] for c in run["clips"]} == {"Honeywell"}
    assert sorted(c["channel"] for c in parsed if c["channel"] is not None) == [1]
    info = json.loads(parsed[0]["parsed_json"])
    assert info["timestamps"][0]["tz_basis"].startswith("utc") and info["fields"]


def test_parser_failure_leaves_generic_carving_standing(
    client, pool, tmp_path, local_registry, monkeypatch
):
    case = client.post("/api/cases", json={"case_number": "H-2", "title": "fb"}).json()
    ev = _acquire(client, case, make_image_file(pool, tmp_path))
    monkeypatch.setattr(
        HoneywellFsParser, "_parse", lambda *a, **k: (_ for _ in ()).throw(ValueError("corrupt"))
    )
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    assert run["status"] == "completed" and run["parsers"][0]["status"] == "fallback"
    assert any(c["engine"] == "generic" and c["kind"] == "clip" for c in run["clips"])
    assert not any(c["engine"] == "Honeywell" for c in run["clips"])


# ---- the synthetic scenarios -------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(H.SCENARIOS))
def test_scenarios_build_and_parse_without_header_bytes_in_clips(pool, name):
    b = H.SCENARIOS[name](random.Random(5), pool, 0)
    img, truth = b.build()
    assert truth["synthetic"] and truth["layout"] == H.LAYOUT and len(img) < 8 << 20
    r = parse(img)
    assert r.status in ("parsed", "partial") and r.clips
    src = {t["id"]: pool.get(t["variant"]).data for t in truth["clips"]}
    for c in r.clips:  # every parsed payload is a contiguous slice of one source stream
        data = payload(img, c)
        assert any(data in s for s in src.values())
    assert all(c["frames_total"] > 0 for c in truth["clips"])


def test_decode_helpers():
    assert honeywell_fs.decode_us(1_750_000_000_123_456) == "2025-06-15 15:06:40.123456"
    assert honeywell_fs.decode_s(1_750_000_000) == "2025-06-15 15:06:40"
    assert honeywell_fs.decode_us(1 << 80) == ""
