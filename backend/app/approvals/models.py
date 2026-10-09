"""Report review state, review events and evidence transfer records.

report_review_events and evidence_transfers are append-only (the same BEFORE UPDATE/DELETE
triggers as custody_entries, app.triggers). report_reviews rows change state, but a row whose
status is 'final' cannot be updated or deleted (trigger below); the custody log carries every
step regardless.
"""

from sqlalchemy import DDL, ForeignKey, Integer, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app import triggers
from app.db import Base
from app.models import _now

REVIEW_STATUSES = ("draft", "pending_approval", "approved", "rejected", "final")


class ReportReview(Base):
    __tablename__ = "report_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), unique=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    author: Mapped[str] = mapped_column(String(200), default="")
    author_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(200), default="")
    requested_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_at: Mapped[str] = mapped_column(String(40), default="")
    approved_by: Mapped[str] = mapped_column(String(200), default="")
    approved_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[str] = mapped_column(String(40), default="")
    rejected_by: Mapped[str] = mapped_column(String(200), default="")
    rejected_at: Mapped[str] = mapped_column(String(40), default="")
    finalized_by: Mapped[str] = mapped_column(String(200), default="")
    finalized_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finalized_at: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)


class ReportReviewEvent(Base):
    __tablename__ = "report_review_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(30))  # requested | approved | rejected | finalized
    actor: Mapped[str] = mapped_column(String(200))
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_role: Mapped[str] = mapped_column(String(20), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[str] = mapped_column(String(40), default=_now)
    custody_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EvidenceTransfer(Base):
    __tablename__ = "evidence_transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), index=True)
    from_party: Mapped[str] = mapped_column(String(200))
    to_party: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    transferred_at: Mapped[str] = mapped_column(String(40))  # when the handover happened (stated)
    location: Mapped[str] = mapped_column(String(300), default="")
    seal: Mapped[str] = mapped_column(String(200), default="")
    recorded_by: Mapped[str] = mapped_column(String(200))
    recorded_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[str] = mapped_column(String(40), default=_now)
    custody_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)


triggers._register(ReportReviewEvent.__table__)
triggers._register(EvidenceTransfer.__table__)

_T = ReportReview.__table__.name
for _op in ("UPDATE", "DELETE"):
    event.listen(
        ReportReview.__table__,
        "after_create",
        DDL(
            f"CREATE TRIGGER IF NOT EXISTS {_T}_final_no_{_op.lower()} BEFORE {_op} ON {_T} "
            f"WHEN OLD.status = 'final' "
            f"BEGIN SELECT RAISE(ABORT, 'a final report review is immutable'); END"
        ).execute_if(dialect="sqlite"),
    )
event.listen(
    ReportReview.__table__,
    "after_create",
    DDL(
        "CREATE OR REPLACE FUNCTION nirikshan_reject_final_review() RETURNS trigger AS $$ "
        "BEGIN IF OLD.status = 'final' THEN "
        "RAISE EXCEPTION 'a final report review is immutable'; END IF; "
        "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    ).execute_if(dialect="postgresql"),
)
event.listen(
    ReportReview.__table__,
    "after_create",
    DDL(
        f"CREATE TRIGGER {_T}_final_immutable BEFORE UPDATE OR DELETE ON {_T} "
        "FOR EACH ROW EXECUTE FUNCTION nirikshan_reject_final_review()"
    ).execute_if(dialect="postgresql"),
)
