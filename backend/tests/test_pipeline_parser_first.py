import io

import pytest
from sqlalchemy import select

from app.carving import nal
from app.carving.carve import CarveParams
from app.carving.ranges import carve_ranges, merge_spans, uncovered
from app.models import Clip
from app.validation import layouts as L
from app.validation import run as R
from app.validation.scenarios import SCENARIOS
from app.validation.streams import StreamPool
from tests.media import filler


@pytest.fixture(scope="module")
def pool():
    return StreamPool()


def dhav_bytes(stream, channel=1, n0=1000):
    return b"".join(f[0] for f in L.wrap_stream(stream, 0, len(stream.data), channel, n0))


def acquire(client, case, path):
    r = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"source_path": str(path), "label": "p", "write_blocker": "yes"},
    )
    return r.json()


@pytest.fixture
def case(client):
    return client.post("/api/cases", json={"case_number": "PF-1", "title": "parser first"}).json()


# ---- range bookkeeping ----------------------------------------------------------------------


def test_merge_spans_and_uncovered():
    assert merge_spans([(10, 20), (15, 30), (40, 50), (5, 5)]) == [(10, 30), (40, 50)]
    assert uncovered([(10, 30), (40, 50)], 60) == [(0, 10), (30, 40), (50, 60)]
    assert uncovered([], 5) == [(0, 5)] and uncovered([(0, 5)], 5) == []
    assert uncovered([(0, 3), (4, 9)], 9) == [(3, 4)]


def test_scan_start_matches_a_full_scan_from_that_offset(streams):
    data = b"\x00" * 100 + streams["h264_baseline"]
    full = [e for e in nal.scan(io.BytesIO(data), len(data)) if isinstance(e, nal.StartCode)]
    part = [
        e for e in nal.scan(io.BytesIO(data), len(data), start=100) if isinstance(e, nal.StartCode)
    ]
    assert [e.sc_start for e in part] == [e.sc_start for e in full if e.sc_start >= 100]


def test_carve_ranges_never_straddles_and_respects_the_end(streams):
    a, b = streams["h264_baseline"], streams["h265_main"]
    img = b"\x00" * 64 + a + b"\x00" * 64 + b + b"\x00" * 64
    ranges = [(0, 64 + len(a) + 64), (64 + len(a) + 64, len(img))]
    clips = [
        c
        for c in carve_ranges(io.BytesIO(img), ranges, CarveParams())
        if hasattr(c, "extents") and hasattr(c, "vcl_count")
    ]
    assert [c.codec for c in clips] == ["h264", "h265"]
    assert all(r[0] <= c.start and c.end <= r[1] for c, r in zip(clips, ranges, strict=True))
    only_second = [
        c
        for c in carve_ranges(io.BytesIO(img), [ranges[1]], CarveParams())
        if hasattr(c, "vcl_count")
    ]
    assert [c.codec for c in only_second] == ["h265"]


# ---- pipeline ---------------------------------------------------------------------------------


def test_partial_parser_never_loses_a_clip_and_nothing_is_carved_twice(
    client, case, pool, streams, tmp_path, session
):
    """A DHAV region (parser) plus a raw H.264 clip the parser cannot see (generic)."""
    dh = dhav_bytes(pool.get("h264_base_320"), channel=4)
    raw = streams["h264_high"]
    img = filler(2000, 1) + dh + b"\x00" * 128 + raw + b"\x00" * 128
    p = tmp_path / "mixed.dd"
    p.write_bytes(img)
    ev = acquire(client, case, p)
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    clips = [c for c in run["clips"] if c["kind"] == "clip"]
    assert {c["engine"] for c in clips} == {"Dahua", "generic"}
    parser_c = [c for c in clips if c["engine"] == "Dahua"]
    generic_c = [c for c in clips if c["engine"] == "generic"]
    assert len(parser_c) == 1 and parser_c[0]["channel"] == 4 and len(generic_c) == 1
    assert generic_c[0]["start_offset"] >= parser_c[0]["end_offset"]
    assert generic_c[0]["bitstream_sha256"] and generic_c[0]["decode_status"] == "ok"
    # no clip of either engine shares a start offset, and generic never overlaps a parser span
    starts = [c["start_offset"] for c in clips]
    assert len(starts) == len(set(starts))
    for g in generic_c:
        assert not any(
            g["start_offset"] < p_["end_offset"] and p_["start_offset"] < g["end_offset"]
            for p_ in parser_c
        )
    stats = run["stats"]
    assert stats["mode"] == "parser_first" and stats["generic_scope"] == "uncovered"
    assert stats["parser_covered_bytes"] > 0 and stats["generic_ranges"] == 2
    assert run["parsers"][0]["crosscheck"]["parser_clips"] == 1


def test_cleared_hikvision_entries_hide_video_from_the_parser_but_not_from_the_run(
    client, case, pool, tmp_path
):
    sc = next(s for s in SCENARIOS if s.id == "deleted_intact_zero@hik")
    img, truth = R.build_trial(sc, pool, 20260101, 0)
    p = tmp_path / "hik_cleared.dd"
    p.write_bytes(img)
    ev = acquire(client, case, p)
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    clips = [c for c in run["clips"] if c["kind"] == "clip"]
    # every truth clip lies inside some carved clip: nothing is lost although the parser misses some
    for t in truth["clips"]:
        lo, hi = t["pieces"][0][0], t["pieces"][-1][1]
        assert any(c["start_offset"] <= lo and hi <= c["end_offset"] for c in clips), t["id"]
    assert "generic" in {c["engine"] for c in clips}


def test_generic_scope_all_restores_the_full_generic_pass(client, case, pool, tmp_path):
    p = tmp_path / "dh.dd"
    p.write_bytes(filler(500, 2) + dhav_bytes(pool.get("h264_base_320")) + b"\x00" * 64)
    ev = acquire(client, case, p)
    run = client.post(f"/api/evidence/{ev['id']}/analyze", json={"generic_scope": "all"}).json()
    engines = [c["engine"] for c in run["clips"] if c["kind"] == "clip"]
    assert "Dahua" in engines and "generic" in engines  # overlap allowed only in this mode
    assert run["stats"]["generic_scope"] == "all" and run["params"]["generic_scope"] == "all"


def test_parser_fallback_means_generic_covers_the_whole_image(
    client, case, streams, tmp_path, monkeypatch
):
    from app.vendors import dahua_dhav

    monkeypatch.setattr(
        dahua_dhav.DhavParser, "_parse", lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))
    )
    p = tmp_path / "fb.dd"
    p.write_bytes(dhav_bytes(StreamPool().get("h264_base_320")))
    ev = acquire(client, case, p)
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    assert run["parsers"][0]["status"] == "fallback"
    assert run["stats"]["parser_covered_bytes"] == 0 and run["stats"]["generic_ranges"] == 1
    assert any(c["engine"] == "generic" and c["kind"] == "clip" for c in run["clips"])


def test_unknown_vendor_image_is_pure_generic(client, case, streams, tmp_path, session):
    p = tmp_path / "raw.dd"
    p.write_bytes(b"\x00" * 500 + streams["h264_main_b"] + b"\x00" * 500)
    ev = acquire(client, case, p)
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    assert run["parsers"] == [] and {c["engine"] for c in run["clips"]} == {"generic"}
    assert run["params"]["parser_options"] == {}
    assert all(c.engine == "generic" for c in session.scalars(select(Clip)))
