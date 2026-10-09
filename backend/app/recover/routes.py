import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException

import app as app_pkg
from app.carving.carve import CarveParams
from app.models import CarveRun, Clip
from app.recover.estimate import estimate, features_from_row, limitations
from app.routes import DbSession

router = APIRouter(prefix="/api")
VALIDATION_DIR = Path(app_pkg.__file__).resolve().parents[2] / "docs" / "validation"
RESULTS = VALIDATION_DIR / "results.json"
AGREEMENT = VALIDATION_DIR / "recoverability.json"


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text())


def load(path: Path) -> dict | None:
    try:
        return _load(str(path), path.stat().st_mtime)
    except (OSError, ValueError):
        return None


def reassembly_measurement() -> dict:
    res = load(RESULTS)
    if res is None:
        return {
            "available": False,
            "reason": f"validation results not found at {RESULTS} (run `make validate`)",
        }
    rows = [
        {
            "scenario": s["id"],
            "false_accept": s["metrics"]["reassembler_false_accept"],
            "true_accept": s["metrics"].get("reassembler_true_accept"),
            "trials": s["trials"],
            "layout": s["layout"],
        }
        for s in res["scenarios"]
        if "reassembler_false_accept" in s["metrics"]
    ]
    if not rows:
        return {"available": False, "reason": "no reassembler decisions in the validation results"}
    k = sum(r["false_accept"]["k"] for r in rows)
    n = sum(r["false_accept"]["n"] for r in rows)
    return {
        "available": True,
        "default": "off" if CarveParams().join_gap == 0 else "on",
        "enable_with": "analyze parameter join_gap > 0 (H.264 only)",
        "pooled_false_accept": {"k": k, "n": n, "rate": round(k / n, 4) if n else None},
        "scenarios": rows,
        "results_digest": res.get("results_digest"),
        "seed": res.get("seed"),
        "source": "docs/validation/results.json",
        "disclaimer": res.get("disclaimer", []),
        "note": "Measured on SYNTHETIC reference images only; the pooled rate mixes scenarios "
        "with very different decoy density (see per-scenario rows).",
    }


def agreement_summary() -> dict:
    res = load(AGREEMENT)
    if res is None:
        return {"available": False, "reason": f"measurement not found at {AGREEMENT}"}
    return {
        "available": True,
        "rule_version": res["rule_version"],
        "seed": res["seed"],
        "trials_per_scenario": res["trials_per_scenario"],
        "overall": res["overall"],
        "disclaimer": res["disclaimer"],
        "source": "docs/validation/recoverability.json (python -m app.recover.measure)",
    }


@router.get("/clips/{clip_id}/recoverability")
def clip_recoverability(clip_id: int, db: DbSession):
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    run = db.get(CarveRun, clip.run_id)
    params = json.loads(run.params_json) if run else {}
    ft = features_from_row(clip, params.get("validate_params"))
    est = estimate(ft)
    fa = reassembly_measurement()
    fa_rate = fa["pooled_false_accept"]["rate"] if fa.get("available") else None
    return {
        "clip_id": clip.id,
        "kind": clip.kind,
        "engine": clip.engine,
        **est,
        "limitations": limitations(ft, fa_rate),
        "measured_agreement": agreement_summary(),
    }


@router.get("/recovery/fragment-reassembly")
def fragment_reassembly():
    return reassembly_measurement()


@router.get("/recovery/agreement")
def recoverability_agreement():
    return agreement_summary()
