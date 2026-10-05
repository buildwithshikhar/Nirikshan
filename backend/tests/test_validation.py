import hashlib
import json
from pathlib import Path

import pytest

from app.validation import run as R
from app.validation import thresholds
from app.validation.image import BANNER, Builder
from app.validation.scenarios import SCENARIOS
from app.validation.score import Carved, _same_extents, score_image, wilson

BASELINE = Path(__file__).resolve().parents[2] / "docs" / "validation" / "results.json"
SEED = 20260101


@pytest.fixture(scope="module")
def pool():
    from app.validation.streams import StreamPool

    return StreamPool()


def by_id(i):
    return next(s for s in SCENARIOS if s.id == i)


# ---- determinism and SYNTHETIC marking -------------------------------------------------------


@pytest.mark.parametrize("sid", [s.id for s in SCENARIOS])
def test_same_seed_same_sha256_and_synthetic_marker(pool, sid):
    sc = by_id(sid)
    a, ta = R.build_trial(sc, pool, SEED, 0)
    b, tb = R.build_trial(sc, pool, SEED, 0)
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()
    assert json.dumps(ta, sort_keys=True) == json.dumps(tb, sort_keys=True)
    assert a.startswith(b"NIRIKSHAN SYNTHETIC TEST IMAGE") and a[: len(BANNER)] == BANNER
    assert ta["synthetic"] is True and ta["image_sha256"] == hashlib.sha256(a).hexdigest()
    assert "per-paper" not in ta["layout"] or "not a real device image" in ta["layout"]


def test_different_seed_or_trial_changes_the_image(pool):
    sc = by_id("zero_gaps")
    base = R.build_trial(sc, pool, SEED, 0)[0]
    assert R.build_trial(sc, pool, SEED + 1, 0)[0] != base
    assert R.build_trial(sc, pool, SEED, 1)[0] != base


def test_grouped_scenarios_share_identical_images(pool):
    a = R.build_trial(by_id("fragmented_zero_join_off"), pool, SEED, 2)[0]
    b = R.build_trial(by_id("fragmented_zero_join_on"), pool, SEED, 2)[0]
    assert a == b


def test_results_json_and_markdown_carry_the_disclaimers():
    res = R.run_all(SEED, 1, export=False, only={"clean_live", "neg_mjpeg"})
    assert res["synthetic"] is True and len(res["disclaimer"]) == 3
    md = R.to_markdown(res)
    first_page = "\n".join(md.splitlines()[:12])
    assert "SYNTHETIC" in first_page and "do NOT" in first_page and "predict" in first_page
    assert "circular check" in first_page and "not independent validation" in first_page
    assert "Tier A" in first_page


def test_results_digest_is_reproducible_and_ignores_timings():
    only = {"clean_live", "zero_gaps", "neg_encrypted_whole"}
    a = R.run_all(SEED, 2, export=False, only=only)
    b = R.run_all(SEED, 2, export=False, only=only)
    assert a["results_digest"] == b["results_digest"] == R.digest(a)
    b["scenarios"][0]["seconds"] = 999
    assert R.digest(b) == a["results_digest"]
    assert R.run_all(SEED + 1, 2, export=False, only=only)["results_digest"] != a["results_digest"]


# ---- ground truth ----------------------------------------------------------------------------


def test_truth_marks_survivors_by_byte_comparison(pool):
    img, t = R.build_trial(by_id("partial_overwrite_zero"), pool, SEED, 0)
    v = next(c for c in t["clips"] if c["id"] == "V")
    assert v["frames_recoverable"] < v["frames_total"]
    for n in v["nals"]:
        if n["img_off"] is not None and n["intact"]:
            src = pool.get(v["variant"]).data
            assert img[n["img_off"] : n["img_off"] + n["len"]] in src
    s = next(c for c in t["clips"] if c["id"] == "S")
    assert s["frames_recoverable"] == s["frames_total"] and all(n["intact"] for n in s["nals"])


def test_recoverable_requires_params_and_gop_prefix(pool):
    stream = pool.get("h264_base_320")
    b = Builder(__import__("random").Random(1))
    b.clip("A", stream)
    s, e = b.place("A")
    sps = next(n for n in stream.nals if n.param)
    b.overwrite(s + sps.start, b"\x01" * 8)  # damage first GOP's SPS
    _, t = b.build()
    nals = t["clips"][0]["nals"]
    g0 = [n for n in nals if n["gop"] == 0 and n["vcl"]]
    g1 = [n for n in nals if n["gop"] == 1 and n["vcl"]]
    assert not any(n["recoverable"] for n in g0) and all(n["recoverable"] for n in g1)


