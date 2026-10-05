import random
from datetime import datetime, timedelta, timezone

import pytest

from app.timeline import drift as D
from app.timeline.timestamps import TimestampRecord

UTC = timezone.utc
T0 = datetime(2025, 3, 1, 8, 0, 0, tzinfo=UTC)


def synth(rng, offset, drift_ppm, n=5, span_days=20.0, noise=0.5):
    """Device times spread over span; true = device + offset + drift*x, reading noise +/-noise."""
    obs = []
    for i in range(n):
        x = span_days * 86400 * (i / (n - 1) if n > 1 else 0)
        dev = T0 + timedelta(seconds=x)
        err = offset + drift_ppm * 1e-6 * x + rng.uniform(-noise, noise)
        obs.append(D.Observation(dev, dev + timedelta(seconds=err), i + 1))
    return obs


def test_t_critical_values_match_tables():
    assert D.t_crit_975(1) == 12.706 and D.t_crit_975(10) == 2.228 and D.t_crit_975(30) == 2.042
    assert abs(D.t_crit_975(50) - 2.009) < 0.004  # tables: 2.009
    assert abs(D.t_crit_975(100) - 1.984) < 0.003  # tables: 1.984
    assert 1.960 < D.t_crit_975(100000) < 1.9605
    prev = 99.0
    for df in range(1, 400):  # monotone decreasing
        v = D.t_crit_975(df)
        assert v <= prev
        prev = v
    with pytest.raises(ValueError):
        D.t_crit_975(0)


def test_recovers_injected_offset_and_drift_with_truth_in_interval():
    trials, hit_a, hit_b, hit_c = 300, 0, 0, 0
    for seed in range(trials):
        rng = random.Random(seed)
        off = rng.uniform(-600, 600)
        ppm = rng.uniform(-80, 80)
        m = D.fit(synth(rng, off, ppm), reading_uncertainty_s=1.0)
        assert m.method == "linear" and m.usable
        hit_a += m.offset_ci_s[0] <= off <= m.offset_ci_s[1]
        lo, hi = m.drift_ci_ppm
        hit_b += lo <= ppm <= hi
        # the correction interval at a later device time must contain the true error there
        x = 30 * 86400
        c, hw = m.correction(T0 + timedelta(seconds=x))
        truth = off + ppm * 1e-6 * x
        hit_c += abs(c - truth) <= hw
    assert hit_a / trials >= 0.90, hit_a / trials
    assert hit_b / trials >= 0.90, hit_b / trials
    assert hit_c / trials >= 0.90, hit_c / trials


def test_point_estimates_close_with_low_noise():
    rng = random.Random(1)
    m = D.fit(synth(rng, 123.0, 42.0, n=8, noise=0.1), reading_uncertainty_s=0.2)
    assert abs(m.offset_s - 123.0) < 0.3 and abs(m.drift_ppm - 42.0) < 0.5
    assert len(m.residuals_s) == 8 and m.df == 6


def test_single_observation_is_offset_only_with_widening_and_warning():
    o = D.Observation(T0, T0 + timedelta(seconds=90))
    m = D.fit([o], reading_uncertainty_s=2.0, assumed_max_drift_ppm=100)
    assert m.method == "offset_only" and m.drift_ppm == 0 and m.drift_ci_ppm is None
    assert m.offset_s == 90 and m.offset_ci_s == (88, 92)
    assert any("single observation" in w for w in m.warnings)
    assert any("ASSUMED zero" in a for a in m.assumptions)
    c0, h0 = m.correction(T0)
    c1, h1 = m.correction(T0 + timedelta(days=10))
    assert c0 == c1 == 90 and h0 == 2.0
    assert h1 == pytest.approx(2.0 + 100e-6 * 864000)  # widens with distance (86.4 s)
    assert m.to_dict()["drift_assumed_zero"] is True


