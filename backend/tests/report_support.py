"""Shared helpers for the P7 report tests (SYNTHETIC data only)."""

import io
import json
import re

from pypdf import PdfReader

import app.report.models  # noqa: F401  (table must exist before the client fixture's create_all)
from app.analytics import TRIAGE_LABEL, error_rates
from app.analytics.models import AnalyticsRun, Detection
from app.analytics.registry import MODELS
from app.main import app
from app.models import CarveRun, Clip
from app.report.routes import router

GEN = "2026-01-02T03:04:05.000000+00:00"
NTP = "unknown"


def mount() -> None:
    if not any(getattr(r, "path", "") == "/api/cases/{case_id}/report" for r in app.routes):
        app.include_router(router)


mount()


def pdf_text(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def flat(text: str) -> str:
    """Whitespace-free text: hashes wrap across lines in table cells."""
    return re.sub(r"\s+", "", text)


def pages(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


def unix_ts(field, value, off=100):
    return {
        "field": field,
        "offset": off,
        "raw": value,
        "format": "unix seconds (u32 LE)",
        "wall_clock_as_stored": "",
        "tz_basis": "not assumed",
    }


def make_case(client, session, image, *, n_clips=2, tz="Asia/Kolkata", failed=True, number="R-1"):
    """Case with one evidence item, one run, clips (some with timestamps), a failed decode,
    an orphan, optional tz assumption and one analytics run. Returns a dict of ids."""
    c = client.post("/api/cases", json={"case_number": number, "title": "report test"}).json()
    ev = client.post(
        f"/api/cases/{c['id']}/evidence",
        json={"source_path": str(image), "label": "synthetic HDD", "write_blocker": "yes"},
    ).json()
    if tz:
        r = client.put(
            f"/api/evidence/{ev['id']}/time-assumption",
            json={"timezone": tz, "epoch_basis": "device_local", "notes": "read from DVR menu"},
        )
        assert r.status_code == 200, r.text
    vendor = [
        {
            "vendor": "hikvision",
            "tier": "B",
            "confidence": "medium",
            "evidence": [],
            "signature_counts": {"master_sector": 1},
            "basis": ["docs/RESEARCH.md"],
            "notes": ["synthetic per-paper layout"],
        }
    ]
    parse = [
        {
            "parser": "hikvision",
            "vendor": "Hikvision",
            "tier": "B",
            "status": "partial",
            "options": {
                "block_size_mode": "field",
                "master_sector_offset": "auto",
                "time_basis_label": "unspecified",
            },  # fmt: skip
            "fields": [
                {
                    "name": "block_size_conflict_in_source",
                    "value": "0x400000 vs 1 GB",
                    "status": "unknown",
                    "source": "",
                    "note": "",
                },
                {"name": "master_sector", "value": 1, "status": "parsed"},
                {"name": "x", "value": 1, "status": "inferred"},
            ],
            "inconsistencies": [],
            "warnings": [],
            "stats": {},
            "crosscheck": {
                "parser_clips": 1,
                "generic_clips": 1,
                "disagreements": [{"kind": "frame_count_mismatch"}],
            },  # fmt: skip
        }
    ]
    run = CarveRun(
        case_id=c["id"], evidence_id=ev["id"], status="completed", examiner="Insp. Test",
        params_json=json.dumps({"join_gap": 0, "generic_scope": "uncovered",
                                "parser_options": {"hikvision": {"block_size_mode": "field"}}}),
        vendor_json=json.dumps(vendor), parse_json=json.dumps(parse),
        stats_json=json.dumps({"clips": n_clips, "orphans": 1}), tool_version="0.1.0",
        ffmpeg_version="ffmpeg version test", finished_at="2026-01-01T00:00:00+00:00",
    )  # fmt: skip
    session.add(run)
    session.commit()
    ids = []
    for i in range(n_clips):
        stamps = [unix_ts("first frame", 1_700_000_000 + 100 * i),
                  unix_ts("last frame", 1_700_000_050 + 100 * i, 200)]  # fmt: skip
        clip = Clip(
            run_id=run.id, evidence_id=ev["id"], case_id=c["id"], kind="clip", seq=i + 1,
            codec="h264", start_offset=1000 * i, end_offset=1000 * i + 900, size_bytes=900,
            bitstream_sha256=f"{i:02x}" * 32, mp4_sha256=f"{i + 100:02x}" * 32,
            mp4_path="", decode_status="ok", engine="hikvision", channel=i % 4 + 1,
            duration_s=2.0, packets=50, fps="25/1",
            parsed_json=json.dumps({"timestamps": stamps, "fields": [{"status": "parsed"}]}),
        )  # fmt: skip
        session.add(clip)
        session.commit()
        ids.append(clip.id)
    out = {"case": c["id"], "evidence": ev["id"], "run": run.id, "clips": ids, "ev": ev}
    if failed:
        bad = Clip(
            run_id=run.id, evidence_id=ev["id"], case_id=c["id"], kind="clip", seq=99,
            codec="h264", start_offset=50_000, end_offset=50_100, size_bytes=100,
            bitstream_sha256="ee" * 32, decode_status="decode_errors", engine="generic",
            decode_errors_json=json.dumps(["error while decoding MB 3 4"]),
            error="", parsed_json="{}",
        )  # fmt: skip
        orphan = Clip(
            run_id=run.id, evidence_id=ev["id"], case_id=c["id"], kind="orphan", seq=1,
            codec="unknown", start_offset=60_000, end_offset=60_500, size_bytes=500,
            reason="no IRAP picture before the range ended", engine="generic",
        )  # fmt: skip
        session.add_all([bad, orphan])
        session.commit()
        out["failed_clip"] = bad.id
    spec = MODELS["objects"]
    params = {"conf_threshold": 0.5}
    ar = AnalyticsRun(
        case_id=c["id"], evidence_id=ev["id"], clip_id=ids[0], kind="objects",
        status="completed", examiner="Insp. Test", label=TRIAGE_LABEL,
        bitstream_sha256=f"{0:02x}" * 32, mp4_sha256=f"{100:02x}" * 32,
        params_json=json.dumps(params), model_json=json.dumps(spec.run_info()),
        error_rates_json=json.dumps(error_rates.for_kind("objects", params)),
        tool_json=json.dumps({"nirikshan": "0.1.0"}), frames_analysed=10, result_count=1,
    )  # fmt: skip
    session.add(ar)
    session.commit()
    session.add(
        Detection(run_id=ar.id, clip_id=ids[0], kind="objects", frame_index=3,
                  nominal_time_s=0.12, class_name="person", confidence=0.77,
                  x1=1, y1=1, x2=2, y2=2)
    )  # fmt: skip
    session.commit()
    out["analytics_run"] = ar.id
    out["model"] = spec.run_info()
    return out
