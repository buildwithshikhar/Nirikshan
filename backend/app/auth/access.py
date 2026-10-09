"""Case membership helpers (no dependency on app.routes, so app.routes can import this)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import custody
from app.auth import service
from app.auth.models import CaseMember, User


def add_member(db: Session, case_id: int, user: User, by: str) -> bool:
    """Idempotent; True when a row was added (custody entry member_added)."""
    exists = db.scalars(
        select(CaseMember).where(CaseMember.case_id == case_id, CaseMember.user_id == user.id)
    ).first()
    if exists is not None:
        return False
    db.add(CaseMember(case_id=case_id, user_id=user.id, added_by=by))
    db.commit()
    custody.append_entry(
        db,
        case_id,
        "member_added",
        by,
        {"user_id": user.id, "username": user.username, "role_at_grant": user.role},
    )
    return True


def grant_creator(db: Session, case_id: int, p: service.Principal) -> None:
    """The user who creates a case becomes its first member (no-op for dev principals)."""
    if p.is_user:
        u = db.get(User, p.user_id)
        if u is not None:
            add_member(db, case_id, u, p.examiner)
