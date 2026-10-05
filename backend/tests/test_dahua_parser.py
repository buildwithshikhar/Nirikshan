import io
import random
import struct

import pytest
from sqlalchemy import select

from app import analyze as analyze_mod
from app.carving.carve import CarveParams
from app.models import Clip, CustodyEntry
from app.validation import layouts as L
from app.validation.streams import StreamPool
from app.vendors import default_registry
from app.vendors.dahua_dhav import OPTIONS, DhavParser, decode_date, parse_ext
from app.vendors.parse import ParsedClip, crosscheck
from tests.media import filler

PARSER = DhavParser()


@pytest.fixture(scope="module")
def pool():
    return StreamPool()


def image(pool, spec, noise=300):
    """spec: list of (variant, channel). Returns (bytes, expected frame counts, streams)."""
    out = bytearray(filler(noise, 1))
    n = 1000
    streams = []
    for name, ch in spec:
        s = pool.get(name)
        streams.append(s)
        for fr, _o, _l, _s in L.wrap_stream(s, 0, len(s.data), ch, n):
            out += fr
        n += 10_000
        out += b"\x00" * 64
    return bytes(out), streams


def parse(data, **opts):
    return PARSER.parse(io.BytesIO(data), len(data), opts)


def test_parses_clips_per_channel_with_exact_payload_extents(pool):
    data, (s,) = image(pool, [("h264_base_320", 3)])
    r = parse(data)
    assert r.status == "parsed" and r.parser == "Dahua" and r.tier == "B"
    (c,) = r.clips
    assert (c.codec, c.channel, c.frames, c.key_frames) == ("h264", 3, s.frames, 5)
    assert (c.width, c.height) == (320, 240) and c.exportable
    assert b"".join(data[a:b] for a, b in c.extents) == s.data  # payloads reassemble the stream
    assert r.stats["video_frames"] == s.frames and r.stats["annexb_frames"] == s.frames


def test_two_channels_interleaved_are_demultiplexed(pool):
    a, b = pool.get("h264_base_320"), pool.get("h264_main_b_352")
    fa = L.wrap_stream(a, 0, len(a.data), 0, 100)
    fb = L.wrap_stream(b, 0, len(b.data), 1, 500)
    data = b"".join(x[0] for pair in zip(fa, fb, strict=False) for x in pair)
    data += b"".join(x[0] for x in (fa[len(fb) :] or fb[len(fa) :]))
    r = parse(data)
    assert sorted(c.channel for c in r.clips) == [0, 1]
    for c in r.clips:
        src = a if c.channel == 0 else b
        assert b"".join(data[s:e] for s, e in c.extents) == src.data


def test_raw_timestamps_have_no_timezone_and_decode_is_plain(pool):
    data, _ = image(pool, [("h264_base_320", 0)])
    r = parse(data)
    t = r.clips[0].timestamps[0]
    assert t.raw == L.frame_date(1000) and t.tz_basis == "not assumed"  # first frame number 1000
    assert t.wall_clock_as_stored == "2025-06-01 12:00:40" and "bit-packed" in t.format
    assert decode_date(L.pack_date(2031, 12, 31, 23, 59, 58))[1] == "2031-12-31 23:59:58"
    assert all(x.tz_basis == "not assumed" for x in r.timestamps)
    assert not any("UTC" in x.wall_clock_as_stored for x in r.timestamps)


def test_fields_are_tagged_and_unverified_ones_are_not_claimed(pool):
    data, _ = image(pool, [("h264_base_320", 0)])
    by = {f.name: f for f in parse(data).fields}
    assert by["frame_header"].status == by["frame_trailer"].status == "parsed"
    assert by["payload_format"].status == "inferred"
    assert (
        by["checksum_byte"].status
        == by["subtype_byte"].status
        == by["dhfs_structures"].status
        == "unknown"
    )
    assert "not verified" in by["checksum_byte"].note
    assert by["date"].status == "parsed" and "NOT assumed" in by["date"].note
    clip_fields = {f.name: f.status for f in parse(data).clips[0].fields}
    assert clip_fields["clip_boundaries"] == "inferred" and clip_fields["channel"] == "parsed"


def test_checksum_byte_is_ignored_because_its_algorithm_is_undocumented(pool):
    s = pool.get("h264_base_320")
    ok = b"".join(x[0] for x in L.wrap_stream(s, 0, len(s.data), 0, 1))
    frames = list(L.wrap_stream(s, 0, len(s.data), 0, 1))
    bad = b"".join(
        L.dhav_frame(
            0xFD if k == 0 else 0xFC, 0, 1 + k, fr[0][fr[1] : fr[1] + fr[2]], checksum=0xFF
        )[0]
        for k, fr in enumerate(frames[:3])
    )
    assert parse(ok).clips and parse(bad).stats["frames"] == 3  # no 'bad checksum' rejection


