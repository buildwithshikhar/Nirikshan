"""Measure the recoverability rule against ground truth on the reference (SYNTHETIC) images.

    python -m app.recover.measure --seed 20260101 --trials 10 \
        --out ../docs/validation/recoverability.json

For every scenario that runs the generic engine with export enabled, each trial image is built by
the validation harness, carved by the generic carver and every clip is exported + decode-tested
exactly as in analysis. The rule (app.recover.estimate) is applied to the same features the API
uses, and compared with the ACTUAL recovered-frame fraction from ground truth:

    actual = (recoverable VCL NAL units of the clip's attributed truth clip that lie wholly inside
              the clip's extents) / (VCL NAL units the carver counted in the clip), capped at 1

'Recoverable' is the harness definition: the NAL unit, its GOP's parameter sets and every earlier
VCL NAL unit of that GOP survived intact. The attributed truth clip is the one with the largest
byte overlap. Nothing is tuned: the rule's factors are constants fixed before this was run.
"""

import argparse
import io
import json
import math
import sys
import tempfile
from pathlib import Path

from app import __version__
from app.carving import nal
from app.carving.carve import CarveParams, Carver
from app.carving.carve import Clip as CarvedClip
from app.carving.export import export_clip, ffmpeg_version
from app.recover.estimate import RULE_VERSION, band, estimate
from app.validation.run import build_trial
from app.validation.scenarios import SCENARIOS
from app.validation.streams import StreamPool

DISCLAIMER = (
    "SYNTHETIC reference images only (built from published research and open-source format "
    "documentation, with known ground truth). Agreement here does not predict agreement on real "
    "DVR/NVR images. No vendor is above Tier B; nothing is validated on a real device."
)


def _norm(ext):
    out = []
    for s, e in sorted(ext):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _overlap(a, b) -> int:
    return sum(max(0, min(e1, e2) - max(s1, s2)) for s1, e1 in a for s2, e2 in b)


def actual_fraction(truth: dict, clip: CarvedClip) -> tuple[float, str | None]:
    ext = _norm([list(e) for e in clip.extents])
    best, best_ov = None, 0
    for t in truth["clips"]:
        ov = _overlap(ext, _norm([[p[0], p[1]] for p in t["pieces"]]))
        if ov > best_ov:
            best, best_ov = t, ov
    if best is None or clip.vcl_count == 0:
        return 0.0, None
    inside = sum(
        1
        for n in best["nals"]
        if n["vcl"]
        and n["recoverable"]
        and n["img_off"] is not None
        and any(s <= n["img_off"] and n["img_off"] + n["len"] <= e for s, e in ext)
    )
    return min(1.0, inside / clip.vcl_count), best["id"]


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx == 0 or sy == 0:
        return None
    return round(sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / (sx * sy), 4)


def stats(rows: list[dict]) -> dict:
    est = [r["estimate"] for r in rows]
    act = [r["actual"] for r in rows]
    n = len(rows)
    bands = {}
    for b in ("high", "medium", "low"):
        sel = [r for r in rows if r["band"] == b]
        bands[b] = {
            "clips": len(sel),
            "mean_estimate": round(sum(r["estimate"] for r in sel) / len(sel), 4) if sel else None,
            "mean_actual": round(sum(r["actual"] for r in sel) / len(sel), 4) if sel else None,
            "actual_ge_0_9": sum(1 for r in sel if r["actual"] >= 0.9),
            "actual_lt_0_5": sum(1 for r in sel if r["actual"] < 0.5),
        }
    return {
        "clips": n,
        "pearson_r": pearson(est, act),
        "spearman_rho": pearson(_ranks(est), _ranks(act)) if n >= 3 else None,
        "mean_absolute_error": round(sum(abs(a - b) for a, b in zip(est, act, strict=True)) / n, 4)
        if n
        else None,
        "mean_signed_error_estimate_minus_actual": round(
            sum(a - b for a, b in zip(est, act, strict=True)) / n, 4
        )
        if n
        else None,
        "band_agreement": round(sum(1 for r in rows if band(r["actual"]) == r["band"]) / n, 4)
        if n
        else None,
        "by_band": bands,
    }


def run(seed: int, trials: int, only: set[str] | None = None) -> dict:
    pool = StreamPool()
    rows: list[dict] = []
    per_scenario = []
    for sc in SCENARIOS:
        if "generic" not in sc.engines or not sc.export or (only and sc.id not in only):
            continue
        params = CarveParams(**sc.carve)
        sc_rows = []
        for i in range(trials):
            img, truth = build_trial(sc, pool, seed, i)
            carver = Carver(lambda o, n, img=img: img[o : o + n], params)
            f = io.BytesIO(img)
            with tempfile.TemporaryDirectory() as tmp:
                for k, item in enumerate(carver.run(nal.scan(io.BytesIO(img), len(img)))):
                    if not isinstance(item, CarvedClip):
                        continue
                    ex = export_clip(f, item.extents, item.codec, Path(tmp), f"m{k}")
                    ft = {
                        "kind": "clip",
                        "engine": "generic",
                        "codec": item.codec,
                        "decode_status": ex.decode_status,
                        "decode_errors": ex.decode_errors,
                        "irap_count": item.irap_count,
                        "vcl_count": item.vcl_count,
                        "nal_count": item.nal_count,
                        "reassembled": item.reassembled,
                        "extent_count": len(item.extents),
                        "end_reason": item.end_reason,
                        "validate_params": params.validate_params,
                    }
                    e = estimate(ft)
                    if not e["available"]:
                        continue
                    act, tid = actual_fraction(truth, item)
                    sc_rows.append(
                        {
                            "scenario": sc.id,
                            "trial": i,
                            "estimate": e["estimate"],
                            "band": e["band"],
                            "actual": round(act, 4),
                            "decode_status": ex.decode_status,
                            "reassembled": item.reassembled,
                            "attributed_truth_clip": tid,
                        }
                    )
        rows += sc_rows
        per_scenario.append({"scenario": sc.id, "kind": sc.kind, **stats(sc_rows)})
    res = {
        "synthetic": True,
        "disclaimer": DISCLAIMER,
        "rule_version": RULE_VERSION,
        "tool_version": __version__,
        "ffmpeg": ffmpeg_version(),
        "seed": seed,
        "trials_per_scenario": trials,
        "engine": "generic",
        "actual_definition": (
            "recoverable VCL NAL units of the attributed truth clip wholly inside the clip "
            "extents / VCL NAL units counted in the clip (capped at 1)"
        ),
        "overall": stats(rows),
        "by_scenario": per_scenario,
        "clips": rows,
    }
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recoverability-measure")
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    res = run(a.seed, a.trials, set(a.only) if a.only else None)
    print(json.dumps(res["overall"], indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
