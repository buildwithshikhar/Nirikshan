#!/usr/bin/env python3
"""Render docs/FINAL_REPORT.md from docs/FINAL_REPORT.template.md plus data files.

    python scripts/build_final_report.py            # write docs/FINAL_REPORT.md
    python scripts/build_final_report.py --check    # validate only; exit 1 if stale or invalid

Every number in the rendered sections is parsed from a data file, never typed:
  docs/validation/results.json   synthetic validation (digest, seed, trials, per-scenario k/n)
  docs/analytics/error_rates.json public-dataset analytics error rates
  docs/timeline.md               OCR accuracy sentence on rendered synthetic overlays
  docs/traceability.yaml         requirement matrix (all code/tests/docs paths must exist)
  docs/OEM_COMPARISON.md         tier column, cross-checked with tier attributes in the code
Fails (exit 1) on a missing referenced path, an unparsable source, a tier mismatch, or (with
--check) when docs/FINAL_REPORT.md differs from what would be generated.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "FINAL_REPORT.md"
TEMPLATE = DOCS / "FINAL_REPORT.template.md"
MARKER = re.compile(r"\[\[PENDING-MERGE: [AB]\]\]")
errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def rate(m: dict) -> str:
    if not m or not m.get("n"):
        return "n/a"
    return f"{100 * m['k'] / m['n']:.1f}% ({m['k']}/{m['n']})"


def load_traceability() -> dict:
    data = yaml.safe_load((DOCS / "traceability.yaml").read_text())
    for r in data["requirements"]:
        if r["status"] not in ("Built", "Partial", "Planned"):
            fail(f"{r['id']}: bad status {r['status']!r}")
        for kind in ("code", "tests", "docs"):
            for p in r.get(kind) or []:
                if not (ROOT / p).exists():
                    fail(f"{r['id']}: {kind} path does not exist: {p}")
        for p in r.get("pending") or []:
            if not MARKER.search(p):
                fail(f"{r['id']}: pending entry without a PENDING-MERGE marker: {p[:60]}")
        for field in ("note", "requirement"):
            if MARKER.search(str(r.get(field, ""))) and not r.get("pending"):
                fail(f"{r['id']}: marker in {field} but no pending entry")
    return data


def render_matrix(data: dict) -> str:
    rows = [
        "| ID | Requirement | Status | Code | Tests | Docs | Note |",
        "|---|---|---|---|---|---|---|",
    ]

    def cell(paths):
        return "<br>".join(f"`{p}`" for p in paths) if paths else "-"

    counts = {"Built": 0, "Partial": 0, "Planned": 0}
    for r in data["requirements"]:
        counts[r["status"]] += 1
        note = r["note"]
        if r.get("pending"):
            note += " " + " ".join(r["pending"])
        rows.append(
            f"| {r['id']} | {r['requirement']} | **{r['status']}** | {cell(r.get('code'))} | "
            f"{cell(r.get('tests'))} | {cell(r.get('docs'))} | {note} |"
        )
    summary = (
        f"Counts (computed): Built {counts['Built']}, Partial {counts['Partial']}, "
        f"Planned {counts['Planned']} of {len(data['requirements'])}. "
        "Built means implemented and tested on synthetic data in this repository, not validated "
        "on a real device."
    )
    return summary + "\n\n" + "\n".join(rows)


def code_tiers() -> dict[str, str]:
    out = {}
    for f in (ROOT / "backend" / "app" / "vendors").glob("*.py"):
        t = f.read_text()
        v = re.search(r'^\s+vendor = "([^"]+)"', t, re.M)
        tr = re.search(r'^\s+tier = "([ABC])"', t, re.M)
        if v and tr:
            out[v.group(1)] = tr.group(1)
    return out


def render_tiers(data: dict) -> str:
    claimed = data["tiers"]
    text = (DOCS / "OEM_COMPARISON.md").read_text()
    table: dict[str, str] = {}
    for line in text.split("## 2.")[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if (
            len(cells) >= 7
            and cells[0] not in ("OEM", "---")
            and re.fullmatch(r"\*\*[ABC]\*\*", cells[-1])
        ):
            table[cells[0]] = cells[-1].strip("*")
    code = code_tiers()
    rows = [
        "| OEM | Tier (claimed) | OEM_COMPARISON.md | Parser in code | Public documentation |",
        "|---|---|---|---|---|",
    ]
    for oem, tier in claimed.items():
        doc_t = table.get(oem)
        if doc_t != tier:
            fail(f"tier mismatch for {oem}: traceability {tier}, OEM_COMPARISON {doc_t}")
        code_t = code.get(oem)
        if code_t is not None and code_t != tier:
            fail(f"tier mismatch for {oem}: traceability {tier}, code {code_t}")
        if code_t is None and tier != "C":
            fail(f"{oem}: tier {tier} but no parser with a tier attribute in code")
        rows.append(
            f"| {oem} | {tier} | {doc_t} | {'Tier ' + code_t if code_t else 'none'} | "
            f"{'see OEM_COMPARISON' if tier != 'C' else 'none found'} |"
        )
    tier_def = {"A": "validated on real images", "B": "signature + generic carving", "C": "planned"}
    return (
        "Tier A = "
        + tier_def["A"]
        + "; B = "
        + tier_def["B"]
        + "; C = "
        + tier_def["C"]
        + f". Tier A vendors: {sum(1 for t in claimed.values() if t == 'A')}.\n\n"
        + "\n".join(rows)
    )


def render_validation() -> str:
    p = DOCS / "validation" / "results.json"
    d = json.loads(p.read_text())
    if not d.get("synthetic"):
        fail("results.json is not marked synthetic")
    sc = d["scenarios"]
    base = [s for s in sc if s["kind"] == "positive" and "@" not in s["id"]]
    neg = [s for s in sc if s["kind"] == "negative"]
    vend = [s for s in sc if "@" in s["id"]]
    head = (
        f"Source: `docs/validation/results.json` (tool {d['tool_version']}, seed {d['seed']}, "
        f"{d['trials']} trials per scenario, engine `{d['engine']}`, {len(sc)} scenario/engine "
        f"rows). **Results digest (SHA-256, excludes timings): `{d['results_digest']}`.** "
        "All images are SYNTHETIC; vendor-layout rows are a circular check.\n\n"
        + "\n".join(f"> {x}" for x in d["disclaimer"])
        + "\n\n"
    )
    rows = [
        "| Scenario (generic engine) | Clip recall | Clip precision | Byte-exact | Decode ok |",
        "|---|---|---|---|---|",
    ]
    for s in base:
        m = s["metrics"]
        rows.append(
            f"| `{s['id']}` | {rate(m['clip_recall'])} | {rate(m['clip_precision'])} | "
            f"{rate(m['byte_exact'])} | {rate(m['decode_ok'])} |"
        )
    nrows = [
        "| Negative scenario | Clips emitted | Decoded cleanly | Emitted but flagged failed |",
        "|---|---|---|---|",
    ]
    for s in neg:
        m = s["metrics"]
        nrows.append(
            f"| `{s['id']}` | {rate(m['clips_emitted'])} | {rate(m['clips_decoded_ok'])} | "
            f"{rate(m['emitted_but_flagged_failed'])} |"
        )
    engines = sorted({s["engine"] for s in vend})
    return (
        head
        + "\n".join(rows)
        + "\n\nNegatives (no cleanly decoding clip must be produced):\n\n"
        + "\n".join(nrows)
        + f"\n\nVendor-layout rows ({len(vend)}, engines: {', '.join(engines)}) are in "
        "`docs/validation/results.md`; they measure parsers against images built from the same "
        "paper-derived layout and are not independent evidence."
    )


def render_analytics() -> str:
    d = json.loads((DOCS / "analytics" / "error_rates.json").read_text())
    rows = [
        "| Task | Condition | Confidence | Precision | Recall | n | Label |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, label in (
        ("objects", "person detection (Penn-Fudan)"),
        ("faces", "face detection (BioID)"),
        ("motion", "motion (synthetic clips)"),
    ):
        for c in d["entries"][key]["configs"]:
            thr = c.get("confidence_threshold")
            rows.append(
                f"| {label} | {c['condition']} | {thr if thr is not None else '-'} | "
                f"{c['precision']:.4f} | {c['recall']:.4f} | {c['n_images']} | {c['label']} |"
            )
    return (
        "Source: `docs/analytics/error_rates.json`. "
        + d.get("statement", "")
        + "\n\n"
        + "\n".join(rows)
    )


def render_ocr() -> str:
    t = (DOCS / "timeline.md").read_text().replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    m = re.search(
        r"(\d+) of (\d+) exactly correct, (\d+) unreadable.{0,200}?(\d+) confidently wrong", t
    )
    if not m:
        fail("OCR accuracy sentence not found in docs/timeline.md")
        return "OCR figure unavailable"
    ex, n, unr, wrong = m.groups()
    return (
        f"On {n} rendered synthetic overlays: {ex} exactly correct, {unr} unreadable, {wrong} "
        "confidently wrong (source: `docs/timeline.md`, parsed). Real DVR overlays are untested."
    )


def render_pending(data: dict) -> str:
    items = []
    for r in data["requirements"]:
        for p in r.get("pending") or []:
            items.append(f"- {r['id']}: {p}")
    return "\n".join(items) if items else "None."


STATS = ROOT / "docs" / "stats.json"
README = ROOT / "README.md"
HL_START, HL_END = "<!-- HIGHLIGHTS:START (generated by scripts/build_final_report.py) -->", "<!-- HIGHLIGHTS:END -->"


def pc(m: dict | None) -> str:
    return "n/a" if not m else f"{m['rate'] * 100:.0f}%"


def render_highlights(heading: str = "###") -> str:
    """Measured strengths, every number read from docs/stats.json (written by collect_stats.py)."""
    try:
        s = json.loads(STATS.read_text())
    except (OSError, ValueError):
        fail("docs/stats.json missing or unreadable; run scripts/collect_stats.py")
        return ""
    t, v = s["tests"], s["validation"]
    fa = v["reassembler_false_accept"]
    lines = [
        f"{heading} Measured strengths (numbers computed by code from `docs/stats.json` and `docs/validation/results.json`)",
        "",
        f"- **{t['backend_collected']} backend tests and {t['e2e_collected']} end-to-end browser tests** "
        f"({t['e2e_files']} spec files, including an axe accessibility gate and a check that every demo screen "
        "states the data origin and the Tier B limit). CI runs backend tests on Python 3.10 and 3.12, the frontend "
        "build and lint, and a traceability/tier consistency check "
        "([![CI](https://github.com/buildwithshikhar/Nirikshan/actions/workflows/ci.yml/badge.svg)]"
        "(https://github.com/buildwithshikhar/Nirikshan/actions/workflows/ci.yml)).",
        f"- **{v['distinct_scenarios']} known-answer scenarios** ({v['scenario_engine_results']} scenario x engine results, "
        f"seed {v['seed']}, {v['trials']} trials each, digest `{v['results_digest'][:16]}`), scored with ground truth "
        "computed by byte comparison; the regression thresholds are enforced in CI "
        f"(violations in the committed baseline: {len(v['thresholds_violations'] or [])}).",
        f"- **{v['negative_scenarios']} negative scenarios** (encrypted streams, MJPEG, MPEG-4, noise with false start codes): "
        f"{v['negative_clean_decodes']} cleanly decoding clips were produced; clips emitted anyway are flagged as failed decodes.",
        f"- **Custody integrity: {t['custody_integrity']} tests** covering tampering, forgery, recomputed chains without the key, "
        "truncation, append-only triggers, and signatures created before a dependency upgrade.",
        f"- **Reports: {t['report_and_origin']} tests**; the PDF is byte-identical for the same data and generation time, "
        "a tampered custody chain is shown as FAILED, and each report records its own SHA-256 in the custody log.",
        f"- **The fragment reassembler is measured, not assumed:** false-accept rate {fa['rate'] * 100:.1f}% "
        f"({fa['k']}/{fa['n']}), so it is off by default.",
        "",
        "Recovery on the reference test layouts (clip recall / clip precision; generic carver vs vendor parser vs the default "
        "parser-first + generic pipeline):",
        "",
        "| Scenario | Generic only | Parser only | Parser first + generic (default) |",
        "|---|---|---|---|",
    ]
    for r in s["recovery_rows"]:
        cells = [
            f"{pc(r[e]['clip_recall'])} / {pc(r[e]['clip_precision'])}" if e in r else "n/a (no parser)"
            for e in ("generic", "parser", "combined")
        ]
        lines.append(f"| {r['title']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "These layouts are reference test data: built from published research and open-source format documentation, with "
        "known ground truth. They were not captured from a physical DVR, and a parser tested on a layout built from the "
        "same document is a circular check. See the limits below.",
    ]
    return "\n".join(lines)


def readme_with_highlights() -> str:
    text = README.read_text()
    if HL_START not in text or HL_END not in text:
        fail("README.md lacks the HIGHLIGHTS markers")
        return text
    a, b = text.index(HL_START), text.index(HL_END)
    return text[: a + len(HL_START)] + "\n\n" + render_highlights("###") + "\n\n" + text[b:]


def build() -> str:
    data = load_traceability()
    tpl = TEMPLATE.read_text()
    subs = {
        "TRACE_MATRIX": render_matrix(data),
        "TIER_TABLE": render_tiers(data),
        "VALIDATION": render_validation(),
        "ANALYTICS": render_analytics(),
        "OCR": render_ocr(),
        "PENDING": render_pending(data),
        "HIGHLIGHTS": render_highlights("##"),
    }
    for k, v in subs.items():
        if "{{" + k + "}}" not in tpl:
            fail(f"template lacks placeholder {{{{{k}}}}}")
        tpl = tpl.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", tpl)
    if left:
        fail(f"unfilled placeholders: {left}")
    return tpl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = build()
    if errors:
        print("FAILED:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    readme = readme_with_highlights()
    if a.check:
        if README.read_text() != readme:
            print("README.md highlights are stale; run scripts/build_final_report.py", file=sys.stderr)
            return 1
        if not OUT.exists() or OUT.read_text() != text:
            print(
                "docs/FINAL_REPORT.md is stale; run scripts/build_final_report.py", file=sys.stderr
            )
            return 1
        print("ok: traceability paths exist, tiers consistent, report up to date")
        return 0
    OUT.write_text(text)
    README.write_text(readme)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
