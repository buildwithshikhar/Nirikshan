"""RBAC and case-level access control with real authentication (dev header mode OFF).

The cross-case tests enumerate EVERY registered route, so a route added later is covered (and a
route without an access rule fails test_every_route_has_an_access_rule)."""

import re

import pytest

from app.auth.policy import POLICY, iter_routes, resolver_key, rule_for
from app.main import app
from tests.auth_support import add_member, world  # noqa: F401  (fixture)

PARAM = re.compile(r"{([a-z_]+)}")


def api_routes():
    return iter_routes(app)


def test_every_route_has_an_access_rule():
    missing = [(m, p) for m, p in api_routes() if rule_for(m, p, PARAM.findall(p)) is None]
    assert missing == []


def test_policy_table_has_no_stale_entries():
    live = set(api_routes())
    assert [k for k in POLICY if k not in live] == []


def _url(path: str, ids: dict) -> str | None:
    out = path
    for param in PARAM.findall(path):
        key = resolver_key(path, param)
        if key not in ids:
            return None
        out = out.replace("{" + param + "}", str(ids[key]))
    return out


def _case_scoped_routes():
    for m, p in api_routes():
        rule = rule_for(m, p, PARAM.findall(p))
        if rule.scope in ("case", "case_meta"):
            yield m, p


def test_non_member_gets_404_identical_to_nonexistent_on_every_case_route(client, world):  # noqa: F811
    """exam1 is a member of case A only. Every case-scoped route, addressed with case B's object
    ids, answers exactly as if the object did not exist."""
    b = world.cases["B"]
    missing = {k: 987654 for k in b}
    checked = 0
    for method, path in _case_scoped_routes():
        url_b, url_missing = _url(path, b), _url(path, missing)
        if url_b is None:
            continue
        rb = client.request(method, url_b, headers=world.h("exam1"))
        rm = client.request(method, url_missing, headers=world.h("exam1"))
        assert rb.status_code == 404, (method, path, rb.status_code, rb.text)
        assert rb.json() == rm.json(), (method, path)
        checked += 1
    assert checked >= 40  # sanity: the enumeration really covered the API


def test_member_can_read_every_get_route_of_own_case(client, world):  # noqa: F811
    a = world.cases["A"]
    for method, path in _case_scoped_routes():
        if method != "GET":
            continue
        url = _url(path, a)
        if url is None:
            continue
        r = client.get(url, headers=world.h("exam1"))
        assert r.status_code not in (401, 403), (path, r.status_code, r.text)
        if r.status_code == 404:  # allowed only for "no such sub-resource", never "case"
            assert r.json()["detail"] not in ("Case not found", "Evidence not found"), path


@pytest.mark.parametrize("who", ["rev1", "ro1"])
def test_non_writer_members_cannot_mutate(client, world, who):  # noqa: F811
    add_member(client, world, "A", who)
    a = world.cases["A"]
    for method, path in _case_scoped_routes():
        rule = rule_for(method, path, PARAM.findall(path))
        if method == "GET" or rule.name.startswith("case member with role admin or reviewer"):
            continue
        if who == "rev1" and "finalize" in path:
            continue  # reviewers may finalize (checked in the approvals tests)
        url = _url(path, a)
        if url is None or rule.scope == "case_meta" and "members" not in path:
            continue
        r = client.request(method, url, headers=world.h(who))
        assert r.status_code == 403, (who, method, path, r.status_code, r.text)
    # but they can read
    assert (
        client.get(f"/api/cases/{a['case_id']}/evidence", headers=world.h(who)).status_code == 200
    )


def test_list_cases_is_filtered_and_admin_sees_all(client, world):  # noqa: F811
    ids = lambda who: {c["id"] for c in client.get("/api/cases", headers=world.h(who)).json()}  # noqa: E731
    a, b = world.cases["A"]["case_id"], world.cases["B"]["case_id"]
    assert ids("exam1") == {a} and ids("exam2") == {b}
    assert ids("rev1") == set() and ids("ro1") == set()
    assert ids("admin1") == {a, b}


