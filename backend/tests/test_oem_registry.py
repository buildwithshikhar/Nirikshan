"""The OEM registry data file must agree with the parser registry in code."""

import copy

from app.oem import registry
from app.vendors import TIER_C_VENDORS, default_registry
from tests import stream2  # noqa: F401


def test_registry_is_consistent_with_code():
    assert registry.check() == []


def test_all_16_targets_have_every_field_and_none_above_tier_b():
    d = registry.load()
    assert sorted(r["name"] for r in d["oems"]) == sorted(registry.TARGETS)
    assert len(d["oems"]) == 16
    for r in d["oems"]:
        assert set(registry.FIELDS) <= set(r)
        assert r["tier"] in ("B", "C")


def test_tier_b_rows_mirror_parsers_and_tier_c_rows_mirror_the_code_list():
    d = {r["name"]: r for r in registry.load()["oems"]}
    for p in default_registry().parsers:
        row = d[p.vendor]
        assert (row["tier"], row["parser_version"]) == (p.tier, p.parser_version)
        assert p.parser_version  # every structured parser carries a version constant
    tier_c = {n for n, r in d.items() if r["tier"] == "C"}
    assert tier_c == set(TIER_C_VENDORS)


def test_check_catches_drift():
    d = copy.deepcopy(registry.load())
    row = next(r for r in d["oems"] if r["name"] == "Hikvision")
    row["parser_version"] = "9.9"
    row["tier"] = "A"
    cp = next(r for r in d["oems"] if r["name"] == "CP Plus")
    cp["proprietary_storage_parsing"]["level"] = "partial"
    cp["sources"].append("NOPE")
    d["oems"] = [r for r in d["oems"] if r["name"] != "Reolink"]
    errs = registry.check(d)
    joined = "\n".join(errs)
    assert "Hikvision: tier 'A' not allowed" in joined
    assert "Hikvision: parser_version 9.9 != code" in joined
    assert "CP Plus: without a parser must claim no proprietary parsing" in joined
    assert "CP Plus: unknown source id NOPE" in joined
    assert "missing target OEM Reolink" in joined


def test_every_source_has_url_date_scope_and_confidence():
    for sid, s in registry.load()["sources"].items():
        assert s["confidence"] in ("high", "medium", "low"), sid
        assert s["url"] and s["retrieved"] and s["says"] and s["does_not_say"], sid


def test_api(client):
    r = client.get("/api/oem-registry").json()
    assert r["consistent_with_code"] is True and r["consistency_problems"] == []
    assert r["targets"] == 16 and r["registry_version"] == 1
