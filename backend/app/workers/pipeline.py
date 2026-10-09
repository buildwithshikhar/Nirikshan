"""Glue between the job manager and isolated workers.

analyze: the worker computes the identification/parse/carve plan (read-only over the image, no
database, no keys); app.analyze then exports clips (ffmpeg, already a separate process with its
own timeouts) and persists rows + custody entries exactly as the in-process path does. A worker
crash, timeout or limit therefore happens before any clip of the run is stored: the run is
marked failed with the worker's error and holds no clips.

analytics: the worker returns detections/intervals; app.analytics.runner adds every result row in
one transaction after the worker returns.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.analyze import AnalysisCancelled
from app.models import Evidence
from app.workers import isolate
from app.workers.plan import PlannedSource


def analyze_planner(
    ev: Evidence,
    params: dict,
    parser_options: dict | None,
    generic_scope: str,
    record: dict,
    limits: isolate.Limits | None = None,
) -> Callable:
    """Return a planner for app.analyze.analyze(planner=...). `record` receives the worker's
    wall time and the limits it applied (stored on the job for performance analytics)."""
    carve = {k: params[k] for k in ("max_pad", "h264_continuity", "validate_params", "join_gap")}

    def planner(hooks) -> PlannedSource:
        payload = {
            "image_path": ev.image_path,
            "size": ev.size_bytes,
            "expected_sha256": ev.sha256,
            "params": carve,
            "parser_options": parser_options or {},
            "generic_scope": generic_scope,
        }
        t0 = time.perf_counter()
        try:
            out = isolate.run_task(
                "analyze_plan",
                payload,
                limits=limits or isolate.Limits.from_env(),
                on_progress=lambda stage, f: hooks.report(stage, 0.10 + 0.40 * f),
                should_cancel=hooks.should_cancel,
            )
        except isolate.WorkerCancelled:
            raise AnalysisCancelled from None
        finally:
            record["worker_wall_s"] = round(time.perf_counter() - t0, 6)
        record["limits_applied"] = out.get("limits_applied", {})
        plan = out["result"]
        record["worker"] = plan.get("timings", {})
        return PlannedSource(plan, ev.size_bytes, ev.sha256)

    return planner


def analytics_compute(record: dict, should_cancel=None, limits: isolate.Limits | None = None):
    """A compute function for app.analytics.runner.run_analytics(compute=...)."""

    def compute(kind: str, mp4_path: str, params, mp4_sha256: str) -> dict:
        t0 = time.perf_counter()
        try:
            out = isolate.run_task(
                "analytics",
                {
                    "mp4_path": mp4_path,
                    "expected_sha256": mp4_sha256,
                    "kind": kind,
                    "params": params.to_dict(),
                },
                limits=limits or isolate.Limits.from_env(),
                should_cancel=should_cancel,
            )
        finally:
            record.setdefault("worker_wall_s", []).append(round(time.perf_counter() - t0, 6))
        record["limits_applied"] = out.get("limits_applied", {})
        return out["result"]["res"]

    return compute
