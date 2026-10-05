"""P6 analytics tests. Models must be installed (python scripts/fetch_models.py): tests FAIL,
not skip, when they are missing. Clips here are SYNTHETIC; nothing is validated on DVR footage."""

import json
import socket
import time
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select

from app import custody
from app.analytics import TRIAGE_LABEL, detect, error_rates, frames, motion, runner
from app.analytics import models as amodels
from app.analytics.registry import (
    FETCH_COMMAND,
    MODELS,
    ModelMissing,
    model_status,
    verified_model_path,
)
from app.hashing import hash_file
from app.main import app
from app.models import CarveRun, Clip, CustodyEntry, Evidence
from tests.analytics_media import encode_gray_frames, interval_overlap_scores, motion_clip

SEGMENTS = [(20, 39), (60, 74)]


@pytest.fixture(autouse=True)
def _mount_router():
    from app.analytics.routes import router

    if not any(getattr(r, "path", "") == "/api/analytics/models" for r in app.routes):
        app.include_router(router)


@pytest.fixture(scope="module")
def motion_mp4(tmp_path_factory):
    p = tmp_path_factory.mktemp("an") / "motion.mp4"
    motion_clip(p, SEGMENTS, n_frames=100, size=(352, 288))
    return p


@pytest.fixture(scope="module")
def noise_mp4(tmp_path_factory):
    """Textured SYNTHETIC clip with no real objects (detectors normally return nothing)."""
    p = tmp_path_factory.mktemp("an") / "noise.mp4"
    rng = np.random.default_rng(3)
    f = rng.integers(0, 255, size=(8, 288, 352), dtype=np.uint8)
    encode_gray_frames(f, p)
    return p


def make_clip(session, mp4: Path, tmp_path, *, bitstream="ab" * 32) -> Clip:
    from app.models import Case

    n = session.query(Case).count()
    case = Case(case_number=f"AN-{n + 1}", title="analytics", examiner="Insp. Test")
    session.add(case)
    session.commit()
    ev = Evidence(
        case_id=case.id,
        label="synthetic",
        source_path=str(tmp_path / "x.dd"),
        source_type="file",
        write_blocker="yes",
        status="acquired",
        examiner="Insp. Test",
    )
    session.add(ev)
    session.commit()
    run = CarveRun(case_id=case.id, evidence_id=ev.id, status="completed", examiner="Insp. Test")
    session.add(run)
    session.commit()
    info = frames.probe(mp4)
    clip = Clip(
        run_id=run.id,
        evidence_id=ev.id,
        case_id=case.id,
        kind="clip",
        seq=1,
        codec="h264",
        start_offset=0,
        end_offset=10,
        size_bytes=10,
        bitstream_sha256=bitstream,
        mp4_path=str(mp4),
        mp4_sha256=hash_file(mp4).sha256,
        decode_status="ok",
        width=info.width,
        height=info.height,
        fps=info.fps_text,
    )
    session.add(clip)
    session.commit()
    return clip


# ---------------------------------------------------------------- models and licensing


def test_models_installed_and_hashes_verified():
    """FAILS (does not skip) when models are missing: run `python scripts/fetch_models.py`."""
    status = model_status()
    missing = [s for s in status if not s["installed"]]
    assert not missing, f"models missing, run `{FETCH_COMMAND}`: {[m['error'] for m in missing]}"
    for spec in MODELS.values():
        assert verified_model_path(spec).stat().st_size == spec.size_bytes
        assert spec.licence in ("Apache-2.0", "MIT")  # permissive only; never AGPL/GPL


def test_model_cards_complete():
    for spec in MODELS.values():
        c = spec.card()
        for k in ("name", "version", "url", "sha256", "licence", "licence_url", "labels"):
            assert c[k], k
        assert len(c["sha256"]) == 64 and c["input_size"]


def test_missing_model_gives_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setenv("NIRIKSHAN_MODELS_DIR", str(tmp_path / "empty"))
    with pytest.raises(ModelMissing) as e:
        detect.get_session(MODELS["objects"])
    assert FETCH_COMMAND in str(e.value)
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / MODELS["faces"].filename).write_bytes(b"corrupt")
    with pytest.raises(ModelMissing, match="SHA-256"):
        verified_model_path(MODELS["faces"])


