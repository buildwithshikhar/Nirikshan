import io
import random
import tracemalloc

import pytest

from app.carving import nal as N
from tests.media import carve, filler, nal_units

CODECS = ["h264_baseline", "h264_main_b", "h264_high", "h265_main"]


def events(data, chunk):
    return list(N.scan(io.BytesIO(data), len(data), chunk))


# ---- NAL header decode -----------------------------------------------------------------------


def test_h265_header_bit_layout_against_ffmpeg_definitions():
    # hevc.h: VPS 32, SPS 33, PPS 34, IDR_W_RADL 19, CRA 21; header = 0,type(6),layer(6),tid+1(3)
    assert N.h265_header(0x40, 0x01) == (32, 0, 1)
    assert N.h265_header(0x42, 0x01) == (33, 0, 1)
    assert N.h265_header(0x44, 0x01) == (34, 0, 1)
    assert N.h265_header(0x26, 0x01) == (19, 0, 1)
    assert N.h265_header(0x2A, 0x01) == (21, 0, 1)
    assert N.h265_header(0x26, 0x09) == (19, 1, 1)  # layer id 1 in the low bits of byte 1
    assert N.h265_header(0x41, 0x01) == (32, 32, 1)  # layer id spans b0 bit0 + b1 bits 7..3
    assert N.h265_header(0x26, 0x00) is None  # temporal_id_plus1 == 0 is invalid
    assert N.h265_header(0xA6, 0x01) is None  # forbidden_zero_bit set


def test_real_h265_stream_starts_vps_sps_pps_irap(streams):
    types = [N.h265_header(n[0], n[1])[0] for _, n in nal_units(streams["h265_main"])][:5]
    # x265 inserts a prefix SEI (39) between the parameter sets and the IRAP picture
    assert types[:3] == [32, 33, 34] and any(16 <= t <= 21 for t in types[3:])


def test_real_h264_stream_starts_sps_pps_idr(streams):
    types = [n[0] & 0x1F for _, n in nal_units(streams["h264_baseline"])]
    assert types[:2] == [7, 8] and 5 in types[:4]


@pytest.mark.parametrize("name", CODECS)
def test_no_zero_triplets_inside_nal_payloads(streams, name):
    """Emulation prevention: the carver's end-of-NAL logic relies on this."""
    for _, payload in nal_units(streams[name]):
        body = payload.rstrip(b"\x00")
        assert (
            b"\x00\x00\x00" not in body
            and b"\x00\x00\x01" not in body
            and b"\x00\x00\x02" not in body
        )


# ---- scanner ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", CODECS)
@pytest.mark.parametrize("chunk", [1, 2, 3, 5, 7, 64, 1000, 4096])
def test_scanner_is_chunk_boundary_safe(streams, name, chunk):
    data = streams[name][:6000]

    def starts(evs):
        return [(e.run_start, e.sc_start, e.hdr, e.head) for e in evs if isinstance(e, N.StartCode)]

    assert starts(events(data, chunk)) == starts(events(data, 1 << 20))


def test_scanner_handles_zero_runs_across_boundaries():
    data = (
        b"\x00\x00\x01\x67\xaa"
        + b"\x00" * 50
        + b"\xff"
        + b"\x00" * 7
        + b"\x00\x00\x00\x01\x68\xbb"
        + b"\x00\x00"
    )
    ref = [
        (type(e).__name__, getattr(e, "sc_start", getattr(e, "pos", None)))
        for e in events(data, 1 << 20)
    ]
    for chunk in range(1, 40):
        got = [
            (type(e).__name__, getattr(e, "sc_start", getattr(e, "pos", None)))
            for e in events(data, chunk)
        ]
        # duplicates of ZeroRun at carried positions are allowed; start codes must match exactly
        assert [g for g in got if g[0] == "StartCode"] == [r for r in ref if r[0] == "StartCode"], (
            chunk
        )
        assert ("ZeroRun", 5) in got


def test_start_code_forms_and_head_bytes():
    data = b"\x00\x00\x01\x65" + b"\xaa" * 20 + b"\x00\x00\x00\x01\x41" + b"\xbb" * 20
    sc = [e for e in events(data, 1 << 20) if isinstance(e, N.StartCode)]
    assert (sc[0].sc_start, sc[0].hdr, sc[0].head[:2]) == (0, 3, b"\x65\xaa")
    assert (sc[1].run_start, sc[1].sc_start, sc[1].hdr) == (24, 24, 28)
    assert len(sc[0].head) == N.HEAD


