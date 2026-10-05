import os

from sqlalchemy import select

from app.models import AuditEntry, CustodyEntry, Evidence
from app.triggers import drop_triggers


def _case(client, number="N-1"):
    r = client.post("/api/cases", json={"case_number": number, "title": "Shop DVR"})
    assert r.status_code == 201, r.text
    return r.json()


def test_mutations_require_examiner_header(client):
    r = client.post(
        "/api/cases", json={"case_number": "x", "title": "t"}, headers={"X-Examiner": " "}
    )
    assert r.status_code == 400


def test_case_lifecycle_and_duplicate_number(client):
    c = _case(client)
    assert c["examiner"] == "Insp. Test"
    assert client.get(f"/api/cases/{c['id']}").json()["case_number"] == "N-1"
    assert [x["id"] for x in client.get("/api/cases").json()] == [c["id"]]
    assert client.post("/api/cases", json={"case_number": "N-1", "title": "t"}).status_code == 409
    assert client.get("/api/cases/999").status_code == 404
    log = client.get(f"/api/cases/{c['id']}/custody").json()
    assert [e["action"] for e in log] == ["case_created"]


def test_acquire_verify_and_custody_over_api(client, image):
    c = _case(client)
    body = {"source_path": str(image), "label": "HDD 1", "write_blocker": "no"}
    r = client.post(f"/api/cases/{c['id']}/evidence", json=body)
    assert r.status_code == 201, r.text
    ev = r.json()
    assert len(ev["sha256"]) == 64 and len(ev["md5"]) == 32 and ev["status"] == "acquired"
    assert client.post(f"/api/evidence/{ev['id']}/verify").json()["ok"] is True
    assert len(client.get(f"/api/cases/{c['id']}/evidence").json()) == 1
    chain = client.get(f"/api/cases/{c['id']}/custody/verify").json()
    assert chain["ok"] and chain["entries"] == 3


def test_acquire_rejects_bad_source_and_bad_attestation(client, tmp_path):
    c = _case(client)
    url = f"/api/cases/{c['id']}/evidence"
    r = client.post(
        url, json={"source_path": str(tmp_path / "x"), "label": "l", "write_blocker": "no"}
    )
    assert r.status_code == 400
    r = client.post(url, json={"source_path": "/etc/hosts", "label": "l", "write_blocker": "maybe"})
    assert r.status_code == 422
    assert (
        client.post(
            "/api/cases/999/evidence",
            json={"source_path": "/", "label": "l", "write_blocker": "no"},
        ).status_code
        == 404
    )


def test_tampered_image_reported_over_api(client, image):
    c = _case(client)
    ev = client.post(
        f"/api/cases/{c['id']}/evidence",
        json={"source_path": str(image), "label": "l", "write_blocker": "yes"},
    ).json()
    from app import db

    with db.SessionLocal() as s:
        path = s.get(Evidence, ev["id"]).image_path
    os.chmod(path, 0o644)
    with open(path, "ab") as f:
        f.write(b"x")
    assert client.post(f"/api/evidence/{ev['id']}/verify").json()["ok"] is False


def test_api_tamper_detected_by_chain_endpoint(client, session):
    c = _case(client)
    drop_triggers(session)  # simulate a DB owner
    row = session.scalars(select(CustodyEntry)).first()
    row.examiner = "someone else"
    session.commit()
    chain = client.get(f"/api/cases/{c['id']}/custody/verify").json()
    assert chain["ok"] is False and chain["failures"]


def test_audit_trail_records_requests(client, session):
    c = _case(client)
    client.get(f"/api/cases/{c['id']}")
    client.get("/api/cases/404")
    rows = session.scalars(select(AuditEntry).order_by(AuditEntry.id)).all()
    assert [(r.method, r.status_code, r.case_id) for r in rows] == [
        ("POST", 201, None),
        ("GET", 200, c["id"]),
        ("GET", 404, 404),
    ]
    assert rows[0].examiner == "Insp. Test"
    api_rows = client.get("/api/audit").json()
    assert len(api_rows) == 3


def test_system_reports_ffmpeg_state_and_key(client, monkeypatch):
    from app import routes

    monkeypatch.setattr(routes, "find_tool", lambda _: None)
    s = client.get("/api/system").json()
    assert s["ffmpeg"] == {"available": False, "version": None} and "degraded" in s["mode"]
    k = client.get("/api/signing-key").json()
    assert k["algorithm"] == "Ed25519" and len(k["public_key_hex"]) == 64
    assert k["key_id"] == s["signing_key_id"]


def test_system_with_ffmpeg_present(client, monkeypatch):
    import subprocess

    from app import routes

    monkeypatch.setattr(routes, "find_tool", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        routes.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="ffmpeg version 7.0\nmore"),
    )
    s = client.get("/api/system").json()
    assert (
        s["ffmpeg"] == {"available": True, "version": "ffmpeg version 7.0"} and s["mode"] == "full"
    )