# ---------------------------------------------------------------- motion


def _found(res):
    return [(i["start_frame"], i["end_frame"]) for i in res["intervals"]]


def test_motion_known_answer_intervals(motion_mp4):
    res = motion.analyse_motion(motion_mp4)
    tp, fp, fn = interval_overlap_scores(SEGMENTS, _found(res))
    assert (tp, fp, fn) == (2, 0, 0), _found(res)
    # still frames before the first segment are not motion
    assert all(i["start_frame"] >= 18 for i in res["intervals"])
    for i in res["intervals"]:
        assert i["label"] == TRIAGE_LABEL and i["score_peak"] > 0
        assert i["start_time_s"] == pytest.approx(i["start_frame"] / 25)


def test_motion_low_quality_variant(tmp_path):
    p = tmp_path / "lq.mp4"
    motion_clip(p, SEGMENTS, size=(176, 144), crf=40)
    tp, fp, fn = interval_overlap_scores(SEGMENTS, _found(motion.analyse_motion(p)))
    assert tp == 2 and fp == 0 and fn == 0


def test_motion_static_clip_has_no_intervals(tmp_path):
    p = tmp_path / "still.mp4"
    motion_clip(p, [], size=(320, 240))
    assert motion.analyse_motion(p)["intervals"] == []


def test_motion_deterministic_and_params_reported(motion_mp4):
    a, b = motion.analyse_motion(motion_mp4), motion.analyse_motion(motion_mp4)
    assert a == b
    assert {"threshold", "min_area", "blur", "stride", "width"} <= set(a["params"])
    assert "nominal" in a["time_basis"]


def test_motion_param_validation():
    for bad in (
        {"stride": 0},
        {"threshold": 0},
        {"blur": -1},
        {"bg_alpha": 0},
        {"min_area": 0},
    ):
        with pytest.raises(ValueError):
            motion.MotionParams(**bad).validate()


def test_motion_stride_keeps_frame_indices(motion_mp4):
    res = motion.analyse_motion(motion_mp4, motion.MotionParams(stride=5))
    assert all(s["frame_index"] % 5 == 0 for s in res["samples"])
    assert interval_overlap_scores(SEGMENTS, _found(res), iou_min=0.4)[0] == 2


# ---------------------------------------------------------------- detection post-processing


class FakeSession:
    def __init__(self, outputs, names, in_name="images"):
        self._o, self._names, self._in = outputs, names, in_name

    class _N:
        def __init__(self, name):
            self.name = name

    def get_inputs(self):
        return [self._N(self._in)]

    def get_outputs(self):
        return [self._N(n) for n in self._names]

    def run(self, _, feed):
        assert next(iter(feed.values())).dtype == np.float32
        return self._o


def test_yolox_decode_known_answer():
    out = np.zeros((1, 3549, 85), dtype=np.float32)
    # stride-8 grid cell (col 10, row 20) => index 20*52+10; centre (10+0.5)*8, (20+0.5)*8
    i = 20 * 52 + 10
    out[0, i, :2] = 0.5
    out[0, i, 2:4] = np.log(5.0)  # w = h = 40 px (stride 8) in the 416 letterbox
    out[0, i, 4] = 0.9
    out[0, i, 5 + 2] = 0.8  # class 2 = car
    rgb = np.zeros((208, 208, 3), dtype=np.uint8)  # scale 2.0
    dets = detect.detect_objects_frame(
        rgb, detect.DetectParams(), FakeSession([out], ["output"], "images")
    )
    assert len(dets) == 1 and dets[0]["class_name"] == "car"
    assert dets[0]["confidence"] == pytest.approx(0.72, abs=1e-3)
    x1, y1, x2, y2 = dets[0]["bbox"]
    assert (x1, y1, x2, y2) == pytest.approx((32.0, 72.0, 52.0, 92.0), abs=0.2)
    assert dets[0]["label"] == TRIAGE_LABEL
    assert set(dets[0]) == {"label", "class_name", "confidence", "bbox"}


