"""Test-only builders: clips with DHAV-style timestamps and STORED analytics rows.

The rows inserted here are test fixtures (reference test data), standing in for what
app.analytics.runner persists; the production index reads the same tables.
"""

import json

from app.analytics import TRIAGE_LABEL
from app.analytics.models import AnalyticsRun, Detection, MotionInterval
from app.analytics.registry import MODELS
from app.models import CarveRun, Clip

DHAV = "DHAV date u32 LE bit-packed (dhav.c get_timeinfo)"


def pack(y, mo, d, h, mi, s) -> int:
    return s | mi << 6 | h << 12 | d << 17 | mo << 22 | (y - 2000) << 26


def new_case(client, image, number="EV-1", n_evidence=1):
    c = client.post("/api/cases", json={"case_number": number, "title": "events"}).json()
    evs = [
        client.post(
            f"/api/cases/{c['id']}/evidence",
            json={"source_path": str(image), "label": f"HDD{i}", "write_blocker": "no"},
        ).json()
        for i in range(n_evidence)
    ]
    return c, evs


def set_tz(client, ev_id, tz="Asia/Kolkata"):
    r = client.put(
        f"/api/evidence/{ev_id}/time-assumption", json={"timezone": tz, "notes": "device menu"}
    )
    assert r.status_code == 200, r.text


def add_clip(session, case_id, ev_id, channel, first=None, offset=0):
    run = CarveRun(case_id=case_id, evidence_id=ev_id, status="completed", examiner="x")
    session.add(run)
    session.commit()
    stamps = []
    if first:
        stamps.append(
            {"field": "first frame date", "offset": 16, "raw": pack(*first), "format": DHAV,
             "tz_basis": "not assumed"}
        )  # fmt: skip
    clip = Clip(
        run_id=run.id, evidence_id=ev_id, case_id=case_id, kind="clip", seq=1, codec="h264",
        start_offset=offset, end_offset=offset + 4096, size_bytes=4096, engine="Dahua",
        channel=channel, parsed_json=json.dumps({"timestamps": stamps}), duration_s=60.0,
        bitstream_sha256="ab" * 32, mp4_sha256="cd" * 32,
        extents_json=json.dumps([[offset, offset + 4096]]),
    )  # fmt: skip
    session.add(clip)
    session.commit()
    return clip


def add_detections(session, clip, kind, dets):
    """dets: [(frame_index, nominal_time_s, class_name, confidence)]"""
    spec = MODELS[kind]
    run = AnalyticsRun(
        case_id=clip.case_id, evidence_id=clip.evidence_id, clip_id=clip.id, kind=kind,
        status="completed", examiner="x", label=TRIAGE_LABEL,
        bitstream_sha256=clip.bitstream_sha256,
        mp4_sha256=clip.mp4_sha256, model_json=json.dumps(spec.run_info()),
    )  # fmt: skip
    session.add(run)
    session.commit()
    for f, t, cls, conf in dets:
        session.add(
            Detection(run_id=run.id, clip_id=clip.id, kind=kind, frame_index=f, nominal_time_s=t,
                      class_name=cls, confidence=conf, x1=1, y1=2, x2=30, y2=40)
        )  # fmt: skip
    session.commit()
    return run


def add_motion(session, clip, intervals):
    """intervals: [(start_frame, end_frame, start_s, end_s, peak)]"""
    run = AnalyticsRun(
        case_id=clip.case_id, evidence_id=clip.evidence_id, clip_id=clip.id, kind="motion",
        status="completed", examiner="x", label=TRIAGE_LABEL, model_json="null",
    )  # fmt: skip
    session.add(run)
    session.commit()
    for f0, f1, t0, t1, peak in intervals:
        session.add(
            MotionInterval(run_id=run.id, clip_id=clip.id, start_frame=f0, end_frame=f1,
                           start_time_s=t0, end_time_s=t1, n_samples=3, score_peak=peak,
                           score_mean=peak / 2)
        )  # fmt: skip
    session.commit()
    return run
