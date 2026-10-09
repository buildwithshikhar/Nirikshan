"""Recoverability rule, its measured agreement file, and the reassembly false-accept exposure."""

import json

import pytest

from app.carving.export import find_tool
from app.recover import measure
from app.recover import routes as R
from app.recover.estimate import RULE_VERSION, band, estimate, limitations
from tests import stream2  # noqa: F401
from tests.media import filler

BASE = {
    "kind": "clip",
    "engine": "generic",
    "codec": "h264",
    "decode_status": "ok",
    "decode_errors": [],
    "irap_count": 2,
    "vcl_count": 50,
    "nal_count": 54,
    "reassembled": False,
    "extent_count": 1,
    "end_reason": "end of image",
    "validate_params": True,
}


@pytest.mark.parametrize(
    "change,value,band",
    [
        ({}, 1.0, "high"),
        ({"decode_status": "decode_errors", "decode_errors": ["x"]}, 0.5, "medium"),
        ({"decode_status": "export_failed"}, 0.0, "low"),
        ({"reassembled": True}, 0.5, "medium"),
        ({"irap_count": 0}, 0.0, "low"),
        ({"engine": "Hikvision", "validate_params": None}, 1.0, "high"),  # decoder accepted it
        (
            {"engine": "Hikvision", "validate_params": None, "decode_status": "decode_errors"},
            0.375,
            "low",
        ),
    ],
)
def test_rule_values(change, value, band):
    e = estimate(BASE | change)
    assert e["available"] and e["rule_version"] == RULE_VERSION
    assert e["estimate"] == value and e["band"] == band
    assert [c["name"] for c in e["components"]] == [
        "decode_test",
        "irap_present",
        "nal_continuity",
        "header_validity",
    ]
    assert e["explanation"].endswith(f"= {value}")


def test_no_decode_test_means_no_estimate_and_orphans_are_zero():
    e = estimate(BASE | {"decode_status": "not_exported"})
    assert e["available"] is False and "decode test" in e["reason"]
    o = estimate(BASE | {"kind": "orphan"})
    assert o["estimate"] == 0.0 and o["band"] == "low"


def test_limitations_text():
    lim = limitations(BASE | {"reassembled": True, "codec": "h265"}, fa_rate=0.1178)
    text = " ".join(lim)
    assert "11.8%" in text and "H.265" in text and "absorbed" in text
    assert "reference test images" in lim[0]
    assert any("Hikvision parser" in x for x in limitations(BASE | {"engine": "Hikvision"}))


def test_reassembly_false_accept_comes_from_committed_results():
    m = R.reassembly_measurement()
    assert m["available"] and m["default"] == "off"
    res = json.loads(R.RESULTS.read_text())
    want = {
        s["id"]: s["metrics"]["reassembler_false_accept"]
        for s in res["scenarios"]
        if "reassembler_false_accept" in s["metrics"]
    }
    assert {r["scenario"]: r["false_accept"] for r in m["scenarios"]} == want
    assert m["pooled_false_accept"]["n"] == sum(v["n"] for v in want.values())
    assert m["results_digest"] == res["results_digest"]


def test_reassembly_unavailable_without_results(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "RESULTS", tmp_path / "missing.json")
    m = R.reassembly_measurement()
    assert m["available"] is False and "not found" in m["reason"]


def test_committed_agreement_file_is_self_consistent():
    res = json.loads(R.AGREEMENT.read_text())
    assert res["synthetic"] is True and res["rule_version"] == RULE_VERSION
    assert measure.stats(res["clips"]) == res["overall"]  # summary not hand-edited
    for row in res["clips"]:
        assert band(row["estimate"]) == row["band"]
        assert 0.0 <= row["actual"] <= 1.0
    s = R.agreement_summary()
    assert s["available"] and s["overall"]["clips"] == len(res["clips"])


def test_stats_helpers():
    assert measure.pearson([0, 1, 2], [0, 1, 2]) == 1.0
    assert measure.pearson([1, 1, 1], [0, 1, 2]) is None  # constant estimate: undefined
    assert measure._ranks([3, 1, 1]) == [3.0, 1.5, 1.5]


@pytest.mark.skipif(find_tool("ffmpeg") is None, reason="ffmpeg not installed")
def test_measure_run_on_clean_images_agrees():
    res = measure.run(20260101, 1, {"clean_live"})
    o = res["overall"]
    assert o["clips"] == 3 and o["mean_absolute_error"] == 0.0
    assert all(r["estimate"] == 1.0 and r["actual"] == 1.0 for r in res["clips"])


@pytest.mark.skipif(find_tool("ffmpeg") is None, reason="ffmpeg not installed")
def test_api_clip_recoverability(client, tmp_path, streams):
    p = tmp_path / "img.dd"
    p.write_bytes(filler(3000, 1) + streams["h264_baseline"] + filler(3000, 2))
    c = client.post("/api/cases", json={"case_number": "RC-1", "title": "rec"}).json()
    ev = client.post(
        f"/api/cases/{c['id']}/evidence",
        json={"source_path": str(p), "label": "x", "write_blocker": "yes"},
    ).json()
    run = client.post(f"/api/evidence/{ev['id']}/analyze").json()
    clip = next(x for x in run["clips"] if x["kind"] == "clip")
    r = client.get(f"/api/clips/{clip['id']}/recoverability").json()
    assert r["available"] and r["estimate"] == 1.0 and r["band"] == "high"
    assert r["limitations"] and r["measured_agreement"]["available"]
    assert client.get("/api/clips/99999/recoverability").status_code == 404
    fr = client.get("/api/recovery/fragment-reassembly").json()
    assert fr["available"] and fr["default"] == "off"
    assert client.get("/api/recovery/agreement").json()["available"]
