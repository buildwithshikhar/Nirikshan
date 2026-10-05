"""Regression thresholds over a validation result."""

import json
from pathlib import Path

PATH = Path(__file__).with_name("thresholds.json")


def load() -> dict:
    return {k: v for k, v in json.loads(PATH.read_text()).items() if not k.startswith("_")}


def check(res: dict, thresholds: dict | None = None) -> list[str]:
    """Violations as strings; empty = pass. Scenarios absent from `res` are skipped."""
    out: list[str] = []
    by_id = {s["id"]: s for s in res["scenarios"]}
    for sid, rules in (thresholds or load()).items():
        sc = by_id.get(sid)
        if sc is None:
            continue
        for metric, rule in rules.items():
            m = sc["metrics"].get(metric)
            if m is None:
                out.append(f"{sid}.{metric}: metric missing")
                continue
            if "max_k" in rule and m["k"] > rule["max_k"]:
                out.append(f"{sid}.{metric}: k={m['k']} > {rule['max_k']}")
            r = m.get("rate")
            if ("min" in rule or "max" in rule) and r is None:
                out.append(f"{sid}.{metric}: no data")
            elif "min" in rule and r < rule["min"]:
                out.append(f"{sid}.{metric}: {r} < min {rule['min']}")
            elif "max" in rule and r > rule["max"]:
                out.append(f"{sid}.{metric}: {r} > max {rule['max']}")
    return out