def test_identical_device_times_handled():
    obs = [D.Observation(T0, T0 + timedelta(seconds=s)) for s in (10, 12, 11)]
    m = D.fit(obs)
    assert m.method == "offset_only" and m.offset_s == pytest.approx(11)
    assert any("same device time" in w for w in m.warnings)


def test_two_points_exact_line_flags_no_dof():
    obs = [
        D.Observation(T0, T0 + timedelta(seconds=10)),
        D.Observation(T0 + timedelta(days=10), T0 + timedelta(days=10, seconds=18.64)),
    ]
    m = D.fit(obs)
    assert m.method == "linear" and m.df == 0
    assert m.drift_ppm == pytest.approx(10.0, rel=1e-6) and m.offset_s == pytest.approx(10)
    assert any("n = 2" in a for a in m.assumptions)
    assert m.drift_ci_ppm[0] < 10 < m.drift_ci_ppm[1]


def test_huge_drift_not_applied_and_large_drift_warns():
    obs = [
        D.Observation(T0, T0),
        D.Observation(T0 + timedelta(days=1), T0 + timedelta(days=1, seconds=3000)),
    ]
    m = D.fit(obs)
    assert m.drift_ppm > D.UNUSABLE_DRIFT_PPM and not m.usable
    assert any("implausible" in w for w in m.warnings)
    obs2 = [
        D.Observation(T0, T0),
        D.Observation(T0 + timedelta(days=10), T0 + timedelta(days=10, seconds=864 * 0.8)),
    ]
    m2 = D.fit(obs2)  # 800 ppm
    assert m2.usable and any("large drift" in w for w in m2.warnings)
    rec = _rec(T0 + timedelta(days=3))
    D.apply_correction(rec, m)
    assert rec.corrected_utc_lo is None and any("not applied" in n for n in rec.notes)


def test_non_monotonic_observations_warn_and_are_not_applied():
    obs = [
        D.Observation(T0, T0 + timedelta(seconds=5)),
        D.Observation(T0 + timedelta(days=1), T0 - timedelta(hours=1)),
        D.Observation(T0 + timedelta(days=2), T0 + timedelta(days=2, seconds=7)),
    ]
    m = D.fit(obs)
    assert not m.usable and any("non-monotonic" in w for w in m.warnings)


def test_short_baseline_warning_and_empty_input():
    obs = [
        D.Observation(T0, T0 + timedelta(seconds=3)),
        D.Observation(T0 + timedelta(minutes=5), T0 + timedelta(minutes=5, seconds=3)),
    ]
    assert any("short baseline" in w for w in D.fit(obs).warnings)
    with pytest.raises(ValueError):
        D.fit([])
    with pytest.raises(ValueError):
        D.fit([D.Observation(T0, T0)], reading_uncertainty_s=-1)


def _rec(lo):
    return TimestampRecord(raw=1, field="f", format="x", offset=0, source={},
                           utc_lo=lo, utc_hi=lo + timedelta(seconds=1))  # fmt: skip


def test_apply_correction_keeps_uncorrected_and_reports_both():
    m = D.fit([D.Observation(T0, T0 + timedelta(seconds=60))], reading_uncertainty_s=1.0)
    m.id = 7
    rec = _rec(T0 + timedelta(hours=1))
    D.apply_correction(rec, m)
    assert rec.utc_lo == T0 + timedelta(hours=1)  # unchanged
    assert rec.corrected_utc_lo < rec.utc_lo + timedelta(seconds=60) < rec.corrected_utc_hi
    assert rec.drift_model_id == 7
    unplaced = TimestampRecord(raw=1, field="f", format="x", offset=0, source={})
    D.apply_correction(unplaced, m)
    assert unplaced.corrected_utc_lo is None


def test_model_roundtrips_through_dict():
    rng = random.Random(3)
    m = D.fit(synth(rng, 5.0, 20.0))
    m2 = D.DriftModel.from_dict(m.to_dict())
    d = T0 + timedelta(days=4)
    assert m2.correction(d) == pytest.approx(m.correction(d))