# ---- scorer ----------------------------------------------------------------------------------


def _truth_img(pool):
    b = Builder(__import__("random").Random(3))
    b.zeros(100)
    b.clip("A", pool.get("h264_base_320"))
    s, e = b.place("A")
    b.zeros(100)
    img, truth = b.build()
    return img, truth, s, e


def test_scorer_perfect_empty_and_false_positive(pool):
    img, truth, s, e = _truth_img(pool)
    perfect = score_image(truth, [Carved("h264", [[s, e]])], img, "t")
    assert (perfect.truth_detected, perfect.tp, perfect.exact) == (1, 1, 1)
    assert perfect.frames_recovered == perfect.frames_recoverable > 0 and perfect.extra_bytes == 0
    empty = score_image(truth, [], img, "t")
    assert (
        empty.truth_detected == 0
        and empty.carved == 0
        and empty.failures[0]["kind"] == "missed_clip"
    )
    fp = score_image(truth, [Carved("h264", [[0, 90]])], img, "t")
    assert fp.tp == 0 and any(f["kind"] == "false_positive_clip" for f in fp.failures)


def test_scorer_partial_and_zero_tolerant_exactness(pool):
    img, truth, s, e = _truth_img(pool)
    half = score_image(truth, [Carved("h264", [[s, (s + e) // 2]])], img, "t")
    assert 0 < half.frames_recovered < half.frames_recoverable and half.exact == 0
    assert _same_extents([[s - 1, e]], [[s, e]], img) and _same_extents([[s, e + 1]], [[s, e]], img)
    assert not _same_extents([[s + 5, e]], [[s, e]], img)  # non-zero bytes differ


def test_scorer_hash_integrity_detects_a_wrong_recorded_hash(pool):
    img, truth, s, e = _truth_img(pool)
    good = hashlib.sha256(img[s:e]).hexdigest()
    ok = score_image(truth, [Carved("h264", [[s, e]], recorded_sha256=good, mp4_ok=True)], img, "t")
    bad = score_image(truth, [Carved("h264", [[s, e]], recorded_sha256="0" * 64)], img, "t")
    assert (ok.hash_checked, ok.hash_ok, bad.hash_checked, bad.hash_ok) == (1, 1, 1, 0)


def test_scorer_negative_image_counts_emitted_clips(pool):
    img, truth = R.build_trial(by_id("neg_encrypted_whole"), pool, SEED, 0)
    c = score_image(truth, [Carved("h264", [[300, 900]], decode_status="decode_errors")], img, "t")
    assert (c.neg_clips, c.neg_decode_ok, c.decode_errors) == (1, 0, 1)


def test_wilson_interval():
    assert wilson(0, 0) is None
    lo, hi = wilson(50, 100)
    assert 0.39 < lo < 0.41 and 0.59 < hi < 0.61
    assert wilson(10, 10)[1] == 1.0


# ---- regression thresholds -------------------------------------------------------------------


def test_threshold_checker_flags_violations():
    res = {
        "scenarios": [
            {"id": "x", "metrics": {"a": {"k": 1, "n": 2, "rate": 0.5}, "b": {"k": 3, "n": 3}}}
        ]
    }
    th = {"x": {"a": {"min": 0.6}, "b": {"max_k": 2}, "c": {"min": 1}}}
    v = thresholds.check(res, th)
    assert len(v) == 3 and any("min 0.6" in s for s in v) and any("k=3" in s for s in v)
    assert thresholds.check(res, {"x": {"a": {"min": 0.4}}, "gone": {"a": {"min": 1}}}) == []


def test_regression_thresholds_hold_on_a_fresh_run():
    """CI guard: full matrix, 3 trials, ffmpeg export + decode test."""
    res = R.run_all(SEED, 3, export=True)
    assert thresholds.check(res) == []
    neg = [s for s in res["scenarios"] if s["kind"] == "negative"]
    assert neg and all(s["metrics"]["clips_decoded_ok"]["k"] == 0 for s in neg)
    assert all(s["failure_count"] >= 0 for s in res["scenarios"])


def test_committed_baseline_is_intact_synthetic_and_within_thresholds():
    res = json.loads(BASELINE.read_text())
    assert res["synthetic"] is True and res["seed"] == SEED and res["trials"] >= 20
    assert R.digest(res) == res["results_digest"], "baseline was edited by hand"
    assert thresholds.check(res) == []
    md = BASELINE.with_suffix(".md").read_text()
    assert "SYNTHETIC" in md[:600] and "circular check" in md[:900]
