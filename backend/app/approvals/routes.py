"""Two-person report approval and evidence transfer records (prefix /api).

Report lifecycle (docs/security/auth.md "Approvals"):
    draft --request-approval--> pending_approval --approve--> approved --finalize--> final
                                                 \\--reject--> rejected (terminal: generate anew)
- request-approval: case member, admin or examiner.
- approve / reject: case member with role reviewer or admin, logged in as a user account
  (not the dev header), and NOT the report's author nor the requester.
- finalize: case member with role admin, examiner or reviewer, user account, status approved;
  the stored PDF is re-hashed first and must still match.
- final is immutable (no further transition; DB trigger refuses UPDATE/DELETE of the row).
Every step writes a custody entry (report_approval_requested / report_approved /
report_rejected / report_finalized) and an append-only report_review_events row.

GET  /api/reports/{report_id}/review
POST /api/reports/{report_id}/request-approval   {note?}
POST /api/reports/{report_id}/approve            {note?}
POST /api/reports/{report_id}/reject             {reason}
POST /api/reports/{report_id}/finalize           {note?}
POST /api/evidence/{evidence_id}/transfers       {from_party, to_party, reason, transferred_at?,
                                                  location?, seal?}
GET  /api/evidence/{evidence_id}/transfers
GET  /api/cases/{case_id}/transfers              (?evidence_id=)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import custody
from app.approvals.models import EvidenceTransfer, ReportReview, ReportReviewEvent
from app.auth import service
from app.auth.deps import CurrentPrincipal, examiner_for, require_user
from app.clock import utc_now_iso
from app.hashing import hash_file
from app.models import Case, Evidence
from app.report.models import Report
from app.routes import DbSession

router = APIRouter(prefix="/api")


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=2000)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class TransferIn(BaseModel):
    from_party: str = Field(min_length=1, max_length=200)
    to_party: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)
    transferred_at: str | None = Field(
        default=None, description="ISO 8601 with a UTC offset; default: now (server clock)"
    )
    location: str = Field(default="", max_length=300)
    seal: str = Field(default="", max_length=200)

    @field_validator("transferred_at")
    @classmethod
    def _iso_with_offset(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(
                "transferred_at must be ISO 8601, e.g. 2026-10-09T10:30:00+05:30"
            ) from None
        if dt.tzinfo is None:
            raise ValueError("transferred_at must include a UTC offset (no naive local times)")
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---- report review ------------------------------------------------------------------------------
def register(db: Session, report: Report, p: service.Principal) -> ReportReview:
    """Called when a report is generated: records the author's user id (draft)."""
    row = ReportReview(
        report_id=report.id,
        case_id=report.case_id,
        status="draft",
        author=report.examiner,
        author_user_id=p.user_id,
    )
    db.add(row)
    db.commit()
    return row


def review_of(db: Session, report: Report) -> ReportReview:
    """The review row; reports generated before this module existed get a draft row whose
    author is known only by the examiner string."""
    row = db.scalars(select(ReportReview).where(ReportReview.report_id == report.id)).first()
    if row is None:
        row = ReportReview(
            report_id=report.id, case_id=report.case_id, status="draft", author=report.examiner
        )
        db.add(row)
        db.commit()
    return row


def status_of(db: Session, report_id: int) -> str:
    row = db.scalars(select(ReportReview).where(ReportReview.report_id == report_id)).first()
    return row.status if row is not None else "draft"


def review_out(db: Session, report: Report, rv: ReportReview) -> dict:
    events = db.scalars(
        select(ReportReviewEvent)
        .where(ReportReviewEvent.report_id == report.id)
        .order_by(ReportReviewEvent.id)
    )
    return {
        "report_id": report.id,
        "case_id": report.case_id,
        "status": rv.status,
        "final": rv.status == "final",
        "author": rv.author,
        "requested_by": rv.requested_by,
        "requested_at": rv.requested_at,
        "approved_by": rv.approved_by,
        "approved_at": rv.approved_at,
        "rejected_by": rv.rejected_by,
        "rejected_at": rv.rejected_at,
        "finalized_by": rv.finalized_by,
        "finalized_at": rv.finalized_at,
        "report_sha256": report.sha256,
        "events": [
            {
                "action": e.action,
                "actor": e.actor,
                "actor_role": e.actor_role,
                "note": e.note,
                "at": e.at,
                "custody_seq": e.custody_seq,
            }
            for e in events
        ],
    }