def test_non_exportable_codecs_are_listed_not_exported():
    ext = L.dhav_ext("h264", 320, 240)
    ext = ext[:-2] + bytes([0x03, 25])  # codec id 0x3 = MJPEG per dhav.c
    data = b"".join(
        L.dhav_frame(
            0xFD if i == 0 else 0xFC, 0, i, b"\xff\xd8" + b"x" * 40, ext=ext if i == 0 else b""
        )[0]
        for i in range(4)
    )
    (c,) = parse(data).clips
    assert c.codec == "mjpeg" and not c.exportable and "not exported" in " ".join(c.notes)


def test_frame_gap_option_controls_clip_boundaries(pool):
    s = pool.get("h264_base_320")
    fr = L.wrap_stream(s, 0, len(s.data), 0, 1)
    data = b"".join(f[0] for f in fr[:20]) + b"".join(
        L.dhav_frame(0xFC, 0, 30 + k, f[0][f[1] : f[1] + f[2]])[0] for k, f in enumerate(fr[20:30])
    )
    tight = parse(data, frame_gap_tolerance=3)
    loose = parse(data, frame_gap_tolerance=50)
    assert len(tight.clips) == 1 and tight.clips[0].end_reason == "frame_number discontinuity"
    assert tight.orphans and tight.orphans[0].reason.startswith("non-key video frames")
    assert len(loose.clips) == 1 and loose.clips[0].frames == 30
    assert parse(data, frame_gap_tolerance=3).options["frame_gap_tolerance"] == 3
    assert set(OPTIONS) == {"frame_gap_tolerance", "min_clip_frames", "max_frames_per_run"}


# ---- corruption: never crash, never claim what was not parsed ---------------------------------


def _clean(pool):
    return image(pool, [("h264_base_320", 0)])[0]


def test_wrong_magic_means_no_frames_and_fallback(pool):
    data = _clean(pool).replace(b"DHAV", b"DHAX")
    r = parse(data)
    assert r.status == "fallback" and not r.clips and "generic carving stands" in r.warnings[0]


def test_truncated_header_and_truncated_frame(pool):
    data = _clean(pool)
    assert parse(data[:10]).status == "fallback"
    start = data.index(b"DHAV")
    r = parse(data[: start + 24 + 5])  # header present, trailer missing
    assert r.status == "fallback" and any(
        "trailer" in i or "length" in i for i in r.inconsistencies
    )
    r2 = parse(data[:-300])  # last frame cut: earlier frames still parse, partial
    assert r2.clips and r2.status == "partial"


def test_bad_trailer_length_and_length_field_corruption(pool):
    data = bytearray(_clean(pool))
    first = data.index(b"DHAV")
    flen = struct.unpack_from("<I", data, first + 12)[0]
    d1 = bytearray(data)
    struct.pack_into("<I", d1, first + flen - 4, 7)  # trailer u32 wrong
    r1 = parse(bytes(d1))
    assert r1.stats["frames"] < parse(bytes(data)).stats["frames"] and r1.inconsistencies
    d2 = bytearray(data)
    struct.pack_into("<I", d2, first + 12, 23)  # length < 24
    assert any("out of range" in i for i in parse(bytes(d2)).inconsistencies)
    d3 = bytearray(data)
    struct.pack_into("<I", d3, first + 12, 0x7FFFFFFF)
    assert parse(bytes(d3)).clips is not None


def test_extension_overrun_is_rejected(pool):
    fr, _ = L.dhav_frame(0xFD, 0, 1, b"\x00\x00\x00\x01" + b"x" * 8)
    bad = bytearray(fr)
    bad[22] = 200  # declared extension longer than the frame
    r = parse(bytes(bad))
    assert r.status == "fallback" and not r.clips


def test_parse_ext_unknown_tlv_stops_like_dhav_c():
    info, used = parse_ext(b"\x82\x00\x00\x00\x40\x01\xf0\x00" + b"\x77" + b"\x00" * 7)
    assert info == {"width": 320, "height": 240} and used == 16


def test_fuzz_never_raises_and_status_is_valid(pool):
    base = _clean(pool)[:60_000]
    rnd = random.Random(3)
    for _ in range(150):
        d = bytearray(base)
        for _ in range(rnd.randrange(1, 40)):
            d[rnd.randrange(len(d))] = rnd.randrange(256)
        if rnd.random() < 0.3:
            d = d[: rnd.randrange(len(d))]
        r = parse(bytes(d))
        assert r.status in ("parsed", "partial", "fallback")
        for c in r.clips:
            assert c.extents and all(a < b for a, b in c.extents)
    for junk in (b"", b"\x00" * 5000, filler(50_000, 9), b"DHAV" * 3000):
        assert parse(junk).status == "fallback"


