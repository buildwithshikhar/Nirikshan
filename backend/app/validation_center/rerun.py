"""Sandboxed validation re-run.

Why not app.jobs: the existing job system is bound to one case's evidence (jobs.case_id and
jobs.evidence_id are foreign keys) and a validation run has neither. Instead this module runs the
existing harness CLI (`python -m app.validation.run`) as ONE subprocess at a time with:
  * a fixed argument list built from validated parameters (no shell, no user strings),
  * a timeout ($NIRIKSHAN_VALIDATION_TIMEOUT_S, default 3600 s; the process is killed on expiry),
  * `--out` pointing at a fresh temporary directory, never at docs/validation,
  * the committed baseline file hashed before and after (any change is reported as a failure).
The new results digest is compared with the committed digest. They can only be equal when the
parameters match the baseline (seed, trials, full scenario set, export on) and the tool and
ffmpeg versions are the same; the comparison says which of these differ.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import app as app_pkg
from app.clock import utc_now_iso
from app.db import SessionLocal
from app.validation import thresholds
from app.validation_center import results as vres
from app.validation_center.models import ValidationRerun

BACKEND_DIR = Path(app_pkg.__file__).resolve().parents[1]
_lock = threading.Lock()
_active: set[int] = set()


def timeout_s() -> float:
    try:
        return max(1.0, float(os.getenv("NIRIKSHAN_VALIDATION_TIMEOUT_S", "3600")))
    except ValueError:
        return 3600.0


def busy() -> bool:
    with _lock:
        return bool(_active)


def is_active(run_id: int) -> bool:
    with _lock:
        return run_id in _active


def command(params: dict, out_dir: str) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "app.validation.run",
        "--seed",
        str(int(params["seed"])),
        "--trials",
        str(int(params["trials"])),
        "--out",
        out_dir,
    ]
    if not params["export"]:
        cmd.append("--no-export")
    if params.get("scenarios"):
        cmd += ["--only", *params["scenarios"]]
    return cmd


def compare(baseline: dict | None, new: dict, params: dict) -> dict:
    if baseline is None:
        return {"baseline_available": False}
    differs = []
    for key, want, got in (
        ("seed", baseline.get("seed"), new.get("seed")),
        ("trials", baseline.get("trials"), new.get("trials")),
        ("export_decode_test", baseline.get("export_decode_test"), new.get("export_decode_test")),
        ("tool_version", baseline.get("tool_version"), new.get("tool_version")),
        ("ffmpeg", baseline.get("ffmpeg"), new.get("ffmpeg")),
    ):
        if want != got:
            differs.append({"field": key, "baseline": want, "rerun": got})
    if params.get("scenarios"):
        differs.append({"field": "scenarios", "baseline": "all", "rerun": params["scenarios"]})
    base = {s["id"]: s for s in baseline["scenarios"]}
    metric_diffs, same = [], 0
    for s in new["scenarios"]:
        b = base.get(s["id"])
        if b is None:
            metric_diffs.append({"id": s["id"], "difference": "not in baseline"})
            continue
        changed = sorted(
            k
            for k in set(b["metrics"]) | set(s["metrics"])
            if b["metrics"].get(k) != s["metrics"].get(k)
        )
        if changed:
            metric_diffs.append(
                {
                    "id": s["id"],
                    "metrics": {
                        k: {"baseline": b["metrics"].get(k), "rerun": s["metrics"].get(k)}
                        for k in changed
                    },
                }
            )
        else:
            same += 1
    return {
        "baseline_available": True,
        "baseline_digest": baseline.get("results_digest"),
        "rerun_digest": new.get("results_digest"),
        "digest_match": baseline.get("results_digest") == new.get("results_digest"),
        "comparable": not differs,
        "parameter_or_version_differences": differs,
        "scenario_results_compared": len(new["scenarios"]),
        "scenario_results_identical": same,
        "metric_differences": metric_diffs,
        "basis": vres.BASIS,
    }


def _finish(run_id: int, **fields) -> None:
    with SessionLocal() as db:
        row = db.get(ValidationRerun, run_id)
        for k, v in fields.items():
            setattr(row, k, v)
        row.finished_at = utc_now_iso()
        db.commit()


def _work(run_id: int, params: dict, out_dir: str, baseline_path: str) -> None:
    try:
        with SessionLocal() as db:
            row = db.get(ValidationRerun, run_id)
            row.status, row.started_at = "running", utc_now_iso()
            db.commit()
        cmd = command(params, out_dir)
        try:
            proc = subprocess.run(
                cmd,
                cwd=BACKEND_DIR,
                capture_output=True,
                text=True,
                timeout=timeout_s(),
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as e:
            tail = (e.stderr or "")[-4000:] if isinstance(e.stderr, str) else ""
            _finish(
                run_id, status="timeout", error=f"killed after {timeout_s():g} s", log_tail=tail
            )
            return
        after = vres.sha256_file(Path(baseline_path)) or ""
        tail = ((proc.stdout or "")[-2000:] + "\n" + (proc.stderr or "")[-2000:]).strip()
        out_file = Path(out_dir) / "results.json"
        if proc.returncode not in (0, 1) or not out_file.is_file():
            _finish(
                run_id,
                status="failed",
                exit_code=proc.returncode,
                log_tail=tail,
                baseline_sha256_after=after,
                error=f"harness exited with {proc.returncode} and wrote no results",
            )
            return
        new = json.loads(out_file.read_text())
        baseline, _ = vres.load(Path(baseline_path))
        cmp = compare(baseline, new, params)
        cmp["rerun_threshold_violations"] = thresholds.check(
            new, require_present=not params.get("scenarios")
        )
        with SessionLocal() as db:
            before = db.get(ValidationRerun, run_id).baseline_sha256_before
        status, err = "completed", ""
        if before and after != before:
            status, err = "failed", "the committed baseline file changed during the re-run"
        _finish(
            run_id,
            status=status,
            exit_code=proc.returncode,
            log_tail=tail,
            baseline_sha256_after=after,
            rerun_digest=new.get("results_digest", ""),
            comparison_json=json.dumps(cmp),
            error=err,
        )
    except Exception as e:  # noqa: BLE001 - every path ends in a terminal state
        _finish(run_id, status="failed", error=f"{type(e).__name__}: {e}"[:500])
    finally:
        with _lock:
            _active.discard(run_id)


def start(db, params: dict, examiner: str) -> ValidationRerun:
    """Create the row and start the worker thread. Raises RuntimeError if one is running."""
    baseline_path = vres.results_path()
    baseline, info = vres.load(baseline_path)
    with _lock:
        if _active:
            raise RuntimeError("a validation re-run is already running")
        out_dir = tempfile.mkdtemp(prefix="nirikshan-validate-")
        resolved = Path(out_dir).resolve()
        if (
            resolved == baseline_path.parent.resolve()
            or baseline_path.parent.resolve() in resolved.parents
        ):
            raise RuntimeError("refusing to write a re-run next to the committed baseline")
        row = ValidationRerun(
            status="queued",
            params_json=json.dumps(params, sort_keys=True),
            command_json=json.dumps(command(params, out_dir)),
            out_dir=out_dir,
            baseline_path=str(baseline_path),
            baseline_sha256_before=info.get("file_sha256") or "",
            baseline_digest=(baseline or {}).get("results_digest", "") or "",
            examiner=examiner,
        )
        db.add(row)
        db.commit()
        _active.add(row.id)
    threading.Thread(
        target=_work,
        args=(row.id, params, out_dir, str(baseline_path)),
        daemon=True,
        name=f"validation-rerun-{row.id}",
    ).start()
    return row
