"""Authentication with the dev header mode OFF: login, tokens, expiry, lockout, rate limit, CLI."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import cli
from app.auth import passwords, service
from app.auth.models import AuthSession, User
from app.models import AuditEntry, CustodyEntry
from tests.auth_support import PASSWORD, bearer, login, make_user


@pytest.fixture
def api(client, no_dev_auth):
    client.headers.pop("X-Examiner", None)
    return client


def test_password_hash_format_salt_and_verify():
    a, b = passwords.hash_password(PASSWORD), passwords.hash_password(PASSWORD)
    assert a != b  # per-hash salt
    algo, log2n, r, p, salt, key = a.split("$")
    assert (algo, r, p) == ("scrypt", "8", "1") and int(log2n) >= passwords.MIN_LOG2N
    assert passwords.verify_password(PASSWORD, a)
    assert not passwords.verify_password(PASSWORD + "x", a)
    assert not passwords.verify_password(PASSWORD, "garbage")
    assert not passwords.verify_password(PASSWORD, "scrypt$99$8$1$AA==$AA==")  # cost out of range


def test_default_cost_is_documented_value(monkeypatch):
    monkeypatch.delenv("NIRIKSHAN_PASSWORD_SCRYPT_LOG2N", raising=False)
    assert passwords.current_log2n() == 15


def test_password_policy():
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.check_policy("short")
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.check_policy("examiner-one", "examiner-one")
    passwords.check_policy(PASSWORD, "someone")


def test_no_credentials_and_dev_header_are_refused(api, session):
    assert api.get("/api/cases").status_code == 401
    r = api.get("/api/cases", headers={"X-Examiner": "Insp. Test"})
    assert r.status_code == 401 and "NIRIKSHAN_DEV_HEADER_AUTH" in r.json()["detail"]
    r = api.post("/api/cases", json={"case_number": "X", "title": "t"}, headers={"X-Examiner": "a"})
    assert r.status_code == 401
    assert api.get("/health").status_code == 200  # public
    assert api.get("/api/signing-key").status_code == 200  # public half only


def test_login_me_logout(api, session):
    make_user(session, "exam1", "examiner", "Insp. One")
    token = login(api, "exam1")
    assert token.startswith("nrk_")
    me = api.get("/api/auth/me", headers=bearer(token)).json()
    assert (
        me["username"] == "exam1"
        and me["role"] == "examiner"
        and "case.write (member)" in me["permissions"]
    )
    # only the hash is stored
    rows = session.scalars(select(AuthSession)).all()
    assert len(rows) == 1 and rows[0].token_hash == service.token_hash(token)
    assert token not in rows[0].token_hash
    assert api.post("/api/auth/logout", headers=bearer(token)).status_code == 200
    r = api.get("/api/auth/me", headers=bearer(token))
    assert r.status_code == 401 and "revoked" in r.json()["detail"]


def test_invalid_and_malformed_tokens(api, session):
    assert api.get("/api/cases", headers=bearer("nrk_not-a-token")).status_code == 401
    assert api.get("/api/cases", headers={"Authorization": "Basic abc"}).status_code == 401
    assert api.get("/api/cases", headers={"Authorization": "Bearer "}).status_code == 401


def test_invalid_token_never_falls_back_to_dev_header(api, session, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_DEV_HEADER_AUTH", "1")
    r = api.get("/api/cases", headers={**bearer("nrk_bad"), "X-Examiner": "Insp. Test"})
    assert r.status_code == 401


def test_absolute_expiry_and_idle_timeout(api, session, monkeypatch):
    make_user(session, "exam1", "examiner")
    token = login(api, "exam1")
    real = service.now
    monkeypatch.setattr(service, "now", lambda: real() + timedelta(minutes=29))
    assert api.get("/api/auth/me", headers=bearer(token)).status_code == 200  # refreshes last_seen
    monkeypatch.setattr(service, "now", lambda: real() + timedelta(minutes=29 + 31))
    r = api.get("/api/auth/me", headers=bearer(token))
    assert r.status_code == 401 and "inactivity" in r.json()["detail"]
    token2 = login(api, "exam1")
    monkeypatch.setattr(service, "now", lambda: real() + timedelta(hours=8, minutes=1))
    r = api.get("/api/auth/me", headers=bearer(token2))
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_cookie_accepted_for_get_only(api, session):
    make_user(session, "exam1", "examiner")
    r = api.post("/api/auth/login", json={"username": "exam1", "password": PASSWORD})
    cookie = r.cookies.get(service.COOKIE)
    assert cookie and cookie == r.json()["token"]
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie
    api.cookies.clear()
    api.cookies.set(service.COOKIE, cookie)
    assert api.get("/api/cases").status_code == 200
    r = api.post("/api/cases", json={"case_number": "C1", "title": "t"})
    assert r.status_code == 401 and "GET requests only" in r.json()["detail"]
    assert api.post("/api/auth/logout").status_code == 200  # logout accepts the cookie
    api.cookies.set(service.COOKIE, cookie)
    assert api.get("/api/cases").status_code == 401
    api.cookies.clear()


def test_wrong_password_and_unknown_user_are_indistinguishable(api, session):
    make_user(session, "exam1", "examiner")
    a = api.post("/api/auth/login", json={"username": "exam1", "password": "wrong password!!"})
    b = api.post("/api/auth/login", json={"username": "nobody", "password": "wrong password!!"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_lockout_after_consecutive_failures_and_unlock(api, session, monkeypatch):
    make_user(session, "admin1", "admin")
    u = make_user(session, "exam1", "examiner")
    admin = login(api, "admin1")
    for _ in range(5):
        assert (
            api.post("/api/auth/login", json={"username": "exam1", "password": "nope nope nope"})
        ).status_code == 401
    session.expire_all()
    assert session.get(User, u.id).locked_until
    # the correct password is refused while locked, with the same generic message
    r = api.post("/api/auth/login", json={"username": "exam1", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == service.GENERIC_FAILURE
    assert api.get(f"/api/users/{u.id}", headers=bearer(admin)).json()["locked"] is True
    # lock expires by itself ...
    real = service.now
    monkeypatch.setattr(service, "now", lambda: real() + timedelta(minutes=16))
    assert login(api, "exam1")
    monkeypatch.setattr(service, "now", real)
    # ... or an admin unlocks early
    for _ in range(5):
        api.post("/api/auth/login", json={"username": "exam1", "password": "nope nope nope"})
    assert api.post(f"/api/users/{u.id}/unlock", headers=bearer(admin)).json()["locked"] is False
    assert login(api, "exam1")


def test_success_resets_failure_counter(api, session):
    u = make_user(session, "exam1", "examiner")
    for _ in range(4):
        api.post("/api/auth/login", json={"username": "exam1", "password": "nope nope nope"})
    login(api, "exam1")
    session.expire_all()
    assert session.get(User, u.id).failed_logins == 0


def test_per_address_rate_limit(api, session, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_LOGIN_ADDR_MAX_FAILURES", "3")
    make_user(session, "exam1", "examiner")
    for name in ("a1", "a2", "a3"):  # different (unknown) usernames: the address limit applies
        assert (
            api.post("/api/auth/login", json={"username": name, "password": "x"}).status_code == 401
        )
    r = api.post("/api/auth/login", json={"username": "exam1", "password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_address_limiter_is_bounded(monkeypatch):
    from app.auth import ratelimit

    monkeypatch.setattr(ratelimit, "ADDR_MAX_TRACKED", 50)
    lim = ratelimit.AddressLimiter()
    for i in range(500):
        lim.failure(f"10.0.0.{i}")
    assert lim.tracked() == 50


def test_deactivated_user_loses_sessions(api, session):
    make_user(session, "admin1", "admin")
    u = make_user(session, "exam1", "examiner")
    admin, tok = login(api, "admin1"), login(api, "exam1")
    assert (
        api.patch(f"/api/users/{u.id}", json={"active": False}, headers=bearer(admin)).status_code
        == 200
    )
    assert api.get("/api/cases", headers=bearer(tok)).status_code == 401
    r = api.post("/api/auth/login", json={"username": "exam1", "password": PASSWORD})
    assert r.status_code == 401


def test_password_change_revokes_other_sessions(api, session):
    make_user(session, "exam1", "examiner")
    t1, t2 = login(api, "exam1"), login(api, "exam1")
    new = "a different long passphrase"
    r = api.post(
        "/api/auth/password",
        json={"current_password": "wrong wrong wrong", "new_password": new},
        headers=bearer(t1),
    )
    assert r.status_code == 403
    r = api.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "short"},
        headers=bearer(t1),
    )  # fmt: skip
    assert r.status_code == 422
    r = api.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": new},
        headers=bearer(t1),
    )  # fmt: skip
    assert r.json() == {"ok": True, "other_sessions_revoked": 1}
    assert api.get("/api/auth/me", headers=bearer(t1)).status_code == 200
    assert api.get("/api/auth/me", headers=bearer(t2)).status_code == 401
    assert login(api, "exam1", new)


def test_admin_password_reset_revokes_sessions(api, session):
    make_user(session, "admin1", "admin")
    u = make_user(session, "exam1", "examiner")
    admin, tok = login(api, "admin1"), login(api, "exam1")
    r = api.post(
        f"/api/users/{u.id}/password", json={"new_password": "brand new passphrase"},
        headers=bearer(admin),
    )  # fmt: skip
    assert r.json()["sessions_revoked"] == 1
    assert api.get("/api/auth/me", headers=bearer(tok)).status_code == 401


def test_cannot_remove_last_admin(api, session):
    a = make_user(session, "admin1", "admin")
    tok = login(api, "admin1")
    r = api.patch(f"/api/users/{a.id}", json={"role": "examiner"}, headers=bearer(tok))
    assert r.status_code == 409
    r = api.patch(f"/api/users/{a.id}", json={"active": False}, headers=bearer(tok))
    assert r.status_code == 409


def test_user_validation(api, session):
    make_user(session, "admin1", "admin")
    tok = login(api, "admin1")
    base = {"display_name": "X", "role": "examiner", "password": PASSWORD}
    assert (
        api.post(
            "/api/users", json={**base, "username": "Bad Name"}, headers=bearer(tok)
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/users", json={**base, "username": "ok", "role": "root"}, headers=bearer(tok)
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/users",
            json={**base, "username": "okay1", "password": "short"},
            headers=bearer(tok),
        ).status_code
        == 422
    )
    assert (
        api.post("/api/users", json={**base, "username": "okay1"}, headers=bearer(tok)).status_code
        == 201
    )
    assert (
        api.post("/api/users", json={**base, "username": "okay1"}, headers=bearer(tok)).status_code
        == 409
    )


def test_identity_in_custody_audit_and_case(api, session):
    make_user(session, "exam1", "examiner", "Insp. One")
    tok = login(api, "exam1")
    r = api.post("/api/cases", json={"case_number": "ID-1", "title": "t"}, headers=bearer(tok))
    assert r.status_code == 201 and r.json()["examiner"] == "Insp. One (exam1)"
    entries = session.scalars(select(CustodyEntry).order_by(CustodyEntry.seq)).all()
    assert [e.action for e in entries] == ["case_created", "member_added"]
    assert {e.examiner for e in entries} == {"Insp. One (exam1)"}
    audit = session.scalars(select(AuditEntry).where(AuditEntry.method == "POST")).all()
    assert any(a.path == "/api/cases" and a.examiner == "Insp. One (exam1)" for a in audit)
    # a refused request is audited with no identity
    api.get("/api/cases", headers=bearer("nrk_bad"))
    last = session.scalars(select(AuditEntry).order_by(AuditEntry.id.desc())).first()
    assert last.status_code == 401 and last.examiner == ""


def test_dev_header_mode_still_works_when_enabled(client, session):
    """The conftest default (NIRIKSHAN_DEV_HEADER_AUTH=1): the old attestation behaviour."""
    r = client.post("/api/cases", json={"case_number": "DEV-1", "title": "t"})
    assert r.status_code == 201 and r.json()["examiner"] == "Insp. Test"
    # but user management never accepts the header
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/auth/me").status_code == 403


# ---- CLI bootstrap ----------------------------------------------------------------------
def _answers(monkeypatch, *values):
    it = iter(values)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(it))


def test_create_admin_cli(api, session, monkeypatch, capsys):
    _answers(monkeypatch, PASSWORD, "different passphrase")
    assert cli.main(["create-admin", "boss"]) == 2
    _answers(monkeypatch, "short", "short")
    assert cli.main(["create-admin", "boss"]) == 2
    _answers(monkeypatch, PASSWORD, PASSWORD)
    assert cli.main(["create-admin", "boss", "--display-name", "Lab Admin"]) == 0
    assert "created admin 'boss'" in capsys.readouterr().out
    tok = login(api, "boss")
    assert api.get("/api/users", headers=bearer(tok)).json()[0]["role"] == "admin"
    _answers(monkeypatch, PASSWORD, PASSWORD)
    assert cli.main(["create-admin", "boss2"]) == 2  # only the first admin
    assert "already exists" in capsys.readouterr().err
