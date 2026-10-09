"""Demo accounts (`make demo` / e2e only): created idempotently, usable through the real login."""

from app import demo_data
from app.auth.models import User


def test_demo_users_are_created_once_and_can_log_in(client, session, no_dev_auth):
    created = demo_data.ensure_demo_users()
    assert set(created) == {u for u, _d, _r in demo_data.DEMO_USERS}
    assert demo_data.ensure_demo_users() == []  # idempotent
    roles = {u.username: u.role for u in session.query(User).all()}
    assert {roles[u] for u in roles} >= {"admin", "examiner", "reviewer", "readonly"}
    for username, _display, role in demo_data.DEMO_USERS:
        r = client.post(
            "/api/auth/login", json={"username": username, "password": demo_data.DEMO_PASSWORD}
        )
        assert r.status_code == 200 and r.json()["user"]["role"] == role
    bad = client.post(
        "/api/auth/login", json={"username": "demo-admin", "password": "wrong-password-xx"}
    )
    assert bad.status_code == 401