def test_yunet_decode_known_answer_and_landmarks_discarded():
    names, outs = [], []
    for s, n in ((8, 6400), (16, 1600), (32, 400)):
        names += [f"cls_{s}", f"obj_{s}", f"bbox_{s}", f"kps_{s}"]
        outs += [
            np.zeros((1, n, 1), np.float32),
            np.zeros((1, n, 1), np.float32),
            np.zeros((1, n, 4), np.float32),
            np.zeros((1, n, 10), np.float32),
        ]
    k = names.index("cls_16")
    outs[k][0, 5 * 40 + 7, 0] = 1.0
    outs[k + 1][0, 5 * 40 + 7, 0] = 0.81
    outs[k + 2][0, 5 * 40 + 7] = [0, 0, np.log(4.0), np.log(4.0)]  # 64x64 px at stride 16
    rgb = np.zeros((320, 320, 3), dtype=np.uint8)  # scale 2.0 => box halves in frame pixels
    dets = detect.detect_faces_frame(
        rgb, detect.DetectParams(conf_threshold=0.5), FakeSession(outs, names, "input")
    )
    assert len(dets) == 1 and dets[0]["confidence"] == pytest.approx(0.9, abs=1e-3)
    assert dets[0]["bbox"] == pytest.approx([40.0, 24.0, 72.0, 56.0], abs=0.2)
    assert set(dets[0]) == {"label", "class_name", "confidence", "bbox"}  # no landmarks/embedding


def test_nms_deterministic_tie_break():
    boxes = np.array([[0, 0, 10, 10], [0, 0, 10, 10], [50, 50, 60, 60]], dtype=np.float32)
    assert detect.nms(boxes, np.array([0.5, 0.5, 0.4]), 0.5) == [0, 2]


def test_detect_param_validation():
    with pytest.raises(ValueError):
        detect.DetectParams(conf_threshold=1.5).validate()
    with pytest.raises(ValueError):
        detect.DetectParams(stride=0).validate()


# ---------------------------------------------------------------- detection on real models