# ---- clip carving ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", CODECS)
def test_clean_stream_is_one_exact_clip(streams, name):
    data = streams[name]
    clips, orphans, _ = carve(data)
    assert len(clips) == 1 and orphans == []
    c = clips[0]
    assert c.codec == name.split("_")[0] and c.extents == [[0, len(data)]]
    assert c.irap_count == 2 and c.vcl_count >= 50 and not c.reassembled


@pytest.mark.parametrize("name", CODECS)
def test_chunk_size_does_not_change_carve_result(streams, name):
    data = streams[name]
    ref = carve(data)[0][0].extents
    for chunk in (997, 4096, 65536):
        assert carve(data, chunk)[0][0].extents == ref


@pytest.mark.parametrize("name", CODECS)
def test_zero_padded_clip_in_noise_is_found_exactly(streams, name):
    data = streams[name]
    pre, post = filler(30_001, 1), filler(20_003, 2)
    img = pre + b"\x00" * 4096 + data + b"\x00" * 8192 + post
    clips, orphans, _ = carve(img)
    assert len(clips) == 1
    start = len(pre) + 4096
    # the leading zero byte of a 4-byte start code belongs to the clip
    assert clips[0].extents == [[start, start + len(data)]]
    assert img[clips[0].start : clips[0].end] == data


def test_garbage_without_zeros_after_clip_is_absorbed_documented_limit(streams):
    data = streams["h264_baseline"]
    img = data + filler(5000, 3)
    c = carve(img)[0][0]
    assert c.start == 0 and len(data) <= c.end <= len(img)  # tail garbage absorbed into last NAL


def test_two_different_streams_back_to_back_are_two_clips(streams):
    a, b = streams["h264_baseline"], streams["h264_high"]
    img = a + b"\x00" * 100 + b
    clips, _, _ = carve(img)
    assert [c.extents for c in clips] == [[[0, len(a)]], [[len(a) + 100, len(img)]]]
    assert clips[0].end_reason == "gap of 100 bytes"


def test_h264_and_h265_in_one_image(streams):
    a, b = streams["h264_main_b"], streams["h265_main"]
    img = a + b"\x00" * 4096 + b
    clips, _, _ = carve(img)
    assert [c.codec for c in clips] == ["h264", "h265"]


def test_zero_overwrite_in_middle_yields_clip_orphan_clip(streams):
    data = streams["h264_baseline"]
    units = list(nal_units(data))
    idr2 = [s for s, n in units if n[0] & 0x1F == 5][1]
    # zero out from 40% of the first GOP up to just before the second GOP's parameter sets
    sps2 = [s for s, n in units if n[0] & 0x1F == 7][1]
    cut = len(data) // 5
    img = data[:cut] + b"\x00" * (sps2 - cut) + data[sps2:]
    clips, orphans, _ = carve(img)
    assert len(clips) == 2 and clips[0].end <= cut and clips[1].start == sps2
    assert clips[0].end_reason.startswith("gap")
    assert clips[1].end == len(data) and idr2 >= sps2


def test_overwrite_inside_gop_keeps_following_slices_as_orphan_until_next_irap(streams):
    data = streams["h264_baseline"]
    units = list(nal_units(data))
    sps2 = [s for s, n in units if n[0] & 0x1F == 7][1]
    mid = [s for s, n in units if s < sps2][10]
    img = data[:mid] + b"\x00" * 3000 + data[mid + 3000 :]
    clips, orphans, _ = carve(img)
    assert clips[0].end <= mid + 3000 and len(clips) == 2 and clips[1].start == sps2
    assert orphans and orphans[0].reason.startswith("slices without")
    assert orphans[0].nal_count >= 1


def test_random_overwrite_without_zero_runs_is_flagged_by_continuity_or_survives(streams):
    data = bytearray(streams["h264_baseline"])
    data[4000:4400] = filler(400, 9)  # damages a few slices, no start codes
    clips, _, _ = carve(bytes(data))
    assert clips and clips[0].start == 0  # never crashes; decode test reports damage (export tests)


