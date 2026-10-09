"""Performance analytics computed from stored run records only (method: docs/performance.md).

Nothing here is estimated or invented: every number is a stored timing, a count of stored rows,
or arithmetic on them. When an input is missing the result says so ({"available": false,
"reason": ...}) instead of substituting a value.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.models import AnalyticsRun
from app.jobs.models import Job
from app.models import CarveRun, Clip, Evidence
from app.perf.models import TASKS, ManualBaseline

DOMINANT_SHARE = 0.5
MIN_TOTAL_S = 0.05
BOTTLENECK_RULE = (
    "The bottleneck is the stage with the largest share of the run's measured wall-clock time "
    f"(finished_at - started_at). It is called dominant when that share is >= {DOMINANT_SHARE}. "
    f"Runs shorter than {MIN_TOTAL_S} s get no bottleneck (timer resolution and noise)."
)
RATES_NOTE = (
    "Rates describe this tool's own stored output (how many detected segments became clips, "
    "how many clips exported and decoded cleanly). They are not accuracy: there is no ground "
    "truth for casework images. Measured accuracy on reference test data is in "
    "docs/VALIDATION.md."
)


def _secs(a: str, b: str) -> float | None:
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()
    except (TypeError, ValueError):
        return None


def _job_for_run(db: Session, run_id: int) -> Job | None:
    return db.scalars(select(Job).where(Job.run_id == run_id).order_by(Job.id.desc())).first()


def run_breakdown(db: Session, run: CarveRun) -> dict:
    stats = json.loads(run.stats_json or "{}")
    total = _secs(run.started_at, run.finished_at)
    stages: dict[str, float] = {
        "identify": run.ident_seconds or 0.0,
        "parse_and_export_parser_clips": float(stats.get("parse_seconds", 0.0)),
        "generic_carve_and_export": run.carve_seconds or 0.0,
    }
    if "crosscheck_seconds" in stats:
        stages["crosscheck"] = float(stats["crosscheck_seconds"])
    job = _job_for_run(db, run.id)
    timings = json.loads(job.timings_json) if job is not None and job.timings_json else {}
    isolated = bool(stats.get("isolated_worker"))
    worker = stats.get("worker_timings") or {}
    if isolated and "worker_wall_s" in timings:
        inner = sum(
            float(worker.get(k, 0.0)) for k in ("identify", "parse", "carve", "crosscheck_pass")
        )
        # worker start-up, image re-hash inside the worker and result transfer
        stages["worker_startup_hash_and_transfer"] = max(
            0.0, float(timings["worker_wall_s"]) - inner
        )
    out = {
        "run_id": run.id,
        "evidence_id": run.evidence_id,
        "status": run.status,
        "tool_version": run.tool_version,
        "isolated_worker": isolated,
        "params": json.loads(run.params_json or "{}"),
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "total_seconds": total,
        "bytes_scanned": stats.get("bytes_scanned"),
    }
    if total is None or total <= 0:
        out.update(
            stages={k: round(v, 6) for k, v in stages.items()},
            bottleneck={"available": False, "reason": "run has no finished_at (not completed)"},
        )
        return out
    accounted = sum(stages.values())
    stages["other (image verification, database, custody signing)"] = max(0.0, total - accounted)
    out["stage_sum_exceeds_total"] = accounted > total * 1.01  # should never be true
    out["stages"] = {
        k: {"seconds": round(v, 6), "share": round(v / total, 4)} for k, v in stages.items()
    }
    if out["bytes_scanned"]:
        out["throughput_mib_per_s"] = round(out["bytes_scanned"] / (1024 * 1024) / total, 3)
    if total < MIN_TOTAL_S:
        out["bottleneck"] = {"available": False, "reason": f"run shorter than {MIN_TOTAL_S} s"}
    else:
        name, sec = max(stages.items(), key=lambda kv: kv[1])
        share = sec / total
        out["bottleneck"] = {
            "available": True,
            "stage": name,
            "seconds": round(sec, 6),
            "share": round(share, 4),
            "dominant": share >= DOMINANT_SHARE,
        }
    return out


def _comparisons(db: Session, runs: list[CarveRun], breakdowns: dict[int, dict]) -> list[dict]:
    """Group completed runs by (evidence SHA-256, parameters); compare each later run with the
    earliest one of its group."""
    groups: dict[tuple, list[CarveRun]] = {}
    for r in runs:
        if r.status != "completed" or breakdowns[r.id].get("total_seconds") is None:
            continue
        ev = db.get(Evidence, r.evidence_id)
        key = (ev.sha256 if ev else str(r.evidence_id), r.params_json)
        groups.setdefault(key, []).append(r)
    out = []
    for (sha, params), rs in groups.items():
        if len(rs) < 2:
            continue
        rs.sort(key=lambda r: (r.started_at, r.id))
        base = breakdowns[rs[0].id]
        cmp = []
        for r in rs[1:]:
            b = breakdowns[r.id]
            stage_delta = {
                k: round(v["seconds"] - base["stages"].get(k, {}).get("seconds", 0.0), 6)
                for k, v in b["stages"].items()
            }
            cmp.append(
                {
                    "run_id": r.id,
                    "total_seconds": b["total_seconds"],
                    "delta_seconds": round(b["total_seconds"] - base["total_seconds"], 6),
                    "ratio_to_baseline": round(b["total_seconds"] / base["total_seconds"], 4),
                    "stage_delta_seconds": stage_delta,
                    "same_tool_version": r.tool_version == rs[0].tool_version,
                    "isolated_worker": b["isolated_worker"],
                }
            )
        out.append(
            {
                "evidence_sha256": sha,
                "params": json.loads(params),
                "baseline_run_id": rs[0].id,
                "baseline_total_seconds": base["total_seconds"],
                "runs": cmp,
            }
        )
    return out


def _rate(num: int, den: int) -> dict:
    if den == 0:
        return {"available": False, "reason": "no items to count", "numerator": 0, "denominator": 0}
    return {"available": True, "rate": round(num / den, 4), "numerator": num, "denominator": den}


def success_rates(db: Session, case_id: int, runs: list[CarveRun]) -> dict:
    completed = [r.id for r in runs if r.status == "completed"]
    if not completed:
        return {"available": False, "reason": "no completed runs in this case"}
    clips = db.scalars(select(Clip).where(Clip.run_id.in_(completed))).all()
    real = [c for c in clips if c.kind == "clip"]
    orphans = [c for c in clips if c.kind == "orphan"]
    exportable = [c for c in real if c.decode_status != "not_exported"]
    ok = [c for c in exportable if c.decode_status == "ok"]
    decode_err = [c for c in exportable if c.decode_status == "decode_errors"]
    aruns = db.scalars(select(AnalyticsRun).where(AnalyticsRun.case_id == case_id)).all()
    return {
        "available": True,
        "runs_counted": len(completed),
        "segment_recovery": {
            **_rate(len(real), len(real) + len(orphans)),
            "definition": "clips / (clips + orphan ranges) over completed runs",
        },
        "extraction_clean": {
            **_rate(len(ok), len(exportable)),
            "definition": "clips exported AND decoded without errors / exportable clips",
        },
        "extraction_any": {
            **_rate(len(ok) + len(decode_err), len(exportable)),
            "definition": "clips exported (with or without decode errors) / exportable clips",
        },
        "analytics_completed": {
            **_rate(sum(a.status == "completed" for a in aruns), len(aruns)),
            "definition": "completed analytics runs / analytics runs",
        },
        "note": RATES_NOTE,
    }


def _latest_runs_per_target(db: Session, case_id: int) -> dict[str, list[float]]:
    """Tool seconds per task: the latest completed run per evidence item (analyze) and per
    (clip, kind) (analytics), so re-runs are not double counted."""
    out: dict[str, list[float]] = {"analyze": [], "analytics": []}
    seen: set = set()
    for r in db.scalars(
        select(CarveRun)
        .where(CarveRun.case_id == case_id, CarveRun.status == "completed")
        .order_by(CarveRun.id.desc())
    ):
        if r.evidence_id in seen:
            continue
        seen.add(r.evidence_id)
        s = _secs(r.started_at, r.finished_at)
        if s is not None:
            out["analyze"].append(s)
    seen = set()
    for a in db.scalars(
        select(AnalyticsRun)
        .where(AnalyticsRun.case_id == case_id, AnalyticsRun.status == "completed")
        .order_by(AnalyticsRun.id.desc())
    ):
        if (a.clip_id, a.kind) in seen:
            continue
        seen.add((a.clip_id, a.kind))
        s = _secs(a.started_at, a.finished_at)
        if s is not None:
            out["analytics"].append(s)
    return out


def latest_baseline(db: Session, case_id: int, task: str) -> ManualBaseline | None:
    return db.scalars(
        select(ManualBaseline)
        .where(ManualBaseline.case_id == case_id, ManualBaseline.task == task)
        .order_by(ManualBaseline.id.desc())
    ).first()


def time_saved(db: Session, case_id: int) -> dict:
    tool = _latest_runs_per_target(db, case_id)
    out = {}
    for task in TASKS:
        b = latest_baseline(db, case_id, task)
        if b is None:
            out[task] = {"available": False, "reason": "no manual baseline entered"}
            continue
        if not tool[task]:
            out[task] = {
                "available": False,
                "reason": f"no completed {task} run in this case to compare with",
                "manual_seconds": b.manual_seconds,
            }
            continue
        t = sum(tool[task])
        out[task] = {
            "available": True,
            "manual_seconds": b.manual_seconds,
            "manual_basis": b.basis,
            "manual_entered_by": b.entered_by,
            "manual_entered_at": b.entered_at,
            "tool_seconds": round(t, 6),
            "tool_runs_counted": len(tool[task]),
            "time_saved_seconds": round(b.manual_seconds - t, 6),
            "speedup": round(b.manual_seconds / t, 3) if t > 0 else None,
            "limits": (
                "tool_seconds is machine processing time only; examiner review of the output "
                "is not measured, so the saving is an upper bound. The manual figure is what "
                "the examiner entered; it is not verified by the tool."
            ),
        }
    return out


def case_performance(db: Session, case_id: int) -> dict:
    runs = list(
        db.scalars(select(CarveRun).where(CarveRun.case_id == case_id).order_by(CarveRun.id))
    )
    breakdowns = {r.id: run_breakdown(db, r) for r in runs}
    return {
        "case_id": case_id,
        "runs": [breakdowns[r.id] for r in runs],
        "bottleneck_rule": BOTTLENECK_RULE,
        "baseline_comparisons": _comparisons(db, runs, breakdowns),
        "success_rates": success_rates(db, case_id, runs),
        "time_saved": time_saved(db, case_id),
        "method": "docs/performance.md",
    }
