"""Hikvision file-system parser tests.

CIRCULARITY NOTICE: the layout under test (app.validation.layouts_hikvision) and the parser are both
written from docs/parsers/hikvision-fields.md. Passing here shows internal consistency and
robustness, NOT that the parser reads real Hikvision devices (no real image has been examined).
"""

import io
import json
import random
import struct

import pytest
from sqlalchemy import select

from app import analyze as analyze_mod
from app.carving import nal
from app.carving.carve import CarveParams, Carver
from app.models import Clip, CustodyEntry
from app.validation import layouts_hikvision as LH
from app.validation.streams import Stream, StreamPool
from app.vendors import hikvision_fs
from app.vendors.base import ParserRegistry
from app.vendors.hikvision_fs import OPTIONS, HikvisionFsParser, wall
from app.vendors.parse import crosscheck

PARSER = HikvisionFsParser()
VALID = ("parsed", "partial", "fallback")


@pytest.fixture(scope="module")
def pool():
    return StreamPool()


def parse(data, **opts):
    return PARSER.parse(io.BytesIO(data), len(data), opts)


def blk(i, s, ch, **kw):
    return LH._blk(i, s, ch, **kw)


@pytest.fixture(scope="module")
def std(pool):
    """3 blocks: ch1 (times), ch2 (times), ch1 (sentinel times) + one unused block."""
    s1, s2, s3 = (pool.get(n) for n in ("h264_base_320", "h264_main_b_352", "h264_base_256"))
    blocks = [blk(0, s1, 1), blk(1, s2, 2), blk(2, s3, 1, times=None)]
    img, clips, meta = LH.build_image(random.Random(5), blocks)
    return img, meta, (s1, s2, s3)