def _report(db: Session, report_id: int) -> Report:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    return r


def _step(
    db: Session,
    report: Report,
    rv: ReportReview,
    p: service.Principal,
    action: str,
    custody_action: str,
    note: str,
    extra: dict | None = None,
) -> None:
    entry = custody.append_entry(
        db,
        report.case_id,
        custody_action,
        examiner_for(p),
        {
            "report_id": report.id,
            "report_sha256": report.sha256,
            "status": rv.status,
            "actor_user_id": p.user_id,
            "actor_role": p.role if p.is_user else "dev-header (unauthenticated)",
            "author": rv.author,
            "note": note,
            **(extra or {}),
        },
    )
    db.add(
        ReportReviewEvent(
            report_id=report.id,
            case_id=report.case_id,
            action=action,
            actor=examiner_for(p),
            actor_user_id=p.user_id,
            actor_role=p.role if p.is_user else "dev-header",
            note=note,
            at=entry.timestamp_utc,
            custody_seq=entry.seq,
        )
    )
    db.commit()


def _conflict(rv: ReportReview, wanted: str) -> HTTPException:
    if rv.status == "final":
        return HTTPException(409, "the report is final and immutable")
    return HTTPException(409, f"report is {rv.status}; this step needs status {wanted}")


@router.get("/reports/{report_id}/review")
def get_review(report_id: int, db: DbSession):
    r = _report(db, report_id)
    return review_out(db, r, review_of(db, r))


@router.post("/reports/{report_id}/request-approval")
def request_approval(
    report_id: int, p: CurrentPrincipal, db: DbSession, body: NoteIn | None = None
):
    r = _report(db, report_id)
    rv = review_of(db, r)
    if rv.status != "draft":
        raise _conflict(rv, "draft")
    rv.status = "pending_approval"
    rv.requested_by, rv.requested_by_user_id = examiner_for(p), p.user_id
    rv.requested_at = utc_now_iso()
    db.commit()
    _step(db, r, rv, p, "requested", "report_approval_requested", (body or NoteIn()).note)
    return review_out(db, r, rv)


def _not_self(rv: ReportReview, r: Report, p: service.Principal) -> None:
    me = examiner_for(p)
    if (rv.author_user_id is not None and rv.author_user_id == p.user_id) or me == r.examiner:
        raise HTTPException(403, "two-person rule: the report's author cannot approve or reject it")
    if (
        rv.requested_by_user_id is not None and rv.requested_by_user_id == p.user_id
    ) or me == rv.requested_by:
        raise HTTPException(403, "two-person rule: the requester cannot approve or reject it")


@router.post("/reports/{report_id}/approve")
def approve(report_id: int, p: CurrentPrincipal, db: DbSession, body: NoteIn | None = None):
    require_user(p)
    r = _report(db, report_id)
    rv = review_of(db, r)
    if rv.status != "pending_approval":
        raise _conflict(rv, "pending_approval")
    _not_self(rv, r, p)
    chain = custody.verify_chain(db, r.case_id)
    rv.status = "approved"
    rv.approved_by, rv.approved_by_user_id = examiner_for(p), p.user_id
    rv.approved_at = utc_now_iso()
    db.commit()
    _step(
        db,
        r,
        rv,
        p,
        "approved",
        "report_approved",
        (body or NoteIn()).note,
        {"chain_ok_at_approval": chain["ok"], "head_hash_at_approval": chain["head_hash"]},
    )
    return review_out(db, r, rv)


@router.post("/reports/{report_id}/reject")
def reject(report_id: int, body: RejectIn, p: CurrentPrincipal, db: DbSession):
    require_user(p)
    r = _report(db, report_id)
    rv = review_of(db, r)
    if rv.status != "pending_approval":
        raise _conflict(rv, "pending_approval")
    _not_self(rv, r, p)
    rv.status = "rejected"
    rv.rejected_by, rv.rejected_at = examiner_for(p), utc_now_iso()
    db.commit()
    _step(db, r, rv, p, "rejected", "report_rejected", body.reason)
    return review_out(db, r, rv)