def test_admin_needs_membership_for_case_contents(client, world):  # noqa: F811
    a = world.cases["A"]
    h = world.h("admin1")
    assert client.get(f"/api/cases/{a['case_id']}", headers=h).status_code == 200  # metadata
    assert client.get(f"/api/cases/{a['case_id']}/members", headers=h).status_code == 200
    r = client.get(f"/api/cases/{a['case_id']}/evidence", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "Case not found"
    add_member(client, world, "A", "admin1")
    assert client.get(f"/api/cases/{a['case_id']}/evidence", headers=h).status_code == 200
    # the grant is in the case's custody log
    log = client.get(f"/api/cases/{a['case_id']}/custody", headers=h).json()
    assert log[-1]["action"] == "member_added" and log[-1]["examiner"] == "Admin1 (admin1)"


def test_membership_removal_takes_effect_immediately(client, world):  # noqa: F811
    a = world.cases["A"]
    add_member(client, world, "A", "ro1")
    assert (
        client.get(f"/api/cases/{a['case_id']}/evidence", headers=world.h("ro1")).status_code == 200
    )
    r = client.delete(
        f"/api/cases/{a['case_id']}/members/{world.users['ro1'].id}", headers=world.h("admin1")
    )
    assert r.status_code == 200
    assert (
        client.get(f"/api/cases/{a['case_id']}/evidence", headers=world.h("ro1")).status_code == 404
    )


@pytest.mark.parametrize("who", ["exam1", "rev1", "ro1"])
def test_role_escalation_attempts(client, world, who):  # noqa: F811
    me = world.users[who]
    h = world.h(who)
    a = world.cases["A"]["case_id"]
    assert client.patch(f"/api/users/{me.id}", json={"role": "admin"}, headers=h).status_code == 403
    body = {"username": "evil", "display_name": "E", "role": "admin", "password": "x" * 20}
    assert client.post("/api/users", json=body, headers=h).status_code == 403
    assert client.get("/api/users", headers=h).status_code == 403
    assert (
        client.post(
            f"/api/users/{me.id}/password", json={"new_password": "y" * 20}, headers=h
        ).status_code
        == 403
    )
    assert client.post(f"/api/users/{me.id}/unlock", headers=h).status_code == 403
    r = client.post(f"/api/cases/{a}/members", json={"user_id": me.id}, headers=h)
    assert r.status_code in (403, 404)  # 403 for a member (exam1), 404 for a non-member
    me_after = client.get("/api/auth/me", headers=h).json()
    assert me_after["role"] == me.role


def test_reviewer_and_readonly_cannot_create_cases(client, world):  # noqa: F811
    for who in ("rev1", "ro1"):
        r = client.post(
            "/api/cases", json={"case_number": f"N-{who}", "title": "t"}, headers=world.h(who)
        )
        assert r.status_code == 403


def test_audit_scoping(client, world):  # noqa: F811
    a, b = world.cases["A"]["case_id"], world.cases["B"]["case_id"]
    assert client.get("/api/audit", headers=world.h("exam1")).status_code == 403
    rows = client.get(f"/api/audit?case_id={a}", headers=world.h("exam1")).json()
    assert rows and {r["case_id"] for r in rows} == {a}
    r = client.get(f"/api/audit?case_id={b}", headers=world.h("exam1"))
    assert r.status_code == 404
    assert client.get("/api/audit", headers=world.h("admin1")).status_code == 200


def test_mismatched_ids_in_one_path_are_refused(client, world):  # noqa: F811
    """/cases/{A}/certificate-draft?evidence_id is query-scoped; the route checks it. A path that
    names objects from two cases is refused outright."""
    from fastapi import HTTPException

    from app.auth.policy import _case_ids_from_path
    from app.db import SessionLocal

    with SessionLocal() as db, pytest.raises(HTTPException) as e:
        _case_ids_from_path(
            db,
            "/api/cases/{case_id}/x/{evidence_id}",
            {
                "case_id": world.cases["A"]["case_id"],
                "evidence_id": world.cases["B"]["evidence_id"],
            },
        )
    assert e.value.status_code == 404
    r = client.get(
        f"/api/cases/{world.cases['A']['case_id']}/certificate-draft?evidence_id="
        f"{world.cases['B']['evidence_id']}",
        headers=world.h("exam1"),
    )
    assert r.status_code == 404


def test_body_references_to_other_cases_are_refused(client, world):  # noqa: F811
    """Batch job bodies name evidence ids; ids from another case are treated as not found."""
    a = world.cases["A"]["case_id"]
    r = client.post(
        f"/api/cases/{a}/jobs/batch",
        json={"evidence_ids": [world.cases["B"]["evidence_id"]]},
        headers=world.h("exam1"),
    )
    assert r.status_code == 404
