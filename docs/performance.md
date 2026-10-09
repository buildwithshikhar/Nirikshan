# Performance analytics

`GET /api/cases/{case_id}/performance` (any case member). Code: `backend/app/perf/`. Tests:
`backend/tests/test_perf_analytics.py`. Every number is a stored timing, a count of stored rows,
or arithmetic on them. When an input is missing the field says `{"available": false, "reason":
...}`; nothing is estimated or filled in.

## Per-run breakdown

For each carve run of the case:

| Stage | Source |
|---|---|
| `identify` | `carve_runs.ident_seconds` (vendor identification; in an isolated job, the worker's identify time) |
| `parse_and_export_parser_clips` | `stats.parse_seconds`: vendor parsers plus exporting and recording their clips |
| `generic_carve_and_export` | `carve_runs.carve_seconds`: generic carving plus exporting and recording its clips |
| `crosscheck` | `stats.crosscheck_seconds` (runs made after Round D): the independent generic pass for the parser cross-check |
| `worker_startup_hash_and_transfer` | isolated jobs only: worker wall time minus the worker's own stage times (interpreter start, re-hash of the image inside the worker, result transfer) |
| `other (image verification, database, custody signing)` | `finished_at - started_at` minus the stages above (includes the parent's image re-verification before every run) |

Each stage has seconds and its share of the run's wall-clock time (`finished_at - started_at`).
`throughput_mib_per_s` = bytes scanned / wall-clock time. Export time is inside the parse and
carve stages because the pipeline exports each clip as it is found; it is not separable from the
stored timings of in-process runs. Runs made before `crosscheck_seconds` existed show the
cross-check inside `other`.

## Bottleneck rule

The bottleneck is the stage with the largest share of the run's wall-clock time; it is
**dominant** when that share is at least 0.5. Runs shorter than 0.05 s get no bottleneck (timer
resolution). A run without `finished_at` (running, failed early) gets
`{"available": false}`.

## Baseline comparison

Completed runs are grouped by (evidence SHA-256, exact run parameters). In every group with at
least two runs the earliest run is the baseline; each later run reports total seconds, the
difference and ratio to the baseline, per-stage differences, whether the tool version is the
same, and whether it ran in an isolated worker. Differences between machines, load and cache
state are not controlled: a comparison is a record of what happened, not a benchmark.

## Success rates

Computed over the case's completed runs:

| Rate | Definition |
|---|---|
| `segment_recovery` | clips / (clips + orphan ranges): share of detected video segments that became clips |
| `extraction_clean` | clips exported and decoded without errors / exportable clips |
| `extraction_any` | clips exported, with or without decode errors / exportable clips |
| `analytics_completed` | completed analytics runs / analytics runs of the case |

Each gives numerator and denominator. These describe the tool's own output on this case. They
are **not accuracy**: there is no ground truth for casework images. Accuracy measured on
reference test data (with known ground truth) is in `docs/VALIDATION.md`.

## Time saved

Reported only against a manual baseline the examiner enters for the case and task:

`POST /api/cases/{id}/performance/baselines` `{"task": "analyze" | "analytics",
"manual_seconds": > 0, "basis": "measured" | "estimate", "note": "..."}` (case member, Admin or
Examiner). Each entry is a custody entry `manual_baseline_recorded`; history is kept and the
newest entry per task is used (`GET .../baselines`).

- No baseline: `{"available": false, "reason": "no manual baseline entered"}`.
- Baseline but no completed run of that task: `available: false` with that reason.
- Otherwise: `tool_seconds` = sum of wall-clock seconds of the latest completed run per evidence
  item (analyze) or per (clip, analytics kind) (analytics), so re-runs are not double counted;
  `time_saved_seconds` = manual - tool; `speedup` = manual / tool.

Limits: the tool time is machine processing only; the examiner's time to review the output is
not measured, so the saving is an upper bound. The manual figure is whatever the examiner
entered (`basis` says whether it was measured or estimated); the tool does not verify it. No
default or typical manual time is ever assumed.