def entry_pos(meta, i, copy=1):
    base = meta["hik1"] if copy == 1 else meta["hik2"]
    per = (4096 - 0x10) // 48
    return base + 0x2000 + 0x1000 * (i // per) + 0x10 + 48 * (i % per)


def put(img, off, data):
    d = bytearray(img)
    d[off : off + len(data)] = data
    return bytes(d)


def mput(img, meta, rel, data):
    """Patch the primary Master Sector (struct offset rel)."""
    return put(img, meta["master_base"] + rel, data)


def by_name(r):
    return {f.name: f for f in r.fields}


# ---- parse correctness -------------------------------------------------------------------------


def test_parses_clips_channels_and_exact_payload_extents(std):
    img, meta, (s1, s2, s3) = std
    r = parse(img)
    assert r.status == "parsed" and r.parser == "Hikvision" and r.tier == "B"
    assert [c.channel for c in r.clips] == [1, 2, 1]
    for c, s in zip(r.clips, (s1, s2, s3), strict=True):
        assert c.codec == "h264" and c.exportable
        assert b"".join(img[a:b] for a, b in c.extents) == s.data
        assert (c.frames, c.key_frames) == (s.frames, sum(1 for n in s.nals if n.irap))
    bo = LH.VIDEO_OFF
    assert all(
        bo + i * LH.BLOCK <= c.start and c.end <= bo + (i + 1) * LH.BLOCK
        for i, c in enumerate(r.clips)
    )
    assert r.stats["entries"] == 4 and r.stats["entries_with_video"] == 3
    assert r.stats["idr_table_records"] == sum(
        sum(1 for n in s.nals if n.irap) for s in (s1, s2, s3)
    )


def test_master_sector_fields_and_geometry(std):
    img, meta, _ = std
    f = by_name(parse(img))
    assert f["master_sector_signature_offset"].value == 0x210
    assert f["capacity_bytes"].value == len(img)
    assert (f["log_offset"].value, f["log_size"].value) == (LH.LOG_OFF, LH.LOG_SIZE)
    assert f["video_area_offset"].value == LH.VIDEO_OFF
    assert f["block_size_field"].value == LH.BLOCK and f["block_count"].value == 4
    assert (
        f["hikbtree1_offset"].value == meta["hik1"] and f["hikbtree2_offset"].value == meta["hik2"]
    )
    assert f["init_time"].value == LH.INIT_T
    assert f["backup_master_sector"].value == {
        "offset": meta["backup_master"],
        "identical_to_primary": True,
    }
    assert f["backup_master_sector"].status == "inferred"  # location is undocumented
    assert f["block_geometry_check"].value["field"] is True


def test_raw_timestamps_carry_no_timezone_and_sentinel_gives_none(std):
    img, _, _ = std
    r = parse(img)
    t0, t1 = r.clips[0].timestamps
    assert (t0.raw, t1.raw) == (LH.T0, LH.T0 + 600)
    assert t0.tz_basis == "not assumed" and "u32 LE" in t0.format
    assert t0.wall_clock_as_stored == wall(LH.T0) == "2014-11-27 14:53:20"
    assert r.clips[2].timestamps == [] and "sentinel" in " ".join(r.clips[2].notes)
    assert all(x.tz_basis == "not assumed" for x in r.timestamps)
    names = {x.field for x in r.timestamps}
    assert {"master sector init time", "hikbtree header created time"} <= names
    assert not any("UTC" in x.wall_clock_as_stored for x in r.timestamps)


def test_tags_unknown_fields_are_never_reported_as_parsed(std):
    img, _, _ = std
    r = parse(img)
    f = by_name(r)
    for name in (
        "master_unlabelled_bytes",
        "master_sector_pre_signature_bytes",
        "version_like_string",
        "idr_table_record_fields",
        "checksum",
        "hevc_framing",
        "log_preamble",
        "block_size_conflict_in_source",
        "timestamp_basis_conflict_in_source",
    ):
        assert f[name].status == "unknown", name
    assert f["idr_table"].status == "parsed" and "OFNI" in f["idr_table"].note
    assert f["HIKBTREE1_entry_layout"].status == "inferred"  # first-entry offset undocumented
    assert f["HIKBTREE1_page_list"].status == "parsed"
    assert f["rats_record_count"].status == "inferred"  # no documented length field
    assert f["video_region_end"].status == "inferred"
    assert all(x.status in ("parsed", "inferred", "unknown") for x in r.fields)
    cf = {x.name: x.status for x in r.clips[0].fields}
    assert cf["entry_channel"] == "parsed" and cf["channel_attribution"] == "inferred"
    assert cf["clip_boundaries"] == "inferred" and cf["idr_record_fields"] == "unknown"
    blob = json.dumps([x.__dict__ for x in r.fields], default=str)
    assert "idr_record_index" not in blob and "idr_record_timestamp" not in blob


def test_rats_log_sample_and_summary(std):
    img, _, _ = std
    f = by_name(parse(img))
    assert f["rats_record_count"].value == 6
    assert f["rats_header_variants"].value == {"14000000": 6}
    assert f["rats_major_type_counts"].value == {
        "1:Alarm": 1,
        "2:Exception": 1,
        "3:Operation": 2,
        "4:Information": 2,
    }
    assert f["rats_time_range_raw"].value == [LH.T0, LH.T0 + 300]
    s = f["rats_sample"].value
    assert len(s) == 6 and s[0]["offset"] == LH.LOG_OFF + 0x800  # Dragonas: records start +2048
    assert s[0]["minor_name"] == "Remote: Login" and s[0]["user"] == "admin"
    assert s[0]["ip"] == "192.168.10.100" and s[0]["tz_basis"] == "not assumed"
    assert "user" not in s[2]  # Details are only parsed for Operation
    assert f["log_preamble"].note.endswith("+0x800")


def test_log_sample_is_bounded_and_cap_is_reported(std):
    img, _, _ = std
    r = parse(img, log_sample_size=2, max_log_records=3)
    f = by_name(r)
    assert len(f["rats_sample"].value) == 2 and f["rats_record_count"].value == 3
    assert any("RATS record cap" in w for w in r.warnings)


def test_rats_variant_01_is_accepted(pool):
    s = pool.get("h264_base_320")
    img, _, _ = LH.build_image(random.Random(1), [blk(0, s, 1)], variant=b"\x01\x00\x00\x00")
    assert by_name(parse(img))["rats_header_variants"].value == {"01000000": 6}


def test_orphans_and_h265_are_not_claimed(pool):
    s = pool.get("h265_main_320")
    img, _, _ = LH.build_image(random.Random(1), [blk(0, s, 1)])
    r = parse(img)
    assert not r.clips and r.orphans and "undocumented" in r.orphans[0].reason
    assert r.status == "partial"


def test_block_referenced_with_two_channels_has_no_channel(std):
    img, meta, _ = std
    extra = LH.entry(True, 7, LH.T0, LH.T0 + 600, LH.VIDEO_OFF)  # same block as entry 0, ch 7
    d = put(img, entry_pos(meta, 4), extra)
    r = parse(d)
    assert r.clips[0].channel is None and r.status == "partial"
    assert any("channel attribution not possible" in i for i in r.inconsistencies)


# ---- options -----------------------------------------------------------------------------------


def test_master_sector_offset_auto_0x200_and_0x210(pool):
    s = pool.get("h264_base_320")
    for base in (0x200, 0x210):
        img, _, _ = LH.build_image(random.Random(1), [blk(0, s, 1)], master_base=base)
        for opt in ("auto", base, hex(base)):
            r = parse(img, master_sector_offset=opt)
            assert r.status == "parsed" and len(r.clips) == 1
            assert by_name(r)["master_sector_signature_offset"].value == base
        other = 0x200 if base == 0x210 else 0x210
        r = parse(img, master_sector_offset=other)
        assert r.status == "fallback" and not r.clips
    r = parse(img, master_sector_offset="0x333")
    assert (
        any("master_sector_offset" in w for w in r.warnings)
        and r.options["master_sector_offset"] == "auto"
    )


def test_master_signature_found_by_search_is_flagged(std):
    img, meta, _ = std
    moved = bytearray(img)
    sec = bytes(moved[0x210:0x310])
    moved[0x210:0x310] = b"\x00" * 0x100
    moved[0x230:0x330] = sec  # signature at 0x230: neither documented offset
    r = parse(bytes(moved))
    assert any("unusual offset 0x230" in i for i in r.inconsistencies)
    assert by_name(r)["master_sector_signature_offset"].value == 0x230


def test_block_size_mode_changes_behaviour_and_always_flags_the_conflict(std):
    img, meta, _ = std
    outs = {m: parse(img, block_size_mode=m) for m in ("field", "0x400000", "1gib")}
    for m, r in outs.items():
        f = by_name(r)["block_size_conflict_in_source"]
        assert "0x400000" in f.value and "1 GB" in f.value and f"block_size_mode={m}" in f.value
        assert f"0x{LH.BLOCK:X}" in f.value and f.status == "unknown"
    assert outs["field"].status == "parsed" and len(outs["field"].clips) == 3
    assert by_name(outs["field"])["block_size_used"].value == LH.BLOCK
    for m, size in (("0x400000", 0x400000), ("1gib", 1 << 30)):
        r = outs[m]
        assert by_name(r)["block_size_used"].value == size
        assert r.status == "partial" and not r.clips  # no clip is emitted on a clamped block
        assert any("clamped" in i for i in r.inconsistencies)
        assert r.orphans and "clamped" in r.orphans[0].reason and r.orphans[0].channel is None
        assert by_name(r)["block_geometry_check"].value["field"] is True


def test_block_size_field_equal_to_text_value_parses_cleanly_and_is_still_flagged(pool):
    s = pool.get("h264_base_320")
    img, _, _ = LH.build_image(random.Random(1), [blk(0, s, 1)], block_size=0x400000)
    r = parse(img)  # field mode: 0x400000 in this image's field
    assert r.status == "parsed" and len(r.clips) == 1
    assert "block_size_conflict_in_source" in by_name(r)
    g = parse(img, block_size_mode="1gib")
    assert g.status == "partial" and by_name(g)["block_size_used"].value == 1 << 30
    assert not g.clips  # entry for the only block is clamped, then geometry exceeds the image


def test_invalid_block_size_mode_falls_back_to_field(std):
    img, _, _ = std
    r = parse(img, block_size_mode="2gib")
    assert r.options["block_size_mode"] == "field" and any(
        "block_size_mode" in w for w in r.warnings
    )


def test_time_basis_label_only_changes_the_label(std):
    img, _, _ = std
    base = parse(img)
    assert "timestamp_basis_conflict_in_source" in by_name(base)
    for lab in ("utc", "local"):
        r = parse(img, time_basis_label=lab)
        assert "timestamp_basis_conflict_in_source" in by_name(r)
        pairs = list(zip(base.timestamps, r.timestamps, strict=True)) + [
            p
            for a, b in zip(base.clips, r.clips, strict=True)
            for p in zip(a.timestamps, b.timestamps, strict=True)
        ]
        assert pairs
        for a, b in pairs:
            assert (a.raw, a.offset, a.wall_clock_as_stored) == (
                b.raw,
                b.offset,
                b.wall_clock_as_stored,
            )
            assert (
                a.tz_basis == "not assumed" and lab in b.tz_basis and "no conversion" in b.tz_basis
            )
        assert [c.extents for c in r.clips] == [c.extents for c in base.clips]
        assert by_name(r)["rats_sample"].value[0]["created_time_raw"] == LH.T0
        assert by_name(r)["rats_sample"].value[0]["created_wall"] == wall(LH.T0)
    assert parse(img, time_basis_label="gmt").options["time_basis_label"] == "unspecified"


def test_options_schema_and_defaults(std):
    img, _, _ = std
    assert PARSER.options_schema is OPTIONS and "block_size_mode" in OPTIONS
    r = PARSER.parse(io.BytesIO(img), len(img), None)
    assert (
        r.options["block_size_mode"] == "field" and r.options["time_basis_label"] == "unspecified"
    )
    assert parse(img, btree_first_entry_offset=0x10).clips  # explicit first-entry offset
    assert not parse(img, btree_first_entry_offset=0x18).clips  # wrong offset finds no entries


# ---- corruption: never crash, never claim what was not parsed ----------------------------------


def test_wrong_signature_and_tiny_images_fall_back(std):
    img, _, _ = std
    r = parse(put(img, 0x210, b"HIKVISION@HANGZHOX"))
    assert r.status == "fallback" and not r.clips and "generic carving stands" in r.warnings[-1]
    for n in (0, 10, 0x210, 0x230, 0x2E0):
        assert parse(img[:n]).status == "fallback"
    for junk in (b"", b"\x00" * 5000, b"\xff" * 5000):
        assert parse(junk).status == "fallback"


def test_truncated_image_before_structures_is_partial_not_a_crash(std):
    img, meta, _ = std
    r = parse(img[: meta["hik1"] + 0x20])  # HIKBTREE header cut off
    assert r.status == "partial" and not r.clips
    assert any("HIKBTREE1" in i for i in r.inconsistencies)
    r2 = parse(img[: meta["hik1"]])  # no HIKBTREE at all
    assert r2.status == "partial" and not r2.clips
    r3 = parse(img[: LH.VIDEO_OFF + 1000])  # also cuts the log's backup/video
    assert r3.status == "partial" and r3.inconsistencies


def test_offsets_and_sizes_pointing_outside_the_image(std):
    img, meta, _ = std
    big = struct.pack("<Q", len(img) + 10_000)
    cases = {
        0x88: (big, "HIKBTREE1"),  # HIKBTREE1 offset
        0x98: (big, "HIKBTREE2"),
        0x68: (big, "video area"),
        0x50: (big, "log area"),
    }
    for rel, (val, word) in cases.items():
        r = parse(mput(img, meta, rel, val))
        assert r.status == "partial" and any(word in i for i in r.inconsistencies), word
        assert all(c.start >= 0 and c.end <= len(img) for c in r.clips)
    z = parse(mput(img, meta, 0x58, struct.pack("<Q", 1 << 60)))  # absurd log size
    assert z.status == "partial" and any("log" in i for i in z.inconsistencies)
    sz = parse(mput(img, meta, 0x90, struct.pack("<I", 0xFFFFFFFF)))  # absurd HIKBTREE1 size
    assert any("HIKBTREE1" in i for i in sz.inconsistencies) and sz.clips  # backup tree still used
    assert any("backup HIKBTREE2" in w for w in sz.warnings)


def test_absurd_block_size_and_count(std):
    img, meta, _ = std
    r = parse(mput(img, meta, 0x78, struct.pack("<Q", 0)))
    assert not r.clips and any("zero or absurd" in i for i in r.inconsistencies)
    r = parse(mput(img, meta, 0x78, struct.pack("<Q", 1 << 62)))
    assert not r.clips and r.status == "partial"
    r = parse(mput(img, meta, 0x80, struct.pack("<I", 0xFFFFFFFF)))
    assert r.status == "partial" and any("block_count" in i for i in r.inconsistencies)


def test_absurd_page_counts_are_rejected(std):
    img, meta, _ = std
    for n in (0xFFFFFFFF, 100_000):
        r = parse(put(img, meta["hik1"] + 0x1000, struct.pack("<I", n)))
        assert any("absurd page count" in i for i in r.inconsistencies)
        assert r.clips  # HIKBTREE2 still usable
    r = parse(put(img, meta["hik1"] + 0x1000, struct.pack("<I", 0)))
    assert r.clips and by_name(r)["HIKBTREE1_page_list"].value["total_pages"] == 0


def test_circular_and_self_referencing_page_offsets(std):
    img, meta, _ = std
    h1 = meta["hik1"]
    page1 = h1 + 0x2000
    for target, word in ((page1, "repeats"), (h1, "repeats"), (h1 + 0x1000, "repeats")):
        d = put(img, h1 + 0x1010, struct.pack("<Q", target))  # second slot of the page list
        r = parse(d)
        assert any(word in i and "circular" in i for i in r.inconsistencies), hex(target)
        assert r.status == "partial" and r.stats["HIKBTREE1_pages"] == 1
    d = put(img, h1 + 0x1010, struct.pack("<Q", meta["hik2"] + 0x9000))  # outside the structure
    assert any("outside the HIKBTREE range" in i for i in parse(d).inconsistencies)
    d = put(img, h1 + 0x5000, struct.pack("<Q", page1))  # footer disagrees with the list
    assert any("footer last-page" in i for i in parse(d).inconsistencies)
    d = put(img, h1 + 0x48, struct.pack("<Q", h1 + 0x3000))  # header page #1 != list page #1
    assert any("page #1" in i for i in parse(d).inconsistencies)
    d = put(img, h1 + 0x30, struct.pack("<Q", 0))  # footer offset outside the tree
    assert any("footer offset" in i for i in parse(d).inconsistencies)


def test_hikbtree_signature_corruption_uses_backup_or_gives_no_entries(std):
    img, meta, _ = std
    one = put(img, meta["hik1"], b"HIKBTREX")
    r = parse(one)
    assert r.clips and any("backup HIKBTREE2" in w for w in r.warnings)
    both = put(one, meta["hik2"], b"HIKBTREX")
    r = parse(both)
    assert not r.clips and r.status == "partial" and r.stats["entries"] == 0


def test_hikbtree_sentinel_and_existence_semantics(std):
    img, meta, _ = std
    r = parse(img)
    assert not any("sentinel" in i for i in r.inconsistencies)
    assert r.clips[2].timestamps == []  # existence 00 + sentinel: times not reported
    # existence FF with a real channel/times contradicts the documented no-video form
    bad = LH.entry(False, 3, LH.T0, LH.T0 + 5, LH.VIDEO_OFF + 3 * LH.BLOCK)
    r = parse(put(img, entry_pos(meta, 3), bad))
    assert any("existence 0xFF" in i for i in r.inconsistencies)
    # existence 00 with channel 0xFF: block is not emitted
    d = put(
        img, entry_pos(meta, 1), LH.entry(True, 0xFF, LH.T0, LH.T0 + 5, LH.VIDEO_OFF + LH.BLOCK)
    )
    r = parse(d)
    assert len(r.clips) == 2 and any("channel 0xFF" in i for i in r.inconsistencies)
    # start > end: clip kept, timestamps omitted, inconsistency listed
    d = put(img, entry_pos(meta, 0), LH.entry(True, 1, LH.T0 + 9, LH.T0, LH.VIDEO_OFF))
    r = parse(d)
    assert r.clips[0].timestamps == [] and any("start time > end" in i for i in r.inconsistencies)
    # existence flag not uniform: entry is implausible and skipped
    e = bytearray(LH.entry(True, 1, LH.T0, LH.T0 + 5, LH.VIDEO_OFF))
    e[8] = 0xFF
    r = parse(put(img, entry_pos(meta, 0), bytes(e)))
    assert len(r.clips) == 2 and any("implausible" in i for i in r.inconsistencies)


def test_entry_block_offset_outside_video_area_or_misaligned(std):
    img, meta, _ = std
    out = LH.entry(True, 1, LH.T0, LH.T0 + 5, len(img) + 0x1000)
    r = parse(put(img, entry_pos(meta, 0), out))
    assert len(r.clips) == 2 and any("implausible" in i for i in r.inconsistencies)
    mis = LH.entry(True, 1, LH.T0, LH.T0 + 5, LH.VIDEO_OFF + 0x1000)  # not n * block size
    r = parse(put(img, entry_pos(meta, 0), mis))
    assert len(r.clips) == 2 and any("not video_offset + n*" in i for i in r.inconsistencies)
    idx = LH.entry(True, 1, LH.T0, LH.T0 + 5, LH.VIDEO_OFF + 9 * LH.BLOCK)  # index >= block count
    r = parse(put(img, entry_pos(meta, 0), idx))
    assert any("block count" in i or "implausible" in i for i in r.inconsistencies)
    assert all(c.end <= len(img) for c in r.clips)


def test_truncated_rats_record_is_reported(std):
    img, meta, _ = std
    cut = struct.pack("<Q", 0x800 + 0x40 * 5 + 8)  # log area ends 8 bytes into the 6th record
    r = parse(mput(img, meta, 0x58, cut))
    assert r.stats["rats_truncated"] == 1 and any("cut off" in i for i in r.inconsistencies)
    assert by_name(r)["rats_sample"].value[-1].get("truncated") is True
    # an image that ends inside a record (log area at the very end of a tiny image)
    r2 = parse(img[: LH.LOG_OFF + 0x800 + 0x40 + 6])
    assert r2.status in VALID


def test_backup_master_difference_is_reported(std):
    img, meta, _ = std
    r = parse(put(img, meta["backup_master"] + 0x38, struct.pack("<Q", 1)))
    f = by_name(r)["backup_master_sector"]
    assert f.value["identical_to_primary"] is False
    assert any("backup Master Sector" in i for i in r.inconsistencies)
    r = parse(put(img, meta["backup_master"], b"\x00" * 18))
    assert by_name(r)["backup_master_sector"].status == "unknown" and r.status == "parsed"


def test_no_checksum_is_claimed_or_verified(std):
    """No source documents any checksum for these structures: flipping bytes in cells the document
    marks unknown must not change the outcome, and no checksum field is ever 'parsed'."""
    img, meta, _ = std
    base = parse(img)
    d = img
    for rel in (0x20, 0x41, 0x48, 0xB0, 0xE8):  # version string, unlabelled cells, rest of sector
        d = put(put(d, 0x210 + rel, b"\xa5\x5a"), meta["backup_master"] + rel, b"\xa5\x5a")
    d = put(d, meta["hik1"] + 0x38, b"\x12" * 8)  # duplicate-of-footer cell (unlabelled)
    d = put(d, meta["hik1"] + 0x50, b"\x34" * 8)
    d = put(d, entry_pos(meta, 0), b"\x00" * 8)  # unlabelled entry cell +0x00
    d = put(d, entry_pos(meta, 0) + 0x28, b"\x56" * 8)  # entry cell labelled "unknown" in Fig.6
    r = parse(d)
    assert r.status == base.status == "parsed" and not r.inconsistencies
    assert [c.extents for c in r.clips] == [c.extents for c in base.clips]
    f = by_name(r)["checksum"]
    assert f.status == "unknown" and "none documented" in f.value and "none verified" in f.value
    assert not [x for x in r.fields if "crc" in x.name.lower() and x.status == "parsed"]
    assert not [x for x in r.fields if "checksum" in x.name.lower() and x.status != "unknown"]
    assert not any("checksum" in i.lower() or "crc" in i.lower() for i in r.inconsistencies)
    assert "backup HIKBTREE2" not in " ".join(r.warnings)


def small_image(pool, seed=0):
    s = pool.get("h264_base_320")
    cut = next(n.start for n in s.nals if n.start > 30_000)
    small = Stream(s.variant, s.data[:cut], [n for n in s.nals if n.end <= cut])
    blocks = [blk(0, small, 1), blk(1, small, 2), blk(2, small, 3, times=None)]
    return LH.build_image(random.Random(seed), blocks, block_size=0x10000)


def test_fuzz_never_raises_and_clips_always_have_valid_extents(pool):
    base, _, meta = small_image(pool)
    assert len(base) < 400_000 and parse(base).status == "parsed"
    rnd = random.Random(11)
    hot = [(0, 0x340), (LH.LOG_OFF, LH.LOG_OFF + 0x900), (meta["hik1"], len(base))]
    for i in range(250):
        d = bytearray(base)
        for _ in range(rnd.randrange(1, 30)):
            lo, hi = rnd.choice(hot) if rnd.random() < 0.8 else (0, len(d))
            d[rnd.randrange(lo, min(hi, len(d)))] = rnd.randrange(256)
        if rnd.random() < 0.3:
            d = d[: rnd.randrange(len(d))]
        data = bytes(d)
        r = parse(data)
        assert r.status in VALID
        assert not any("parser error" in w for w in r.warnings), (i, r.warnings)
        for c in r.clips:
            assert c.extents and all(0 <= a < b <= len(data) for a, b in c.extents)
        for o in r.orphans:
            assert 0 <= o.start <= o.end <= len(data)
    for junk in (b"", b"\x00" * 5000, random.Random(2).randbytes(50_000), b"HIKBTREE" * 2000):
        assert parse(junk).status == "fallback"


def test_parser_exception_becomes_fallback(std, monkeypatch):
    img, _, _ = std
    monkeypatch.setattr(
        hikvision_fs._Run, "logs", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    r = parse(img)
    assert r.status == "fallback" and "RuntimeError" in r.warnings[0] and not r.clips


# ---- cross-check against the generic carver ----------------------------------------------------


def generic_clips(data):
    carver = Carver(lambda o, n: data[o : o + n], CarveParams())
    return [
        c
        for c in carver.run(nal.scan(io.BytesIO(data), len(data)))
        if hasattr(c, "extents") and hasattr(c, "vcl_count")
    ]


def test_crosscheck_on_a_clean_layout_shows_only_benign_kinds(std):
    img, _, _ = std
    r = parse(img)
    xc = crosscheck(r.clips, generic_clips(img))
    kinds = {d["kind"] for d in xc["disagreements"]}
    assert kinds <= {"generic_includes_extra_bytes", "frame_count_mismatch"}
    assert xc["parser_clips"] == 3 and xc["generic_clips"] >= 3


def test_crosscheck_flags_the_deleted_blocks_the_parser_cannot_see(pool):
    from app.validation.layouts_hikvision import SCENARIOS

    b = SCENARIOS["deleted_intact_zero"](random.Random(3), pool, 0)
    img, _ = b.build()
    r = parse(img)
    assert len(r.clips) == 1  # entries of blocks 1 and 2 were cleared: documented no-video form
    xc = crosscheck(r.clips, generic_clips(img))
    kinds = [d["kind"] for d in xc["disagreements"]]
    assert kinds.count("generic_clip_not_explained_by_parser") == 2
    assert set(kinds) <= {
        "generic_clip_not_explained_by_parser",
        "generic_includes_extra_bytes",
        "frame_count_mismatch",
    }


# ---- scenarios ---------------------------------------------------------------------------------


def test_scenarios_build_small_labelled_per_paper_images(pool):
    assert set(LH.SCENARIOS) == {
        "clean_live",
        "deleted_intact_zero",
        "partial_overwrite_zero",
        "multi_channel_gop",
    }
    assert "per-paper layout" in LH.LAYOUT and "not a real device image" in LH.LAYOUT
    for name, fn in LH.SCENARIOS.items():
        b = fn(random.Random(7), pool, 0)
        img, truth = b.build()
        assert truth["synthetic"] and truth["layout"] == LH.LAYOUT and len(img) < 6 * 1024 * 1024
        assert truth["clips"], name
        r = parse(img)
        assert r.status in ("parsed", "partial") and r.clips, name
        for c in r.clips:  # each parsed clip lies inside the truth pieces of a recovered clip
            assert any(
                p[0] <= c.start and c.end <= p[1] + 4096 and t["channel"] == c.channel
                for t in truth["clips"]
                for p in t["pieces"]
            ), name


def test_multi_channel_and_partial_overwrite_scenarios(pool):
    b = LH.SCENARIOS["multi_channel_gop"](random.Random(2), pool, 0)
    r = parse(b.build()[0])
    assert [c.channel for c in r.clips] == [1, 2, 1, 3, 2] and r.status == "parsed"
    b = LH.SCENARIOS["partial_overwrite_zero"](random.Random(2), pool, 0)
    img, truth = b.build()
    r = parse(img)
    victim = truth["clips"][1]
    assert victim["frames_recoverable"] < victim["frames_total"]
    assert r.clips[1].frames < victim["frames_total"]  # only the surviving prefix is carved
    assert r.clips[1].channel == 2


# ---- pipeline integration ----------------------------------------------------------------------


def make_image(pool, tmp_path):
    s1, s2 = pool.get("h264_base_320"), pool.get("h264_main_b_352")
    img, _, _ = LH.build_image(random.Random(5), [blk(0, s1, 2), blk(1, s2, 5)])
    p = tmp_path / "hik_like.dd"
    p.write_bytes(img)
    return p


@pytest.fixture
def local_registry(monkeypatch):
    from app.vendors import default_registry

    base = default_registry()
    parsers = [HikvisionFsParser() if p.vendor == "Hikvision" else p for p in base.parsers]
    monkeypatch.setattr(analyze_mod, "default_registry", lambda: ParserRegistry(parsers))
    return ParserRegistry(parsers)


def test_pipeline_runs_parser_beside_generic(client, pool, tmp_path, session, local_registry):
    case = client.post("/api/cases", json={"case_number": "H-1", "title": "hik"}).json()
    r = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={
            "source_path": str(make_image(pool, tmp_path)),
            "label": "hik",
            "write_blocker": "yes",
        },
    )
    ev = r.json()
    r = client.post(
        f"/api/evidence/{ev['id']}/analyze",
        json={"parser_options": {"Hikvision": {"time_basis_label": "local"}}},
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["vendor_matches"][0]["vendor"] == "Hikvision"
    (p,) = run["parsers"]
    assert p["parser"] == "Hikvision" and p["tier"] == "B" and p["status"] == "parsed"
    assert p["options"]["time_basis_label"] == "local"
    assert p["crosscheck"]["parser_clips"] == 2
    fields = {f["name"]: f["status"] for f in p["fields"]}
    assert fields["checksum"] == "unknown" and fields["block_size_conflict_in_source"] == "unknown"
    assert {c["engine"] for c in run["clips"]} == {"generic", "Hikvision"}
    parsed = [c for c in run["clips"] if c["engine"] == "Hikvision" and c["kind"] == "clip"]
    assert sorted(c["channel"] for c in parsed) == [2, 5]
    assert all(c["decode_status"] == "ok" for c in parsed)
    info = json.loads(parsed[0]["parsed_json"])
    assert "local" in info["timestamps"][0]["tz_basis"] and info["fields"]
    acts = [e.action for e in session.scalars(select(CustodyEntry).order_by(CustodyEntry.seq))]
    assert "parser_completed" in acts
    assert all(c.engine in ("generic", "Hikvision") for c in session.scalars(select(Clip)))


def test_pipeline_parser_failure_leaves_generic_standing(
    client, pool, tmp_path, local_registry, monkeypatch
):
    case = client.post("/api/cases", json={"case_number": "H-2", "title": "fb"}).json()
    ev = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={
            "source_path": str(make_image(pool, tmp_path)),
            "label": "hik",
            "write_blocker": "yes",
        },
    ).json()
    monkeypatch.setattr(
        hikvision_fs._Run, "run", lambda *a, **k: (_ for _ in ()).throw(ValueError("corrupt"))
    )
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    assert run["status"] == "completed" and run["parsers"][0]["status"] == "fallback"
    assert any(c["engine"] == "generic" and c["kind"] == "clip" for c in run["clips"])
    assert not any(c["engine"] == "Hikvision" for c in run["clips"])


def test_tier_is_unchanged_by_parsing():
    assert PARSER.tier == "B" and PARSER.vendor == "Hikvision"
    assert parse(b"\x00" * 100).tier == "B"