def test_foreign_data_spliced_into_clip_breaks_on_frame_num_discontinuity(streams):
    """Another stream's P slices spliced mid-GOP: frame_num check ends the clip (H.264 only)."""
    a = streams["h264_baseline"]
    units = list(nal_units(a))
    sps2 = [s for s, n in units if n[0] & 0x1F == 7][1]
    p_slices = [(s, n) for s, n in units if n[0] & 0x1F == 1 and s < sps2]
    cut = p_slices[3][0]
    # take P slices from the 2nd GOP of the same stream (frame_num restarted): a foreign jump
    foreign = [(s, n) for s, n in units if n[0] & 0x1F == 1 and s > sps2][12:14]
    spliced = b"".join(b"\x00\x00\x00\x01" + n for _, n in foreign)
    img = a[:cut] + spliced + a[cut:sps2]
    clips, orphans, _ = carve(img)
    assert clips[0].end_reason.startswith("frame_num discontinuity")


def test_continuity_check_can_be_disabled(streams):
    data = streams["h264_baseline"]
    assert carve(data, h264_continuity=False)[0][0].extents == [[0, len(data)]]


def test_irap_without_parameter_sets_is_an_orphan_not_a_clip(streams):
    data = streams["h264_baseline"]
    units = list(nal_units(data))
    idr = [s for s, n in units if n[0] & 0x1F == 5][0]
    clips, orphans, _ = carve(b"\x00" * 100 + data[idr:])
    assert clips == [] or all(c.start >= idr for c in clips)
    assert orphans and orphans[0].reason == "IRAP picture without parameter sets"


def test_fragment_reassembly_off_by_default_and_on_with_join_gap(streams):
    data = streams["h264_baseline"]
    units = list(nal_units(data))
    p = [s for s, n in units if n[0] & 0x1F == 1][5]  # NAL boundary inside GOP 1
    img = data[:p] + b"\x00" * 50_000 + data[p:]
    clips, orphans, _ = carve(img)
    assert len(clips) == 2 and orphans  # split, continuation reported as orphan
    clips, orphans, _ = carve(img, join_gap=100_000)
    assert len(clips) == 1 and clips[0].reassembled and orphans == []
    assert clips[0].extents == [[0, p], [p + 50_000, len(img)]]
    assert b"".join(img[s:e] for s, e in clips[0].extents) == data
    assert any("heuristic" in n for n in clips[0].notes)


def test_h265_has_no_join_even_when_requested(streams):
    data = streams["h265_main"]
    units = list(nal_units(data))
    cut = units[len(units) // 4][0]
    img = data[:cut] + b"\x00" * 50_000 + data[cut:]
    clips, _, _ = carve(img, join_gap=100_000)
    assert not any(c.reassembled for c in clips)


# ---- robustness ------------------------------------------------------------------------------


def test_garbage_and_zeros_produce_nothing_and_do_not_crash():
    for img in (
        b"",
        b"\x00",
        b"\x00" * 100_000,
        filler(300_000, 4),
        b"\xff" * 5000,
        b"\x00\x00\x01",
        b"\x00\x00\x00\x01\x67",
        b"\x00\x00\x01\x65",
    ):
        clips, orphans, stats = carve(img)
        assert clips == []


def test_random_start_codes_with_junk_headers_do_not_crash():
    rnd = random.Random(7)
    img = b"".join(
        b"\x00\x00\x01" + bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 40)))
        for _ in range(3000)
    )
    carve(scrub_keep_sc(img))


def scrub_keep_sc(b):
    return b


def test_fuzzed_streams_never_raise(streams):
    rnd = random.Random(11)
    for name in CODECS:
        base = streams[name][:60_000]
        for _ in range(40):
            d = bytearray(base)
            for _ in range(rnd.randrange(1, 30)):
                d[rnd.randrange(len(d))] = rnd.randrange(256)
            if rnd.random() < 0.3:
                a = rnd.randrange(len(d))
                d[a : a + rnd.randrange(2000)] = b"\x00" * 2000
            carve(bytes(d), chunk=rnd.choice([97, 4096, 1 << 20]))


def test_oversize_nal_is_reported_not_swallowed(streams):
    data = streams["h264_baseline"]
    clips, _, stats = carve(data, max_nal=1000)
    assert stats["oversize_nal_units"] >= 1