@router.post("/reports/{report_id}/finalize")
def finalize(report_id: int, p: CurrentPrincipal, db: DbSession, body: NoteIn | None = None):
    require_user(p)
    r = _report(db, report_id)
    rv = review_of(db, r)
    if rv.status != "approved":
        raise _conflict(rv, "approved")
    try:
        observed = hash_file(r.file_path).sha256
    except OSError:
        observed = ""
    if observed != r.sha256:
        raise HTTPException(
            409, "stored report file no longer matches its recorded SHA-256; refusing to finalize"
        )
    chain = custody.verify_chain(db, r.case_id)
    _step(
        db,
        r,
        rv,
        p,
        "finalized",
        "report_finalized",
        (body or NoteIn()).note,
        {
            "approved_by": rv.approved_by,
            "approved_at": rv.approved_at,
            "file_sha256_verified": observed,
            "chain_ok_at_finalize": chain["ok"],
        },
    )
    rv.status = "final"  # last write to this row: the trigger refuses any later change
    rv.finalized_by, rv.finalized_by_user_id = examiner_for(p), p.user_id
    rv.finalized_at = utc_now_iso()
    db.commit()
    return review_out(db, r, rv)


# ---- evidence transfers -------------------------------------------------------------------------
def transfer_out(t: EvidenceTransfer) -> dict:
    return {
        "id": t.id,
        "case_id": t.case_id,
        "evidence_id": t.evidence_id,
        "from_party": t.from_party,
        "to_party": t.to_party,
        "reason": t.reason,
        "transferred_at": t.transferred_at,
        "location": t.location,
        "seal": t.seal,
        "recorded_by": t.recorded_by,
        "recorded_at": t.recorded_at,
        "custody_seq": t.custody_seq,
    }


@router.post("/evidence/{evidence_id}/transfers", status_code=201)
def add_transfer(evidence_id: int, body: TransferIn, p: CurrentPrincipal, db: DbSession):
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    who = examiner_for(p)
    when = body.transferred_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    details = {
        "from": body.from_party,
        "to": body.to_party,
        "reason": body.reason,
        "transferred_at": when,
        "transferred_at_source": "stated by recorder" if body.transferred_at else "server clock",
        "location": body.location,
        "seal": body.seal,
        "evidence_sha256": ev.sha256,
        "recorded_by_user_id": p.user_id,
    }
    entry = custody.append_entry(db, ev.case_id, "evidence_transferred", who, details, ev.id)
    t = EvidenceTransfer(
        case_id=ev.case_id,
        evidence_id=ev.id,
        from_party=body.from_party,
        to_party=body.to_party,
        reason=body.reason,
        transferred_at=when,
        location=body.location,
        seal=body.seal,
        recorded_by=who,
        recorded_by_user_id=p.user_id,
        recorded_at=entry.timestamp_utc,
        custody_seq=entry.seq,
    )
    db.add(t)
    db.commit()
    return transfer_out(t)


@router.get("/evidence/{evidence_id}/transfers")
def list_evidence_transfers(evidence_id: int, db: DbSession):
    if db.get(Evidence, evidence_id) is None:
        raise HTTPException(404, "Evidence not found")
    rows = db.scalars(
        select(EvidenceTransfer)
        .where(EvidenceTransfer.evidence_id == evidence_id)
        .order_by(EvidenceTransfer.id)
    )
    return [transfer_out(t) for t in rows]


@router.get("/cases/{case_id}/transfers")
def list_case_transfers(case_id: int, db: DbSession, evidence_id: int | None = None):
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    q = select(EvidenceTransfer).where(EvidenceTransfer.case_id == case_id)
    if evidence_id is not None:
        q = q.where(EvidenceTransfer.evidence_id == evidence_id)
    return [transfer_out(t) for t in db.scalars(q.order_by(EvidenceTransfer.id))]