@pytest.mark.parametrize("kind", ["objects", "faces"])
def test_detection_deterministic_repeated_runs(noise_mp4, kind):
    p = detect.DetectParams(stride=2, conf_threshold=0.05)
    runs = [detect.analyse_detections(noise_mp4, kind, p) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    assert runs[0]["frames_analysed"] == 4 and runs[0]["label"] == TRIAGE_LABEL
    assert all(d["label"] == TRIAGE_LABEL for d in runs[0]["detections"])


def test_detection_outputs_contain_no_identity_or_embedding_fields(noise_mp4):
    forbidden = ("embed", "identity", "identif", "person_id", "name_match", "match", "landmark")
    for kind in ("objects", "faces"):
        res = detect.analyse_detections(noise_mp4, kind, detect.DetectParams(conf_threshold=0.002))
        keys = set(res) | {k for d in res["detections"] for k in d}
        for k in keys - {"label"}:
            assert not any(f in k.lower() for f in forbidden), k
    cols = {c.name for t in (amodels.Detection, amodels.AnalyticsRun) for c in t.__table__.columns}
    assert not any(f in c.lower() for c in cols for f in forbidden[:-2]), cols
    # the face model exposes no embedding head: only detection heads
    sess = detect.get_session(MODELS["faces"])
    assert all(o.name.split("_")[0] in ("cls", "obj", "bbox", "kps") for o in sess.get_outputs())


def test_cpu_provider_only():
    assert detect.get_session(MODELS["objects"]).get_providers() == ["CPUExecutionProvider"]


def test_runtime_budget_cpu(noise_mp4):
    """Generous bounds; the measured value is in the failure message."""
    p = detect.DetectParams(stride=1, conf_threshold=0.3)
    for kind, bound_ms in (("objects", 1500.0), ("faces", 1500.0)):
        detect.analyse_detections(noise_mp4, kind, p)  # warm-up (session load)
        t = time.perf_counter()
        res = detect.analyse_detections(noise_mp4, kind, p)
        ms = (time.perf_counter() - t) * 1000 / res["frames_analysed"]
        assert ms < bound_ms, f"{kind}: {ms:.1f} ms/frame (bound {bound_ms})"
    t = time.perf_counter()
    res = motion.analyse_motion(noise_mp4)
    ms = (time.perf_counter() - t) * 1000 / res["frames_analysed"]
    assert ms < 500.0, f"motion: {ms:.1f} ms/frame"


# ---------------------------------------------------------------- API, DB, custody


def post(client, clip_id, kind, params=None):
    return client.post(
        f"/api/clips/{clip_id}/analytics", json={"kind": kind, "params": params or {}}
    )


def test_api_motion_run_persists_label_hashes_and_custody(client, session, motion_mp4, tmp_path):
    clip = make_clip(session, motion_mp4, tmp_path, bitstream="cd" * 32)
    r = post(client, clip.id, "motion")
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "completed" and run["label"] == TRIAGE_LABEL
    assert len(run["intervals"]) == 2 and run["bitstream_sha256"] == "cd" * 32
    assert run["params"]["threshold"] == 25 and run["tool"]["nirikshan"]
    assert (
        run["error_rates"]["configs"] and "synthetic" in run["error_rates"]["configs"][0]["label"]
    )
    assert run["error_rates"]["run_params_match_measured"] is True
    assert all(i["label"] == TRIAGE_LABEL for i in run["intervals"])
    got = client.get(f"/api/analytics/{run['id']}").json()
    assert got["intervals"] == run["intervals"]
    listing = client.get(f"/api/clips/{clip.id}/analytics").json()
    assert [x["id"] for x in listing] == [run["id"]]
    entry = session.scalars(
        select(CustodyEntry).where(CustodyEntry.action == "analytics_run")
    ).one()
    d = json.loads(entry.details_json)
    assert d["bitstream_sha256"] == "cd" * 32 and d["mp4_sha256"] == clip.mp4_sha256
    assert d["params"]["threshold"] == 25 and d["label"] == TRIAGE_LABEL and d["kind"] == "motion"
    assert entry.examiner == "Insp. Test" and entry.tool_version
    assert custody.verify_chain(session, clip.case_id)["ok"]


@pytest.mark.parametrize("kind", ["objects", "faces"])
def test_api_detection_run_records_model_and_error_rates(
    client, session, noise_mp4, tmp_path, kind
):
    clip = make_clip(session, noise_mp4, tmp_path)
    r = post(client, clip.id, kind, {"stride": 2, "conf_threshold": 0.3})
    assert r.status_code == 201, r.text
    run = r.json()
    spec = MODELS[kind]
    assert run["model"]["sha256"] == spec.sha256 and run["model"]["licence"] == spec.licence
    assert run["model"]["name"] == spec.name and run["model"]["version"]
    assert run["tool"]["execution_provider"] == "CPUExecutionProvider"
    assert run["error_rates"]["configs"], "error rates must accompany every detection run"
    assert run["frames_analysed"] == 4
    d = json.loads(
        session.scalars(select(CustodyEntry).where(CustodyEntry.action == "analytics_run"))
        .one()
        .details_json
    )
    assert d["models"][0]["sha256"] == spec.sha256


def test_api_persists_detection_rows_with_label(client, session, noise_mp4, tmp_path, monkeypatch):
    fake = {
        "label": TRIAGE_LABEL,
        "class_name": "person",
        "confidence": 0.87,
        "bbox": [1.0, 2.0, 30.0, 40.0],
    }
    monkeypatch.setitem(detect.FRAME_FUNCS, "objects", lambda rgb, p, s=None: [dict(fake)])
    clip = make_clip(session, noise_mp4, tmp_path)
    run = post(client, clip.id, "objects", {"stride": 4}).json()
    assert run["result_count"] == 2
    d = run["detections"][0]
    assert d["label"] == TRIAGE_LABEL and d["class_name"] == "person" and d["confidence"] == 0.87
    assert d["frame_index"] == 0 and d["nominal_time_s"] == 0.0
    assert run["detections"][1]["frame_index"] == 4
    assert run["detections"][1]["nominal_time_s"] == pytest.approx(4 / 25)
    rows = session.scalars(select(amodels.Detection)).all()
    assert len(rows) == 2 and all(r.label == TRIAGE_LABEL for r in rows)


def test_api_error_cases(client, session, motion_mp4, tmp_path):
    clip = make_clip(session, motion_mp4, tmp_path)
    assert post(client, 9999, "motion").status_code == 404
    assert post(client, clip.id, "recognition").status_code == 422
    assert post(client, clip.id, "motion", {"bogus": 1}).status_code == 422
    assert post(client, clip.id, "motion", {"threshold": 0}).status_code == 422
    assert client.get("/api/analytics/9999").status_code == 404
    assert client.get("/api/clips/9999/analytics").status_code == 404
    bad = client.post(
        f"/api/clips/{clip.id}/analytics", json={"kind": "motion"}, headers={"X-Examiner": ""}
    )
    assert bad.status_code == 400  # examiner attestation required


def test_api_refuses_tampered_mp4(client, session, tmp_path):
    p = tmp_path / "t.mp4"
    motion_clip(p, SEGMENTS, n_frames=40, size=(160, 120))
    clip = make_clip(session, p, tmp_path)
    p.chmod(0o644)
    p.write_bytes(p.read_bytes() + b"\x00")
    r = post(client, clip.id, "motion")
    assert r.status_code == 409 and "SHA-256" in r.text
    assert session.scalars(select(amodels.AnalyticsRun)).all() == []


def test_api_models_missing_is_503_with_fetch_command(
    client, session, noise_mp4, tmp_path, monkeypatch
):
    clip = make_clip(session, noise_mp4, tmp_path)
    monkeypatch.setenv("NIRIKSHAN_MODELS_DIR", str(tmp_path / "nomodels"))
    r = post(client, clip.id, "faces")
    assert r.status_code == 503 and FETCH_COMMAND in r.json()["detail"]
    assert post(client, clip.id, "motion").status_code == 201  # motion needs no model
    info = client.get("/api/analytics/models").json()
    assert info["label"] == TRIAGE_LABEL and not any(m["installed"] for m in info["models"])


def test_api_models_listing(client):
    info = client.get("/api/analytics/models").json()
    assert {m["key"] for m in info["models"]} == {"objects", "faces"}
    assert all(m["licence"] and m["sha256"] for m in info["models"])
    assert "entries" in info["error_rates"]


def test_no_network_during_analysis(client, session, motion_mp4, noise_mp4, tmp_path, monkeypatch):
    clips = [make_clip(session, motion_mp4, tmp_path), make_clip(session, noise_mp4, tmp_path)]
    assert post(client, clips[0].id, "motion").status_code == 201  # warm-up: loop/threads exist

    class NoSocket(socket.socket):
        def __init__(self, *a, **k):
            raise AssertionError("network/socket use is forbidden during analytics")

    def no_dns(*a, **k):
        raise AssertionError("name resolution is forbidden during analytics")

    monkeypatch.setattr(socket, "socket", NoSocket)
    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    monkeypatch.setattr(socket, "create_connection", no_dns)
    runs = [
        runner.run_analytics(session, clips[0], "motion", {}, "Insp. Test"),
        runner.run_analytics(session, clips[1], "objects", {"stride": 4}, "Insp. Test"),
        runner.run_analytics(session, clips[1], "faces", {"stride": 4}, "Insp. Test"),
    ]
    assert [r.status for r in runs] == ["completed"] * 3


def test_error_rates_file_matches_what_the_ui_shows():
    rates = error_rates.load()
    assert rates["label"] == TRIAGE_LABEL and "real DVR" in rates["statement"]
    for kind in ("objects", "faces", "motion"):
        for c in rates["entries"][kind]["configs"]:
            assert "synthetic" in c["label"] or "public benchmark" in c["label"]
            assert c["precision"] is None or 0 <= c["precision"] <= 1
    e = error_rates.for_kind("objects", {"conf_threshold": 0.3})
    assert e["run_threshold_measured"] is True
    assert (
        error_rates.for_kind("objects", {"conf_threshold": 0.33})["run_threshold_measured"] is False
    )
