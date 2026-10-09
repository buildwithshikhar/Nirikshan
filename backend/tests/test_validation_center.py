"""Validation Center API over the committed results (reference test data) and the sandboxed
re-run. The committed baseline must never change."""

import hashlib
import json
import shutil
import time

import pytest

from app.validation_center import rerun
from app.validation_center import results as vres
from app.validation_center.models import ValidationRerun
from tests import stream3  # noqa: F401

COMMITTED = vres.REPO_ROOT / "docs" / "validation" / "results.json"
ENDPOINTS = ("summary", "scorecards", "regression", "false-rates", "crosscheck")


def committed_sha() -> str:
    return hashlib.sha256(COMMITTED.read_bytes()).hexdigest()


def numbers_have_basis(obj, path="") -> list[str]:
    """Every metric-like dict (has 'rate' or 'count') must carry the basis statement."""
    bad = []
    if isinstance(obj, dict):
        if ("rate" in obj or "count" in obj) and obj.get("basis") != vres.BASIS:
            bad.append(path)
        for k, v in obj.items():
            bad += numbers_have_basis(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += numbers_have_basis(v, f"{path}[{i}]")
    return bad


@pytest.fixture
def baseline_copy(tmp_path, monkeypatch):
    p = tmp_path / "baseline" / "results.json"
    p.parent.mkdir()
    shutil.copy(COMMITTED, p)
    monkeypatch.setenv(vres.ENV, str(p))
    return p


def test_default_path_is_repo_docs(monkeypatch):
    monkeypatch.delenv(vres.ENV, raising=False)
    assert vres.results_path() == COMMITTED and COMMITTED.is_file()


def test_summary_and_digest(client):
    s = client.get("/api/validation/summary").json()
    assert s["available"] is True and s["digest_verified"] is True
    assert s["results_digest"] == json.loads(COMMITTED.read_text())["results_digest"]
    assert s["synthetic"] is True and "Reference test data" in s["headline"]
    assert "circular check" in s["basis"] and "Tier B" in s["tier_limit"]
    assert s["scenario_results"]["count"] == len(json.loads(COMMITTED.read_text())["scenarios"])
    assert not numbers_have_basis(s)


@pytest.mark.parametrize("ep", ENDPOINTS)
def test_unavailable_when_missing_or_invalid(client, tmp_path, monkeypatch, ep):
    monkeypatch.setenv(vres.ENV, str(tmp_path / "nope.json"))
    r = client.get(f"/api/validation/{ep}").json()
    assert r["available"] is False and "not found" in r["reason"]
    (tmp_path / "bad.json").write_text("{not json")
    monkeypatch.setenv(vres.ENV, str(tmp_path / "bad.json"))
    r = client.get(f"/api/validation/{ep}").json()
    assert r["available"] is False and "not a validation result" in r["reason"]


def test_scorecards_tiers_and_basis_on_every_number(client):
    r = client.get("/api/validation/scorecards").json()
    cards = {c["vendor"]: c for c in r["vendors"]}
    assert set(cards) == {"Generic carver", "Dahua", "Hikvision", "Honeywell"}
    for v in ("Dahua", "Hikvision", "Honeywell"):
        assert cards[v]["tier"] == "B"  # never above Tier B
        assert [e["engine"] for e in cards[v]["engines"]] == [v.lower(), f"{v.lower()}+generic"]
    assert cards["Generic carver"]["tier"].startswith("n/a")
    sc = cards["Generic carver"]["engines"][0]["scenarios"]
    clean = next(s for s in sc if s["id"] == "clean_live")
    assert clean["recall"]["k"] == clean["recall"]["n"] == 60 and clean["recall"]["rate"] == 1.0
    pooled = cards["Dahua"]["engines"][0]["pooled_recall"]
    assert pooled["pooled_over"] > 0 and "descriptive only" in pooled["note"]
    assert not numbers_have_basis(r)


def test_regression_pass_and_detects_drop(client, baseline_copy):
    r = client.get("/api/validation/regression").json()
    assert r["status"] == "pass" and r["violations"] == []
    assert r["stored_matches_recomputed"] is True and r["require_present"] is True
    assert all(x["pass"] for x in r["rules"]) and not numbers_have_basis(r)
    res = json.loads(baseline_copy.read_text())
    sc = next(s for s in res["scenarios"] if s["id"] == "clean_live")
    sc["metrics"]["clip_recall"]["rate"] = 0.5
    baseline_copy.write_text(json.dumps(res))
    r = client.get("/api/validation/regression").json()
    assert r["status"] == "fail" and r["violations"] == ["clean_live.clip_recall: 0.5 < min 1.0"]
    assert r["stored_matches_recomputed"] is False
    failed = [x for x in r["rules"] if not x["pass"]]
    assert [(x["scenario"], x["metric"]) for x in failed] == [("clean_live", "clip_recall")]
    s = client.get("/api/validation/summary").json()
    assert s["digest_verified"] is False  # edited file no longer matches its digest


def test_false_rates_and_crosscheck(client):
    f = client.get("/api/validation/false-rates").json()
    assert f["negative_scenarios"] and all(
        n["false_accept_decodable_clips"]["k"] == 0 for n in f["negative_scenarios"]
    )
    assert f["reassembler"] and "reassembler_false_accept" in f["reassembler"][0]
    fp = next(x for x in f["positive_scenario_false_positives"] if x["id"] == "clean_live")
    assert fp["false_positive_clips"]["k"] == 0 and fp["false_positive_clips"]["n"] == 60
    assert not numbers_have_basis(f)
    x = client.get("/api/validation/crosscheck").json()
    assert "frame_count_mismatch" in x["benign_definition"]
    assert x["totals_by_vendor"]["dahua"]["frame_count_mismatch"]["count"] > 0
    assert all(s["engine"] != "generic" for s in x["scenarios"])
    assert not numbers_have_basis(x)


def wait(client, rid, limit=240):
    t0 = time.time()
    while time.time() - t0 < limit:
        r = client.get(f"/api/validation/reruns/{rid}").json()
        if r["status"] not in ("queued", "running"):
            return r
        time.sleep(0.5)
    raise AssertionError("re-run did not finish")


def test_rerun_subset_in_temp_dir_never_touches_baseline(client, baseline_copy):
    before = committed_sha()
    copy_before = hashlib.sha256(baseline_copy.read_bytes()).hexdigest()
    assert client.post("/api/validation/reruns", json={"scenarios": ["nope"]}).status_code == 422
    r = client.post(
        "/api/validation/reruns",
        json={"trials": 1, "scenarios": ["clean_live"], "export": False},
    )
    assert r.status_code == 202, r.text
    rid = r.json()["id"]
    assert r.json()["command"][1:3] == ["-m", "app.validation.run"]
    busy = client.post("/api/validation/reruns", json={"trials": 1, "scenarios": ["clean_live"]})
    assert busy.status_code == 409
    done = wait(client, rid)
    assert done["status"] == "completed", done
    assert done["baseline_unchanged"] is True and done["out_dir"] != str(baseline_copy.parent)
    cmp = done["comparison"]
    assert cmp["digest_match"] is False and cmp["comparable"] is False
    fields = {d["field"] for d in cmp["parameter_or_version_differences"]}
    assert {"trials", "export_decode_test", "scenarios"} <= fields
    assert cmp["scenario_results_compared"] == 1 and cmp["basis"] == vres.BASIS
    # export off: the decode/hash thresholds have no data, which the check reports honestly
    assert cmp["rerun_threshold_violations"]
    assert all(
        v.startswith(("clean_live.decode_ok", "clean_live.hash_integrity"))
        for v in cmp["rerun_threshold_violations"]
    )
    assert committed_sha() == before
    assert hashlib.sha256(baseline_copy.read_bytes()).hexdigest() == copy_before
    assert client.get("/api/validation/reruns").json()[0]["id"] == rid


def test_rerun_timeout_kills_process(client, baseline_copy, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_VALIDATION_TIMEOUT_S", "1")
    r = client.post("/api/validation/reruns", json={})  # full default run: far longer than 1 s
    done = wait(client, r.json()["id"], limit=60)
    assert done["status"] == "timeout" and "killed after 1 s" in done["error"]


def test_orphaned_rerun_reports_interrupted(client, session):
    row = ValidationRerun(status="running", examiner="x")
    session.add(row)
    session.commit()
    assert not rerun.is_active(row.id)
    assert client.get(f"/api/validation/reruns/{row.id}").json()["status"] == "interrupted"
    assert client.get("/api/validation/reruns/9999").status_code == 404
