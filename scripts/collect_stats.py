#!/usr/bin/env python3
"""Collect measured project statistics into docs/stats.json (run by hand before a release).

    backend/.venv/bin/python scripts/collect_stats.py

Everything is computed: test counts come from `pytest --collect-only` and `playwright test --list`,
scenario and recovery numbers from docs/validation/results.json. Nothing is typed in. The file is
read by scripts/build_final_report.py to render the README and FINAL_REPORT highlights.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND, FRONTEND = ROOT / "backend", ROOT / "frontend"
RESULTS = ROOT / "docs" / "validation" / "results.json"
OUT = ROOT / "docs" / "stats.json"

CUSTODY_TESTS = [
    "tests/test_custody.py", "tests/test_triggers.py", "tests/test_signature_compat.py",
    "tests/test_signing.py", "tests/test_cli.py", "tests/test_evidence.py",
]
REPORT_TESTS = ["tests/test_report.py", "tests/test_report_exports.py", "tests/test_data_origin.py"]


def collect(files: list[str]) -> int:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *files],
        cwd=BACKEND, capture_output=True, text=True, check=False,
    ).stdout
    m = re.findall(r"(\d+) tests? collected", out)
    if not m:
        raise SystemExit(f"could not count tests for {files}:\n{out[-400:]}")
    return int(m[-1])


def e2e_count() -> tuple[int, int]:
    out = subprocess.run(
        ["npx", "playwright", "test", "--list"], cwd=FRONTEND, capture_output=True, text=True,
        check=False,
    ).stdout
    m = re.search(r"Total: (\d+) tests? in (\d+) files?", out)
    if not m:
        raise SystemExit(f"could not count e2e tests:\n{out[-400:]}")
    return int(m.group(1)), int(m.group(2))


def metric(by_id: dict, key: str, name: str) -> dict | None:
    m = (by_id.get(key) or {}).get("metrics", {}).get(name)
    return None if not m or m.get("rate") is None else {"k": m["k"], "n": m["n"], "rate": m["rate"]}


def recovery_rows(by_id: dict) -> list[dict]:
    rows = []
    for title, base, vendor in [
        ("Hikvision layout, HIKBTREE entries cleared (deleted-then-intact)", "deleted_intact_zero@hik", "hikvision"),
        ("Hikvision layout, clean live clips", "clean_live@hik", "hikvision"),
        ("Dahua DHAV layout, clean live clips", "clean_live@dhav", "dahua"),
        ("Dahua DHAV layout, 2-3 cameras frame-interleaved", "multi_channel_frame@dhav", "dahua"),
        ("Honeywell layout, clean live clips", "clean_live@honeywell", "honeywell"),
        # documented limits, listed next to the strengths on purpose (raw layout: generic carver only)
        ("Raw layout, 100-300 B zero padding inside a clip (documented limit)", "zero_pad_inside_wide", None),
        ("Raw layout, 2-3 cameras GOP-interleaved, identical parameter sets (no channel metadata)", "multi_channel_gop", None),
        ("Raw layout, one clip fully overwritten (must not be recovered)", "fully_overwritten", None),
    ]:
        row = {"title": title, "scenario": base}
        keys = (
            [("generic", base)]
            if vendor is None
            else [
                ("generic", f"{base}[generic]"),
                ("parser", f"{base}[{vendor}]"),
                ("combined", f"{base}[{vendor}+generic]"),
            ]
        )
        for label, key in keys:
            row[label] = {"clip_recall": metric(by_id, key, "clip_recall"),
                          "frame_recall": metric(by_id, key, "frame_recall"),
                          "clip_precision": metric(by_id, key, "clip_precision")}
        rows.append(row)
    return rows


def main() -> int:
    res = json.loads(RESULTS.read_text())
    by_id = {s["id"]: s for s in res["scenarios"]}
    neg = [s for s in res["scenarios"] if s["kind"] == "negative"]
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                         text=True, check=False).stdout.strip()
    e2e, e2e_files = e2e_count()
    fa = (by_id.get("fragmented_decoy_join_on") or {}).get("metrics", {}).get("reassembler_false_accept")
    stats = {
        "collected_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "git_commit": sha,
        "tests": {
            "backend_collected": collect([]),
            "e2e_collected": e2e,
            "e2e_files": e2e_files,
            "custody_integrity": collect(CUSTODY_TESTS),
            "report_and_origin": collect(REPORT_TESTS),
        },
        "validation": {
            "results_digest": res["results_digest"],
            "seed": res["seed"],
            "trials": res["trials"],
            "distinct_scenarios": len({s.get("scenario", s["id"]) for s in res["scenarios"]}),
            "scenario_engine_results": len(res["scenarios"]),
            "negative_scenarios": len(neg),
            "negative_clean_decodes": sum(s["metrics"]["clips_decoded_ok"]["k"] for s in neg),
            "reassembler_false_accept": fa and {"k": fa["k"], "n": fa["n"], "rate": fa["rate"]},
            "thresholds_violations": res.get("thresholds", {}).get("violations"),
        },
        "recovery_rows": recovery_rows(by_id),
    }
    OUT.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
