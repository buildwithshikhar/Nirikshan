"""Demo data creation end to end: through the ASGI app (TestClient) and as a real subprocess."""

import json
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

from sqlalchemy import select

from app import custody, demo_data
from app.models import CarveRun, Clip, CustodyEntry, Evidence
from app.timeline.models import ReferenceObservation, TimeAssumption

ROOT = Path(__file__).resolve().parents[2]


def test_seed_builds_the_synthetic_demo_case(client, tmp_path, session):
    lines: list[str] = []
    api = demo_data.ClientApi(client)
    summary = demo_data.seed(api, tmp_path / "evidence", log=lines.append, poll=0.1)
    cid = summary["case_id"]
    case = client.get(f"/api/cases/{cid}").json()
    assert case["case_number"] == "DEMO-REFERENCE-001"
    assert (
        "Reference test data" in case["title"]
        and "not captured from a physical DVR" in case["title"]
    )

    ev = client.get(f"/api/cases/{cid}/evidence").json()
    assert len(ev) == 3 and all(e["synthetic"] and "Reference data" in e["label"] for e in ev)
    # three completed runs, clips with exported video, the vendors identified by their parsers
    runs = session.scalars(select(CarveRun).order_by(CarveRun.id)).all()
    assert [r.status for r in runs] == ["completed"] * 3
    vendors = [{m["vendor"] for m in json.loads(r.vendor_json)} for r in runs]
    assert vendors == [{"Hikvision"}, {"Dahua"}, set()]
    clips = session.scalars(select(Clip).where(Clip.kind == "clip")).all()
    assert len(clips) >= 7 and all(c.decode_status == "ok" for c in clips)

    # P5: the raw image is left without a timezone on purpose; the others have assumptions
    rows = {a.evidence_id: a for a in session.scalars(select(TimeAssumption))}
    raw_id = summary["unknown_timezone_evidence"]
    assert raw_id not in rows and len(rows) == 2
    assert len(session.scalars(select(ReferenceObservation)).all()) == 2
    tl = client.get(f"/api/cases/{cid}/timeline").json()
    assert tl["evidence_without_timezone"] == [raw_id]

    # analytics ran at least for motion (models may be absent for objects/faces: then skipped)
    assert "motion" in summary["analytics"]
    # job progress was visible and the report step was skipped or done explicitly
    assert any("%" in ln and "job" in ln for ln in lines)
    assert any(s.startswith("report") for s in summary["skipped"]) or "report" in summary

    jobs = client.get(f"/api/cases/{cid}/jobs").json()
    assert [j["status"] for j in jobs] == ["completed"] * 3
    acts = [e.action for e in session.scalars(select(CustodyEntry).order_by(CustodyEntry.seq))]
    assert acts.count("evidence_acquired") == 3 and acts.count("time_assumption_set") == 2
    assert custody.verify_chain(session, cid)["ok"] is True
    assert all(e.synthetic for e in session.scalars(select(Evidence)))

    # running it again does not duplicate the case
    again = demo_data.seed(api, tmp_path / "evidence", log=lines.append)
    assert again["already_existed"] is True and again["case_id"] == cid
    assert len(client.get("/api/cases").json()) == 1


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_demo_script_runs_end_to_end_in_a_subprocess(tmp_path):
    """`scripts/demo.py --no-web --exit-after-seed`: starts uvicorn on a free port with an
    isolated data dir and demo-only keys, seeds, prints the reference-data banner, exits cleanly."""
    data = tmp_path / "demo-data"
    port = free_port()
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "demo.py"),
            "--data-dir",
            str(data),
            "--api-port",
            str(port),
            "--no-web",
            "--exit-after-seed",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "REFERENCE TEST DATA" in out and "DEMO-REFERENCE-001" in out and "[6/6] report" in out
    assert (data / "demo.db").is_file() and (data / "keys").is_dir()
    assert any((data / "data" / "cases").rglob("*.mp4"))
    # the server was stopped when the script exited
    try:
        urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2)
        raise AssertionError("backend still running after the demo script exited")
    except OSError:
        pass