def test_parser_exception_becomes_fallback(pool, monkeypatch):
    from app.vendors import dahua_dhav

    monkeypatch.setattr(
        dahua_dhav, "iter_frames", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    r = parse(_clean(pool))
    assert r.status == "fallback" and "RuntimeError" in r.warnings[0]


# ---- cross-check against the generic carver ----------------------------------------------------


def test_crosscheck_flags_expected_header_absorption_only_on_a_clean_image(pool):
    from app.carving import nal
    from app.carving.carve import Carver

    data, _ = image(pool, [("h264_base_320", 0)])
    r = parse(data)
    carver = Carver(lambda o, n: data[o : o + n], CarveParams())
    generic = [
        c
        for c in carver.run(nal.scan(io.BytesIO(data), len(data)))
        if hasattr(c, "extents") and hasattr(c, "vcl_count")
    ]
    xc = crosscheck(r.clips, generic)
    kinds = {d["kind"] for d in xc["disagreements"]}
    assert (
        kinds <= {"generic_includes_extra_bytes", "frame_count_mismatch"}
        and xc["parser_clips"] == 1
    )


def test_crosscheck_reports_every_kind_of_disagreement():
    class G:
        def __init__(self, ext, codec="h264", vcl=10):
            self.extents, self.codec, self.vcl_count = ext, codec, vcl

    p = [
        ParsedClip("h264", [[0, 100]], 0, frames=10),
        ParsedClip("h264", [[1000, 1100]], 1, frames=10),
    ]
    xc = crosscheck(p, [G([[0, 100]], "h265", 9), G([[5000, 5200]])])
    kinds = [d["kind"] for d in xc["disagreements"]]
    assert kinds == [
        "codec_mismatch",
        "frame_count_mismatch",
        "parser_clip_not_found_by_generic",
        "generic_clip_not_explained_by_parser",
    ]


# ---- pipeline integration ----------------------------------------------------------------------


def make_dahua_image(pool, tmp_path):
    data, _ = image(pool, [("h264_base_320", 2), ("h265_main_320", 5)], noise=2000)
    p = tmp_path / "dahua_like.dd"
    p.write_bytes(data)
    return p


def _acquire(client, case, path):
    r = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"source_path": str(path), "label": "dahua-like", "write_blocker": "yes"},
    )
    return r.json()


def test_pipeline_runs_parser_beside_generic_and_records_everything(
    client, pool, tmp_path, session
):
    case = client.post("/api/cases", json={"case_number": "D-1", "title": "dhav"}).json()
    ev = _acquire(client, case, make_dahua_image(pool, tmp_path))
    r = client.post(
        f"/api/evidence/{ev['id']}/analyze",
        json={"parser_options": {"Dahua": {"frame_gap_tolerance": 5}}},
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["vendor_matches"][0]["vendor"] == "Dahua" and run["vendor_matches"][0]["tier"] == "B"
    (p,) = run["parsers"]
    assert p["parser"] == "Dahua" and p["tier"] == "B" and p["status"] == "parsed"
    assert p["options"]["frame_gap_tolerance"] == 5 and p["crosscheck"]["parser_clips"] == 2
    assert {f["name"]: f["status"] for f in p["fields"]}["checksum_byte"] == "unknown"
    engines = {c["engine"] for c in run["clips"]}
    assert engines == {"Dahua"}  # fully parsed image: nothing left for generic carving
    parsed = [c for c in run["clips"] if c["engine"] == "Dahua" and c["kind"] == "clip"]
    assert sorted(c["channel"] for c in parsed) == [2, 5] and all(
        c["decode_status"] == "ok" for c in parsed
    )
    info = __import__("json").loads(parsed[0]["parsed_json"])
    assert info["timestamps"][0]["tz_basis"] == "not assumed" and info["fields"]
    acts = [e.action for e in session.scalars(select(CustodyEntry).order_by(CustodyEntry.seq))]
    assert "parser_completed" in acts
    assert all(c.engine in ("generic", "Dahua") for c in session.scalars(select(Clip)))


def test_parser_failure_leaves_generic_carving_standing(client, pool, tmp_path, monkeypatch):
    case = client.post("/api/cases", json={"case_number": "D-2", "title": "fb"}).json()
    ev = _acquire(client, case, make_dahua_image(pool, tmp_path))
    monkeypatch.setattr(
        default_registry().parser_for("Dahua").__class__,
        "_parse",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("corrupt")),
    )
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    assert run["status"] == "completed" and run["parsers"][0]["status"] == "fallback"
    assert any(c["engine"] == "generic" and c["kind"] == "clip" for c in run["clips"])
    assert not any(c["engine"] == "Dahua" for c in run["clips"])


def test_tiers_are_unchanged_by_parsing():
    assert {p.vendor: p.tier for p in default_registry().parsers}["Dahua"] == "B"
    assert analyze_mod  # module import sanity
