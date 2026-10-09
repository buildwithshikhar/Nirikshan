"""Load and check the versioned OEM support registry (registry.json next to this module).

`check()` returns every disagreement between the data file and the parser registry in code
(vendors.default_registry, vendors.TIER_C_VENDORS); tests/test_oem_registry.py requires it to be
empty, so the documented support levels cannot drift from what the code does.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.vendors import TIER_C_VENDORS, default_registry

PATH = Path(__file__).with_name("registry.json")
TARGETS = (
    "Dahua",
    "CP Plus",
    "Honeywell",
    "TP-Link",
    "Godrej",
    "Uniview",
    "Hikvision",
    "Matrix",
    "Axis",
    "Bosch",
    "Hanwha Vision",
    "VIVOTEK",
    "Avigilon",
    "Pelco",
    "Tiandy",
    "Reolink",
)
FIELDS = (
    "standard_export_support",
    "proprietary_storage_parsing",
    "deleted_video_recovery",
    "tier",
    "evidence",
    "limitations",
    "parser_version",
    "sources",
)
ALLOWED_TIERS = ("B", "C")  # no vendor above Tier B
CONFIDENCE = ("high", "medium", "low")


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(PATH.read_text())


def check(data: dict | None = None) -> list[str]:
    d = data if data is not None else load()
    errs: list[str] = []
    rows = {r["name"]: r for r in d["oems"]}
    if len(rows) != len(d["oems"]):
        errs.append("duplicate OEM names")
    for t in TARGETS:
        if t not in rows:
            errs.append(f"missing target OEM {t}")
    for name in rows:
        if name not in TARGETS:
            errs.append(f"unexpected OEM {name}")
    parsers = {p.vendor: p for p in default_registry().parsers}
    for name, r in rows.items():
        for f in FIELDS:
            if f not in r:
                errs.append(f"{name}: missing field {f}")
        if r.get("tier") not in ALLOWED_TIERS:
            errs.append(f"{name}: tier {r.get('tier')!r} not allowed (max B)")
        for s in r.get("sources", []):
            if s not in d["sources"]:
                errs.append(f"{name}: unknown source id {s}")
        p = parsers.get(r.get("parser_vendor") or "")
        if p is not None:
            if r["tier"] != p.tier:
                errs.append(f"{name}: tier {r['tier']} != parser tier {p.tier}")
            if r["parser_version"] != p.parser_version:
                errs.append(
                    f"{name}: parser_version {r['parser_version']} != code {p.parser_version}"
                )
            if r["proprietary_storage_parsing"]["level"] == "none":
                errs.append(f"{name}: has a parser but claims no proprietary parsing")
        else:
            if r.get("parser_vendor"):
                errs.append(f"{name}: parser_vendor {r['parser_vendor']} not in default_registry")
            if name not in TIER_C_VENDORS:
                errs.append(f"{name}: no parser but not in TIER_C_VENDORS")
            if r["tier"] != "C" or r["parser_version"] is not None:
                errs.append(f"{name}: without a parser must be Tier C with parser_version null")
            if r["proprietary_storage_parsing"]["level"] != "none":
                errs.append(f"{name}: without a parser must claim no proprietary parsing")
            if r["deleted_video_recovery"]["level"] != "generic carving only":
                errs.append(f"{name}: without a parser recovery must be generic carving only")
    for v in TIER_C_VENDORS:
        if v not in rows:
            errs.append(f"TIER_C_VENDORS entry {v} missing from the registry")
    for v in parsers:
        if not any(r.get("parser_vendor") == v for r in rows.values()):
            errs.append(f"parser {v} missing from the registry")
    for sid, s in d["sources"].items():
        if s.get("confidence") not in CONFIDENCE:
            errs.append(f"source {sid}: confidence must be one of {CONFIDENCE}")
        for k in ("url", "retrieved", "says", "does_not_say"):
            if not s.get(k):
                errs.append(f"source {sid}: missing {k}")
    return errs
