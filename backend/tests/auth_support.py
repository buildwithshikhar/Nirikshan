"""Helpers for tests that run with real authentication (dev header mode OFF)."""

from dataclasses import dataclass, field

import pytest

from app.auth.routes import create_user

PASSWORD = "correct horse battery staple"  # test-only credential, created per test database


def make_user(session, username: str, role: str, display: str | None = None, password=PASSWORD):
    return create_user(session, username, display or username.title(), role, password, "test")


def login(client, username: str, password: str = PASSWORD) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    client.cookies.clear()  # tests choose explicitly between bearer and cookie
    return r.json()["token"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class World:
    """Two cases owned by different examiners, plus one of every case-scoped object in each."""

    tokens: dict = field(default_factory=dict)
    users: dict = field(default_factory=dict)
    cases: dict = field(default_factory=dict)  # "A" / "B" -> {"case_id":..., "evidence_id":...}

    def h(self, who: str) -> dict:
        return bearer(self.tokens[who])


def seed_objects(session, case_id: int, evidence_id: int, tmp_path) -> dict:
    """Create a run, clip, analytics run, job and report row directly (no ffmpeg needed)."""
    from app.analytics.models import AnalyticsRun
    from app.jobs.models import Job
    from app.models import CarveRun, Clip
    from app.report.models import Report

    run = CarveRun(case_id=case_id, evidence_id=evidence_id, status="completed", examiner="seed")
    session.add(run)
    session.commit()
    clip = Clip(
        run_id=run.id, evidence_id=evidence_id, case_id=case_id, kind="clip", seq=1,
        codec="h264", start_offset=0, end_offset=10, size_bytes=10,
    )  # fmt: skip
    session.add(clip)
    session.commit()
    arun = AnalyticsRun(
        case_id=case_id, evidence_id=evidence_id, clip_id=clip.id, kind="motion",
        status="completed", examiner="seed",
    )  # fmt: skip
    job = Job(
        kind="analyze", case_id=case_id, evidence_id=evidence_id, examiner="seed",
        idempotency_key=f"seed{case_id}", status="completed",
    )  # fmt: skip
    pdf = tmp_path / f"seed_report_{case_id}.pdf"
    pdf.write_bytes(b"%PDF-1.4 seed")
    import hashlib

    rep = Report(
        case_id=case_id, file_name=pdf.name, file_path=str(pdf),
        sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(), examiner="seed",
    )  # fmt: skip
    from app.package.models import Package

    pkg = Package(
        case_id=case_id, file_name="seed.zip", file_path=str(pdf), sha256=rep.sha256,
        size_bytes=1, manifest_sha256="0" * 64, signature_hex="0" * 128, key_id="0" * 16,
        file_count=0, head_hash_built_from="0" * 64, created_by="seed",
    )  # fmt: skip
    session.add_all([arun, job, rep, pkg])
    session.commit()
    return {
        "package_id": pkg.id,
        "run_id": run.id,
        "clip_id": clip.id,
        "analytics_run_id": arun.id,
        "job_id": job.id,
        "report_id": rep.id,
    }


@pytest.fixture
def world(client, session, no_dev_auth, tmp_path):
    client.headers.pop("X-Examiner", None)
    w = World()
    for name, role in (
        ("admin1", "admin"),
        ("exam1", "examiner"),
        ("exam2", "examiner"),
        ("rev1", "reviewer"),
        ("ro1", "readonly"),
    ):
        w.users[name] = make_user(session, name, role)
        w.tokens[name] = login(client, name)
    for label, owner in (("A", "exam1"), ("B", "exam2")):
        r = client.post(
            "/api/cases",
            json={"case_number": f"AUTH-{label}", "title": f"case {label}"},
            headers=w.h(owner),
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        src = tmp_path / f"src_{label}.dd"
        src.write_bytes(bytes(range(256)) * 64)
        r = client.post(
            f"/api/cases/{cid}/evidence",
            json={"source_path": str(src), "label": label, "write_blocker": "yes"},
            headers=w.h(owner),
        )
        assert r.status_code == 201, r.text
        eid = r.json()["id"]
        w.cases[label] = {
            "case_id": cid,
            "evidence_id": eid,
            **seed_objects(session, cid, eid, tmp_path),
        }
    return w


def add_member(client, w: World, case: str, user: str):
    r = client.post(
        f"/api/cases/{w.cases[case]['case_id']}/members",
        json={"user_id": w.users[user].id},
        headers=w.h("admin1"),
    )
    assert r.status_code == 201, r.text
