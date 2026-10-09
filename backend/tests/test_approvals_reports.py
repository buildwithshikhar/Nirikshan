"""Two-person report approval and evidence transfer records (dev header mode OFF)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.approvals.models import ReportReview
from app.models import CustodyEntry
from tests.auth_support import add_member, world  # noqa: F401  (fixture)


@pytest.fixture
def rep(client, world):  # noqa: F811
    """A real generated report in case A, authored by exam1; rev1 and exam2 join case A."""
    add_member(client, world, "A", "rev1")
    add_member(client, world, "A", "ro1")
    cid = world.cases["A"]["case_id"]
    r = client.post(f"/api/cases/{cid}/report", headers=world.h("exam1"))
    assert r.status_code == 201, r.text
    assert r.json()["review_status"] == "draft"
    return r.json()


def _post(client, world, who, rid, step, **body):  # noqa: F811
    return client.post(f"/api/reports/{rid}/{step}", json=body or None, headers=world.h(who))


def test_full_two_person_flow_with_custody_entries(client, world, rep, session):  # noqa: F811
    rid, cid = rep["id"], rep["case_id"]
    assert _post(client, world, "exam1", rid, "approve").status_code == 403  # examiner role
    assert _post(client, world, "rev1", rid, "approve").status_code == 409  # not requested yet
    r = _post(client, world, "exam1", rid, "request-approval", note="please review")
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    assert _post(client, world, "exam1", rid, "finalize").status_code == 409  # not approved
    r = _post(client, world, "rev1", rid, "approve", note="checked hashes")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["approved_by"] == "Rev1 (rev1)"
    r = _post(client, world, "exam1", rid, "finalize")
    assert r.status_code == 200 and r.json()["final"] is True
    acts = [
        e.action
        for e in session.scalars(
            select(CustodyEntry).where(CustodyEntry.case_id == cid).order_by(CustodyEntry.seq)
        )
    ]
    assert acts[-3:] == ["report_approval_requested", "report_approved", "report_finalized"]
    assert client.get(f"/api/cases/{cid}/custody/verify", headers=world.h("rev1")).json()["ok"]
    review = client.get(f"/api/reports/{rid}/review", headers=world.h("ro1")).json()
    assert [e["action"] for e in review["events"]] == ["requested", "approved", "finalized"]
    assert all(e["custody_seq"] for e in review["events"])
    # final is immutable: every further step is refused
    for who, step in (("exam1", "request-approval"), ("rev1", "approve"), ("rev1", "finalize")):
        r = _post(client, world, who, rid, step)
        assert r.status_code == 409 and "final" in r.json()["detail"]
    r = client.post(
        f"/api/reports/{rid}/reject", json={"reason": "too late"}, headers=world.h("rev1")
    )
    assert r.status_code == 409
    # ... and the database refuses a direct change too
    with pytest.raises(DatabaseError):
        session.execute(text(f"UPDATE report_reviews SET status='draft' WHERE report_id={rid}"))
        session.commit()
    session.rollback()
    # download carries the status (PDF bytes unchanged)
    d = client.get(f"/api/reports/{rid}/download", headers=world.h("ro1"))
    assert d.status_code == 200 and d.headers["x-nirikshan-report-status"] == "final"
    assert "_FINAL.pdf" in d.headers["content-disposition"]
    import hashlib

    assert hashlib.sha256(d.content).hexdigest() == rep["sha256"]
    listed = client.get(f"/api/cases/{cid}/reports", headers=world.h("ro1")).json()
    assert listed[0]["review_status"] == "final"


def test_author_cannot_approve_own_report_even_as_admin(client, world):  # noqa: F811
    add_member(client, world, "A", "admin1")
    cid = world.cases["A"]["case_id"]
    rep = client.post(f"/api/cases/{cid}/report", headers=world.h("admin1")).json()
    assert _post(client, world, "exam1", rep["id"], "request-approval").status_code == 200
    r = _post(client, world, "admin1", rep["id"], "approve")
    assert r.status_code == 403 and "author" in r.json()["detail"]


def test_requester_cannot_approve(client, world, rep):  # noqa: F811
    add_member(client, world, "A", "admin1")
    rid = rep["id"]
    assert _post(client, world, "admin1", rid, "request-approval").status_code == 200
    r = _post(client, world, "admin1", rid, "approve")
    assert r.status_code == 403 and "requester" in r.json()["detail"]
    assert _post(client, world, "rev1", rid, "approve").status_code == 200


def test_readonly_and_non_member_reviewer(client, world, rep):  # noqa: F811
    rid = rep["id"]
    _post(client, world, "exam1", rid, "request-approval")
    assert _post(client, world, "ro1", rid, "approve").status_code == 403
    assert _post(client, world, "ro1", rid, "finalize").status_code == 403
    r = client.post(  # rev1 is not a member of case B: B's reports do not exist for them
        f"/api/reports/{world.cases['B']['report_id']}/approve", headers=world.h("rev1")
    )
    assert r.status_code == 404


def test_reject_is_terminal(client, world, rep):  # noqa: F811
    rid = rep["id"]
    _post(client, world, "exam1", rid, "request-approval")
    r = client.post(f"/api/reports/{rid}/reject", json={"reason": "x"}, headers=world.h("rev1"))
    assert r.status_code == 422  # a reason is required
    r = client.post(
        f"/api/reports/{rid}/reject", json={"reason": "timeline gap unexplained"},
        headers=world.h("rev1"),
    )  # fmt: skip
    assert r.json()["status"] == "rejected"
    assert _post(client, world, "exam1", rid, "request-approval").status_code == 409


def test_finalize_refuses_modified_pdf(client, world, rep, session):  # noqa: F811
    from app.report.models import Report

    rid = rep["id"]
    _post(client, world, "exam1", rid, "request-approval")
    _post(client, world, "rev1", rid, "approve")
    path = session.get(Report, rid).file_path
    import os

    os.chmod(path, 0o644)
    with open(path, "ab") as f:
        f.write(b"tamper")
    r = _post(client, world, "exam1", rid, "finalize")
    assert r.status_code == 409 and "SHA-256" in r.json()["detail"]
    assert (
        session.scalars(select(ReportReview).where(ReportReview.report_id == rid)).one().status
        == "approved"
    )


def test_dev_header_cannot_approve(client, session, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_DEV_HEADER_AUTH", "1")
    c = client.post("/api/cases", json={"case_number": "DEV-A", "title": "t"}).json()
    rep = client.post(f"/api/cases/{c['id']}/report").json()
    assert client.post(f"/api/reports/{rep['id']}/request-approval").status_code == 200
    r = client.post(f"/api/reports/{rep['id']}/approve", headers={"X-Examiner": "Someone Else"})
    assert r.status_code == 403 and "X-Examiner" in r.json()["detail"]


# ---- transfers ----
def test_transfer_recorded_in_custody_and_queryable(client, world, session):  # noqa: F811
    a = world.cases["A"]
    body = {
        "from_party": "Insp. One, Cyber Cell",
        "to_party": "Evidence store, Room 4",
        "reason": "end of examination session",
        "transferred_at": "2026-10-09T18:30:00+05:30",
        "seal": "SEAL-0042",
    }
    r = client.post(
        f"/api/evidence/{a['evidence_id']}/transfers", json=body, headers=world.h("exam1")
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["transferred_at"] == "2026-10-09T13:00:00+00:00"  # normalised to UTC
    assert t["recorded_by"] == "Exam1 (exam1)" and t["custody_seq"]
    entry = session.scalars(
        select(CustodyEntry).where(
            CustodyEntry.case_id == a["case_id"], CustodyEntry.seq == t["custody_seq"]
        )
    ).one()
    assert entry.action == "evidence_transferred" and entry.evidence_id == a["evidence_id"]
    assert '"to":"Evidence store, Room 4"' in entry.details_json
    assert (
        client.get(f"/api/evidence/{a['evidence_id']}/transfers", headers=world.h("exam1")).json()[
            0
        ]["id"]
        == t["id"]
    )
    rows = client.get(
        f"/api/cases/{a['case_id']}/transfers?evidence_id={a['evidence_id']}",
        headers=world.h("exam1"),
    ).json()
    assert [x["seal"] for x in rows] == ["SEAL-0042"]
    # append-only
    with pytest.raises(DatabaseError):
        session.execute(text("UPDATE evidence_transfers SET to_party='x'"))
        session.commit()
    session.rollback()


def test_transfer_validation_and_access(client, world):  # noqa: F811
    a, b = world.cases["A"], world.cases["B"]
    base = {"from_party": "a", "to_party": "b", "reason": "handover"}
    url = f"/api/evidence/{a['evidence_id']}/transfers"
    assert (
        client.post(
            url, json={**base, "transferred_at": "2026-10-09T10:00:00"}, headers=world.h("exam1")
        ).status_code
        == 422
    )
    assert (
        client.post(
            url, json={**base, "transferred_at": "yesterday"}, headers=world.h("exam1")
        ).status_code
        == 422
    )
    r = client.post(url, json=base, headers=world.h("exam1"))
    assert r.status_code == 201
    assert (
        client.post(
            f"/api/evidence/{b['evidence_id']}/transfers", json=base, headers=world.h("exam1")
        ).status_code
        == 404
    )
    add_member(client, world, "A", "ro1")
    assert client.post(url, json=base, headers=world.h("ro1")).status_code == 403
    assert client.get(url, headers=world.h("ro1")).status_code == 200
