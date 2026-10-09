"""Production configuration: validated at startup, safe defaults, healthz, redacted logs."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import bootstrap, demo_data, logging_setup, settings
from tests.auth_support import PASSWORD, login, make_user

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
def prod_env(monkeypatch, tmp_path):
    for k, v in {
        "NIRIKSHAN_PRODUCTION": "1",
        "DATABASE_URL": "sqlite:///x.db",
        "NIRIKSHAN_DATA_DIR": str(tmp_path / "data"),
        "NIRIKSHAN_KEY_DIR": str(tmp_path / "keys"),
        "NIRIKSHAN_EVIDENCE_ROOTS": str(tmp_path / "ev"),
        "CORS_ORIGINS": "https://app.example.org",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("NIRIKSHAN_DEV_HEADER_AUTH", raising=False)
    monkeypatch.delenv("NIRIKSHAN_COOKIE_SECURE", raising=False)


def test_a_complete_production_configuration_is_valid(prod_env):
    assert settings.validate() == []
    assert settings.cookie_secure() is True  # secure by default in production


def test_production_requires_explicit_settings(prod_env, monkeypatch):
    for k in ("DATABASE_URL", "NIRIKSHAN_KEY_DIR", "NIRIKSHAN_EVIDENCE_ROOTS", "CORS_ORIGINS"):
        monkeypatch.delenv(k)
    text = " ".join(settings.validate())
    for k in ("DATABASE_URL", "NIRIKSHAN_KEY_DIR", "NIRIKSHAN_EVIDENCE_ROOTS", "CORS_ORIGINS"):
        assert k in text


@pytest.mark.parametrize("origin", ["*", "http://localhost:5173", "http://127.0.0.1:3000"])
def test_production_rejects_wildcard_and_localhost_cors(prod_env, monkeypatch, origin):
    monkeypatch.setenv("CORS_ORIGINS", origin)
    assert any("CORS_ORIGINS" in p for p in settings.validate())


def test_key_dir_inside_data_dir_is_refused(prod_env, monkeypatch, tmp_path):
    monkeypatch.setenv("NIRIKSHAN_KEY_DIR", str(tmp_path / "data" / "keys"))
    assert any("outside NIRIKSHAN_DATA_DIR" in p for p in settings.validate())


def test_dev_header_with_production_flag_is_refused_at_startup(tmp_path):
    env = {
        **os.environ,
        "NIRIKSHAN_PRODUCTION": "1",
        "NIRIKSHAN_DEV_HEADER_AUTH": "1",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'p.db'}",
        "NIRIKSHAN_DATA_DIR": str(tmp_path / "d"),
        "NIRIKSHAN_KEY_DIR": str(tmp_path / "k"),
        "NIRIKSHAN_EVIDENCE_ROOTS": str(tmp_path),
        "CORS_ORIGINS": "https://app.example.org",
    }
    code = "from fastapi.testclient import TestClient as T\nfrom app.main import app\nwith T(app): pass"
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True
    )
    assert r.returncode != 0
    assert "NIRIKSHAN_DEV_HEADER_AUTH" in r.stderr and "refuses to start" in r.stderr


def test_bad_numbers_are_reported_together(monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_DB_POOL_SIZE", "many")
    monkeypatch.setenv("NIRIKSHAN_MAX_UPLOAD_BYTES", "0")
    monkeypatch.setenv("NIRIKSHAN_COOKIE_SAMESITE", "sideways")
    p = " ".join(settings.validate())
    assert "POOL_SIZE" in p and "MAX_UPLOAD" in p and "SAMESITE" in p


def test_samesite_none_needs_secure_cookie(monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_COOKIE_SAMESITE", "none")
    monkeypatch.delenv("NIRIKSHAN_COOKIE_SECURE", raising=False)
    assert any("secure cookie" in p for p in settings.validate())


def test_login_cookie_follows_env(client, no_dev_auth, session, monkeypatch):
    client.headers.pop("X-Examiner", None)
    make_user(session, "cookie-user", "examiner")
    monkeypatch.setenv("NIRIKSHAN_COOKIE_SECURE", "1")
    monkeypatch.setenv("NIRIKSHAN_COOKIE_SAMESITE", "lax")
    r = client.post("/api/auth/login", json={"username": "cookie-user", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie and "samesite=lax" in cookie and "httponly" in cookie


def test_demo_accounts_cannot_be_created_in_production(prod_env):
    with pytest.raises(SystemExit):
        demo_data.ensure_demo_users()


def test_healthz_is_public_and_reports_the_database(client, no_dev_auth):
    client.headers.pop("X-Examiner", None)
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["database"] == "ok"
    assert set(r.json()) == {"status", "database", "version"}  # no configuration leaks


def test_logs_are_json_and_redact_secrets(capsys, monkeypatch):
    logger = logging.getLogger("nirikshan")
    for h in list(logger.handlers):
        logger.removeHandler(h)
    monkeypatch.setenv("NIRIKSHAN_LOG_FORMAT", "json")
    logging_setup.setup()
    logging_setup.access.info(
        "request nrk_abcdefghijklmnop password=hunter2",
        extra={"fields": {"method": "GET", "path": "/api/cases", "status": 200}},
    )
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["status"] == 200 and line["path"] == "/api/cases"
    assert "hunter2" not in line["msg"] and "abcdefghijklmnop" not in line["msg"]
    for h in list(logger.handlers):
        logger.removeHandler(h)


def test_request_log_has_no_query_string_or_body(client, no_dev_auth, capsys):
    client.headers.pop("X-Examiner", None)
    logger = logging.getLogger("nirikshan")
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logging_setup.setup()
    client.post(
        "/api/auth/login?trace=1", json={"username": "nobody", "password": "very-secret-password"}
    )
    out = capsys.readouterr().out
    assert "very-secret-password" not in out and "trace=1" not in out
    assert '"path": "/api/auth/login"' in out
    for h in list(logger.handlers):
        logger.removeHandler(h)


def test_first_admin_from_env_file_only_while_no_admin_exists(session, monkeypatch, tmp_path):
    pwfile = tmp_path / "pw"
    pwfile.write_text("a-long-first-admin-password\n")
    monkeypatch.setenv("NIRIKSHAN_FIRST_ADMIN_USERNAME", "boss")
    monkeypatch.setenv("NIRIKSHAN_FIRST_ADMIN_PASSWORD_FILE", str(pwfile))
    assert bootstrap.first_admin_from_env(session) == "boss"
    assert bootstrap.first_admin_from_env(session) is None  # an admin exists now: ignored
    monkeypatch.setenv("NIRIKSHAN_FIRST_ADMIN_USERNAME", "other")
    assert bootstrap.first_admin_from_env(session) is None


def test_first_admin_errors_never_contain_the_password(session, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_FIRST_ADMIN_USERNAME", "boss2")
    monkeypatch.setenv("NIRIKSHAN_FIRST_ADMIN_PASSWORD", "short")
    with pytest.raises(ValueError) as e:
        bootstrap.first_admin_from_env(session)
    assert "short" not in str(e.value).replace("too short", "")


def test_demo_viewer_sees_only_the_demo_case(client, no_dev_auth, session, monkeypatch):
    from app.models import Case

    client.headers.pop("X-Examiner", None)
    session.add_all(
        [
            Case(case_number="DEMO-REFERENCE-001", title="d", description="", examiner="x"),
            Case(case_number="REAL-1", title="secret", description="", examiner="x"),
        ]
    )
    session.commit()
    name, added = bootstrap.create_demo_viewer(session, "demo-viewer-password-1")
    assert name == "demo-viewer" and added == ["DEMO-REFERENCE-001"]
    h = {"Authorization": "Bearer " + login(client, "demo-viewer", "demo-viewer-password-1")}
    cases = client.get("/api/cases", headers=h).json()
    assert [c["case_number"] for c in cases] == ["DEMO-REFERENCE-001"]
    real = session.query(Case).filter_by(case_number="REAL-1").one()
    assert client.get(f"/api/cases/{real.id}", headers=h).status_code == 404
    body = {"case_number": "N", "title": "t", "description": ""}
    assert client.post("/api/cases", json=body, headers=h).status_code == 403
