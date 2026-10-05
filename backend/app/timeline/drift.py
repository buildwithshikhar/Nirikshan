"""Clock offset / drift model from reference observations (P5, SWGDE 17-V-002-1.4 workflow).

An observation pairs a DEVICE time (what the DVR clock showed, converted to a UTC instant with
the examiner's timezone assumption) with the TRUE time (UTC, established by the examiner by
photo of the DVR clock vs an NTP-synced reference, a known event, ...).

Model: error(x) = true - device = a + b * x, x = device time - x0 (seconds), x0 = the earliest
observation's device time. Corrected time = device + a + b * x. Reported with 95 % intervals.

  * 1 observation (or all at the same device time): PURE OFFSET. Drift is ASSUMED zero, which is
    an assumption, not a measurement; the interval is widened by `assumed_max_drift_ppm` times
    the distance (in time) from the observation, plus the reading uncertainty.
  * >= 2 observations at different device times: ordinary least squares.
      n == 2 : zero residual degrees of freedom. The interval uses sigma = reading
               uncertainty / sqrt(3) (uniform +/-u reading error) and the normal critical value
               1.96; this is a propagated-reading-error interval, not a residual-based one.
      n >= 3 : sigma = max(residual std, u / sqrt(3)) (the floor stops a lucky near-perfect fit
               from claiming a zero-width interval) and Student t critical values (df = n - 2,
               95 % two-sided, table below; no scipy).
  * Not modelled: clock steps, NTP adjustments, temperature-dependent drift (a linear model is
    used); non-monotonic or implausible fits are reported with warnings and are NOT applied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.timeline.timestamps import TimestampRecord, iso, parse_iso_utc

# Two-sided 95 % Student t critical values (standard tables), df -> t.
_T975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
    9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120,
    17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
    40: 2.021, 60: 2.000, 120: 1.980,
}  # fmt: skip
Z975 = 1.960
HUGE_DRIFT_WARN_PPM = 500.0
UNUSABLE_DRIFT_PPM = 10_000.0
SHORT_BASELINE_S = 3600.0


def t_crit_975(df: int) -> float:
    """Two-sided 95 % t critical value; linear interpolation in 1/df between table rows."""
    if df < 1:
        raise ValueError("df must be >= 1")
    if df in _T975:
        return _T975[df]
    keys = sorted(_T975)
    if df > keys[-1]:
        lo, hi, vlo, vhi = keys[-1], None, _T975[keys[-1]], Z975
        inv_hi = 0.0
    else:
        lo = max(k for k in keys if k < df)
        hi = min(k for k in keys if k > df)
        vlo, vhi, inv_hi = _T975[lo], _T975[hi], 1.0 / hi
    inv_lo, inv = 1.0 / lo, 1.0 / df
    w = (inv - inv_lo) / (inv_hi - inv_lo)
    return vlo + w * (vhi - vlo)


@dataclass
class Observation:
    device_utc: datetime
    true_utc: datetime
    id: int | None = None


@dataclass
class DriftModel:
    method: str  # offset_only | linear
    n: int
    x0: datetime  # reference device time (UTC instant)
    offset_s: float  # true - device at x0
    offset_ci_s: tuple[float, float]
    drift_ppm: float  # 0 and ASSUMED for offset_only
    drift_ci_ppm: tuple[float, float] | None
    sigma_s: float
    df: int
    t_critical: float
    residuals_s: list[float]
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    usable: bool = True
    reading_uncertainty_s: float = 1.0
    assumed_max_drift_ppm: float = 100.0
    observation_ids: list[int | None] = field(default_factory=list)
    sxx: float = 0.0
    xbar: float = 0.0
    id: int | None = None  # database id once stored

    def _x(self, device_utc: datetime) -> float:
        return (device_utc - self.x0).total_seconds()

    def correction(self, device_utc: datetime) -> tuple[float, float]:
        """(central correction in seconds, 95 % half-width in seconds) at a device time."""
        x = self._x(device_utc)
        b = self.drift_ppm * 1e-6
        centre = self.offset_s + b * x
        if self.method == "offset_only":
            base = (self.offset_ci_s[1] - self.offset_ci_s[0]) / 2
            return centre, base + self.assumed_max_drift_ppm * 1e-6 * abs(x - self.xbar)
        hw = (
            self.t_critical
            * self.sigma_s
            * math.sqrt(1.0 / self.n + (x - self.xbar) ** 2 / self.sxx)
        )
        return centre, hw

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "method": self.method,
            "n": self.n,
            "x0": iso(self.x0),
            "offset_s": self.offset_s,
            "offset_ci_s": list(self.offset_ci_s),
            "drift_ppm": self.drift_ppm,
            "drift_ci_ppm": list(self.drift_ci_ppm) if self.drift_ci_ppm else None,
            "drift_assumed_zero": self.method == "offset_only",
            "sigma_s": self.sigma_s,
            "df": self.df,
            "t_critical": self.t_critical,
            "confidence": 0.95,
            "residuals_s": self.residuals_s,
            "warnings": self.warnings,
            "assumptions": self.assumptions,
            "usable": self.usable,
            "reading_uncertainty_s": self.reading_uncertainty_s,
            "assumed_max_drift_ppm": self.assumed_max_drift_ppm,
            "observation_ids": self.observation_ids,
            "sxx": self.sxx,
            "xbar": self.xbar,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DriftModel:
        return cls(
            method=d["method"],
            n=d["n"],
            x0=parse_iso_utc(d["x0"]),
            offset_s=d["offset_s"],
            offset_ci_s=tuple(d["offset_ci_s"]),
            drift_ppm=d["drift_ppm"],
            drift_ci_ppm=tuple(d["drift_ci_ppm"]) if d.get("drift_ci_ppm") else None,
            sigma_s=d["sigma_s"],
            df=d["df"],
            t_critical=d["t_critical"],
            residuals_s=d["residuals_s"],
            warnings=d.get("warnings", []),
            assumptions=d.get("assumptions", []),
            usable=d.get("usable", True),
            reading_uncertainty_s=d.get("reading_uncertainty_s", 1.0),
            assumed_max_drift_ppm=d.get("assumed_max_drift_ppm", 100.0),
            observation_ids=d.get("observation_ids", []),
            sxx=d.get("sxx", 0.0),
            xbar=d.get("xbar", 0.0),
            id=d.get("id"),
        )


def fit(
    observations: list[Observation],
    reading_uncertainty_s: float = 1.0,
    assumed_max_drift_ppm: float = 100.0,
) -> DriftModel:
    """Fit the offset/drift model. Raises ValueError for an empty observation list."""
    if not observations:
        raise ValueError("at least one reference observation is required")
    if reading_uncertainty_s < 0 or assumed_max_drift_ppm < 0:
        raise ValueError("uncertainty parameters must be >= 0")
    obs = sorted(observations, key=lambda o: o.device_utc)
    x0 = obs[0].device_utc
    xs = [(o.device_utc - x0).total_seconds() for o in obs]
    ys = [(o.true_utc - o.device_utc).total_seconds() for o in obs]
    n = len(obs)
    u = reading_uncertainty_s
    sd_read = u / math.sqrt(3.0)
    warnings: list[str] = []
    assumptions = [
        f"each reading is uncertain by +/-{u:g} s (uniform; sd {sd_read:.3f} s)",
        "linear clock error (constant drift); clock steps and NTP slews are not modelled",
        "device times were converted to UTC with the examiner-entered timezone assumption",
    ]
    ids = [o.id for o in obs]

    # non-monotonic: true time must increase with device time
    for (d1, t1), (d2, t2) in zip(
        ((o.device_utc, o.true_utc) for o in obs[:-1]),
        ((o.device_utc, o.true_utc) for o in obs[1:]),
        strict=True,
    ):
        if d2 > d1 and t2 <= t1:
            warnings.append(
                "non-monotonic observations: true time does not increase with device time "
                "(clock step, wrong timezone or a mislabelled observation); fit not applied"
            )
            break
        if d2 == d1 and t2 != t1:
            warnings.append("two observations share a device time but have different true times")
            break
    non_monotonic = any(w.startswith("non-monotonic") for w in warnings)

    sxx = sum((x - sum(xs) / n) ** 2 for x in xs)
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    if n == 1 or sxx == 0.0:
        if n > 1:
            warnings.append(
                "all observations are at the same device time: drift cannot be estimated; "
                "using the mean offset"
            )
        else:
            warnings.append("single observation: drift cannot be estimated")
        assumptions.append(
            f"drift ASSUMED zero (not measured); interval widened by +/-{assumed_max_drift_ppm:g} "
            "ppm x time distance from the observation (an assumed bound, not a measurement)"
        )
        resid = [y - ybar for y in ys]
        if n > 1:
            df = n - 1
            s = math.sqrt(sum(r * r for r in resid) / df)
            sigma = max(s, sd_read)
            tc = t_crit_975(df)
            half = tc * sigma / math.sqrt(n)
        else:
            df, sigma, tc = 0, sd_read, Z975
            half = u  # full uniform reading bound
        return DriftModel(
            "offset_only", n, x0, ybar, (ybar - half, ybar + half), 0.0, None, sigma, df, tc,
            resid, warnings, assumptions, not non_monotonic, u, assumed_max_drift_ppm, ids,
            sxx, xbar,
        )  # fmt: skip

    b = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys, strict=True)) / sxx
    a_c = ybar - b * xbar  # intercept at x = 0 (= x0)
    resid = [y - (a_c + b * x) for x, y in zip(xs, ys, strict=True)]
    df = n - 2
    if df >= 1:
        s = math.sqrt(sum(r * r for r in resid) / df)
        sigma, tc = max(s, sd_read), t_crit_975(df)
    else:
        sigma, tc = sd_read, Z975
        assumptions.append(
            "n = 2: no residual degrees of freedom; interval from the reading uncertainty only "
            "(sigma = u/sqrt(3), z = 1.96), so it does not reflect real clock non-linearity"
        )
    se_b = sigma / math.sqrt(sxx)
    se_a = sigma * math.sqrt(1.0 / n + xbar**2 / sxx)
    drift_ppm = b * 1e6
    usable = not non_monotonic
    if abs(drift_ppm) >= UNUSABLE_DRIFT_PPM:
        usable = False
        warnings.append(
            f"implausible drift {drift_ppm:.0f} ppm (>= {UNUSABLE_DRIFT_PPM:.0f}); likely a clock "
            "step, wrong timezone or mislabelled observation; fit not applied"
        )
    elif abs(drift_ppm) > HUGE_DRIFT_WARN_PPM:
        warnings.append(
            f"large drift {drift_ppm:.0f} ppm (> {HUGE_DRIFT_WARN_PPM:.0f}); far above typical "
            "crystal tolerances (engineering expectation, not a sourced figure); check inputs"
        )
    if xs[-1] < SHORT_BASELINE_S:
        warnings.append(
            f"short baseline ({xs[-1]:.0f} s < {SHORT_BASELINE_S:.0f} s): drift is poorly "
            "constrained and extrapolation will be wide"
        )
    return DriftModel(
        "linear", n, x0, a_c, (a_c - tc * se_a, a_c + tc * se_a), drift_ppm,
        ((b - tc * se_b) * 1e6, (b + tc * se_b) * 1e6), sigma, df, tc, resid, warnings,
        assumptions, usable, u, assumed_max_drift_ppm, ids, sxx, xbar,
    )  # fmt: skip


def apply_correction(rec: TimestampRecord, model: DriftModel | None) -> TimestampRecord:
    """Fill corrected_utc_lo/hi (uncorrected values stay). Skips unplaceable records and
    unusable models; the reason is appended to the record notes."""
    if model is None or not rec.placeable:
        return rec
    if not model.usable:
        rec.notes.append("drift model not applied (unusable, see model warnings)")
        return rec
    assert rec.utc_lo is not None and rec.utc_hi is not None
    c_lo, h_lo = model.correction(rec.utc_lo)
    c_hi, h_hi = model.correction(rec.utc_hi)
    rec.corrected_utc_lo = rec.utc_lo + timedelta(seconds=c_lo - h_lo)
    rec.corrected_utc_hi = rec.utc_hi + timedelta(seconds=c_hi + h_hi)
    rec.drift_model_id = model.id
    return rec