def test_scan_memory_is_bounded_on_large_inputs(tmp_path):
    p = tmp_path / "big.bin"
    with open(p, "wb") as f:
        for i in range(32):
            f.write(filler(1 << 20, i) if i % 2 else b"\x00" * (1 << 20))
    size = p.stat().st_size
    tracemalloc.start()
    with open(p, "rb") as f:
        n = sum(1 for _ in N.scan(f, size, 1 << 20))
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert n >= 1 and peak < 12 * (1 << 20)  # 32 MiB scanned, peak a few chunks


# ---- parameter-set validation, EOF trimming, PPS references ---------------------------------


def _first(data, kind):
    for _, n in nal_units(data):
        if kind == "h264_sps" and n[0] & 0x1F == 7:
            return n
        if kind == "h264_pps" and n[0] & 0x1F == 8:
            return n
        if kind == "h265_vps" and (n[0] >> 1) & 0x3F == 32:
            return n
        if kind == "h265_sps" and (n[0] >> 1) & 0x3F == 33:
            return n
        if kind == "h265_pps" and (n[0] >> 1) & 0x3F == 34:
            return n


@pytest.mark.parametrize("name", ["h264_baseline", "h264_main_b", "h264_high"])
def test_real_h264_parameter_sets_validate_and_mutations_do_not(streams, name):
    from app.carving import bits

    sps, pps = _first(streams[name], "h264_sps"), _first(streams[name], "h264_pps")
    parsed = bits.validate_h264_sps(sps)
    assert parsed and parsed.log2_max_frame_num >= 4
    assert bits.validate_h264_pps(pps, {parsed.sps_id}) is not None
    assert bits.validate_h264_pps(pps, {parsed.sps_id + 5}) is None  # PPS must reference the SPS
    bad = bytes([sps[0], 0x01, *sps[2:]])  # profile_idc 1 is not a profile
    assert bits.validate_h264_sps(bad) is None
    assert bits.validate_h264_sps(sps[:5]) is None  # truncated


def test_real_h265_parameter_sets_validate_and_mutations_do_not(streams):
    from app.carving import bits

    d = streams["h265_main"]
    vps, sps, pps = _first(d, "h265_vps"), _first(d, "h265_sps"), _first(d, "h265_pps")
    v = bits.validate_h265_vps(vps)
    assert v is not None
    s = bits.validate_h265_sps(sps, {v})
    assert s is not None and bits.validate_h265_pps(pps, {s}) is not None
    assert bits.validate_h265_vps(vps[:2] + b"\x00" * 10) is None  # reserved 0xFFFF missing
    assert bits.validate_h265_sps(sps, {v + 1}) is None  # SPS must reference an existing VPS


def test_fake_parameter_set_groups_are_rejected_unless_validation_is_disabled():
    rnd = random.Random(5)
    sc = b"\x00\x00\x00\x01"
    accepted = 0
    for _ in range(200):
        fake = (
            sc
            + b"\x67"
            + filler(12, rnd.randrange(10**6))
            + sc
            + b"\x68"
            + filler(4, rnd.randrange(10**6))
        )
        fake += sc + b"\x65" + b"\x88" + filler(100, rnd.randrange(10**6))
        accepted += bool(carve(fake)[0])
    assert accepted == 0
    # with validation off the same junk can become "clips": that is what the check prevents
    loose = 0
    for _ in range(200):
        fake = sc + b"\x67" + filler(12, rnd.randrange(10**6)) + sc + b"\x68\xce" + filler(4, 1)
        fake += sc + b"\x65\x88" + filler(100, rnd.randrange(10**6))
        loose += bool(carve(fake, validate_params=False)[0])
    assert loose > 0


@pytest.mark.parametrize("name", CODECS)
def test_trailing_zero_bytes_at_eof_are_not_part_of_the_clip(streams, name):
    data = streams[name]
    for tail in (b"\x00", b"\x00\x00"):
        clips, _, _ = carve(data + tail)
        assert clips[0].extents == [[0, len(data)]]


def test_slice_with_unknown_pps_ends_the_clip(streams):
    """A P slice whose pps_id was never sent in the clip is not accepted into it."""
    data = streams["h264_baseline"]
    # header bits: first_mb ue(0)="1", slice_type ue(0)="1", pps_id ue(1)="010"
    fake = b"\x00\x00\x01\x41\xd0" + b"\x88" * 20
    clips, orphans, _ = carve(data + fake)
    assert clips[0].extents == [[0, len(data)]]
    assert clips[0].end_reason == "slice references a PPS not seen in the clip"
