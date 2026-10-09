"""Authentication, user administration and case membership API (prefix /api).

POST   /api/auth/login                      public; rate limited; returns the token once
POST   /api/auth/logout                     revokes the presented session
GET    /api/auth/me                         the current user, role, permissions, memberships
POST   /api/auth/password                   change own password (revokes other sessions)
GET    /api/users                           admin
POST   /api/users                           admin
GET    /api/users/{user_id}                 admin
PATCH  /api/users/{user_id}                 admin (display_name, role, active)
POST   /api/users/{user_id}/password        admin password reset (revokes that user's sessions)
POST   /api/users/{user_id}/unlock          admin
GET    /api/cases/{case_id}/members         case member or admin
POST   /api/cases/{case_id}/members         admin; custody entry member_added
DELETE /api/cases/{case_id}/members/{uid}   admin; custody entry member_removed
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import custody, settings
from app.auth import passwords, service
from app.auth.access import add_member
from app.auth.deps import CurrentPrincipal
from app.auth.models import ROLES, AuthSession, CaseMember, User
from app.auth.policy import member_case_ids
from app.models import Case
from app.routes import DbSession

router = APIRouter(prefix="/api")

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
Role = Literal["admin", "examiner", "reviewer", "readonly"]

PERMISSIONS = {
    "admin": [
        "users.manage",
        "cases.list_all",
        "case.create",
        "case.members.manage",
        "case.read (member)",
        "case.write (member)",
        "report.approve (member, not own report)",
        "report.finalize (member)",
        "audit.read_all",
    ],
    "examiner": [
        "case.create",
        "case.read (member)",
        "case.write (member)",
        "report.request_approval (member)",
        "report.finalize (member, once approved)",
    ],
    "reviewer": [
        "case.read (member)",
        "report.approve (member, not own report)",
        "report.finalize (member, once approved)",
    ],
    "readonly": ["case.read (member)"],
}


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=passwords.MAX_LENGTH)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=passwords.MAX_LENGTH)
    new_password: str = Field(min_length=1, max_length=passwords.MAX_LENGTH)


class PasswordResetIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=passwords.MAX_LENGTH)


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    role: Role
    password: str = Field(min_length=1, max_length=passwords.MAX_LENGTH)


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    active: bool | None = None


class MemberIn(BaseModel):
    user_id: int


def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "active": u.active,
        "locked": service.is_locked(u),
        "locked_until": u.locked_until if service.is_locked(u) else "",
        "created_at": u.created_at,
        "created_by": u.created_by,
        "last_login_at": u.last_login_at,
        "password_changed_at": u.password_changed_at,
    }


def create_user(
    db: Session, username: str, display_name: str, role: str, password: str, created_by: str
) -> User:
    """Shared by the API and `python -m app.cli create-admin`. Raises ValueError for invalid
    input (policy) and LookupError for a duplicate username."""
    uname = username.strip().lower()
    if not USERNAME.match(uname):
        raise ValueError(
            "username must be 3-64 characters: lowercase letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    passwords.check_policy(password, uname)
    u = User(
        username=uname,
        display_name=display_name.strip(),
        role=role,
        password_hash=passwords.hash_password(password),
        created_by=created_by,
    )
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise LookupError("username already exists") from None
    return u


def active_admins(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True))
    )


def _user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    return u


# ---- authentication ---------------------------------------------------------------------------
@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: DbSession):
    addr = service.client_address(request)
    try:
        token, sess, user = service.login(
            db, body.username, body.password, addr, request.headers.get("user-agent", "")
        )
    except service.LoginRefused as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(exc.status, exc.detail, headers=headers) from None
    max_age = int((service.parse(sess.expires_at) - service.now()).total_seconds())
    response.set_cookie(
        service.COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite=settings.cookie_samesite(),
        secure=settings.cookie_secure(),
        path="/api",
    )
    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": sess.expires_at,
        "idle_timeout_minutes": service.idle_minutes(),
        "user": user_out(user),
    }


@router.post("/auth/logout")
def logout(p: CurrentPrincipal, response: Response, db: DbSession):
    service.revoke_session(db, p.session_id, "logout")
    response.delete_cookie(service.COOKIE, path="/api")
    return {"ok": True}


@router.get("/auth/me")
def me(p: CurrentPrincipal, db: DbSession):
    u = _user(db, p.user_id)
    sess = db.get(AuthSession, p.session_id)
    return {
        **user_out(u),
        "permissions": PERMISSIONS[u.role],
        "case_ids": member_case_ids(db, u.id),
        "session": {"expires_at": sess.expires_at, "created_at": sess.created_at},
    }


@router.post("/auth/password")
def change_password(body: PasswordChangeIn, p: CurrentPrincipal, db: DbSession):
    u = _user(db, p.user_id)
    if not passwords.verify_password(body.current_password, u.password_hash):
        raise HTTPException(403, "current password is incorrect")
    try:
        passwords.check_policy(body.new_password, u.username)
    except passwords.PasswordPolicyError as exc:
        raise HTTPException(422, str(exc)) from None
    u.password_hash = passwords.hash_password(body.new_password)
    u.password_changed_at = service.iso(service.now())
    db.commit()
    revoked = service.revoke_user_sessions(db, u.id, "password changed", keep=p.session_id)
    return {"ok": True, "other_sessions_revoked": revoked}


# ---- users (admin) ----------------------------------------------------------------------------
@router.get("/users")
def list_users(db: DbSession):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", status_code=201)
def add_user(body: UserIn, p: CurrentPrincipal, db: DbSession):
    try:
        u = create_user(db, body.username, body.display_name, body.role, body.password, p.examiner)
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return user_out(u)


@router.get("/users/{user_id}")
def get_user(user_id: int, db: DbSession):
    u = _user(db, user_id)
    return {**user_out(u), "case_ids": member_case_ids(db, u.id)}


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, p: CurrentPrincipal, db: DbSession):
    u = _user(db, user_id)
    demoting = body.role is not None and body.role != "admin" and u.role == "admin"
    deactivating = body.active is False and u.active and u.role == "admin"
    if (demoting or deactivating) and active_admins(db) <= 1:
        raise HTTPException(409, "refused: this would leave no active admin account")
    if body.display_name is not None:
        u.display_name = body.display_name.strip()
    if body.role is not None:
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    db.commit()
    if body.active is False:
        service.revoke_user_sessions(db, u.id, "account deactivated")
    return user_out(u)


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, body: PasswordResetIn, db: DbSession):
    u = _user(db, user_id)
    try:
        passwords.check_policy(body.new_password, u.username)
    except passwords.PasswordPolicyError as exc:
        raise HTTPException(422, str(exc)) from None
    u.password_hash = passwords.hash_password(body.new_password)
    u.password_changed_at = service.iso(service.now())
    u.failed_logins, u.locked_until = 0, ""
    db.commit()
    revoked = service.revoke_user_sessions(db, u.id, "password reset by admin")
    return {"ok": True, "sessions_revoked": revoked}


@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: int, db: DbSession):
    u = _user(db, user_id)
    u.failed_logins, u.locked_until = 0, ""
    db.commit()
    return user_out(u)


# ---- case membership ----------------------------------------------------------------------------
def _members(db: Session, case_id: int) -> list[dict]:
    rows = db.execute(
        select(CaseMember, User)
        .join(User, User.id == CaseMember.user_id)
        .where(CaseMember.case_id == case_id)
        .order_by(CaseMember.id)
    ).all()
    return [
        {
            "user_id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "role": u.role,
            "active": u.active,
            "added_by": m.added_by,
            "added_at": m.added_at,
        }
        for m, u in rows
    ]


@router.get("/cases/{case_id}/members")
def list_members(case_id: int, db: DbSession):
    return _members(db, case_id)


@router.post("/cases/{case_id}/members", status_code=201)
def post_member(case_id: int, body: MemberIn, p: CurrentPrincipal, db: DbSession):
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    u = _user(db, body.user_id)
    if not u.active:
        raise HTTPException(409, "user is deactivated")
    added = add_member(db, case_id, u, p.examiner)
    return {"added": added, "members": _members(db, case_id)}


@router.delete("/cases/{case_id}/members/{user_id}")
def delete_member(case_id: int, user_id: int, p: CurrentPrincipal, db: DbSession):
    row = db.scalars(
        select(CaseMember).where(CaseMember.case_id == case_id, CaseMember.user_id == user_id)
    ).first()
    if row is None:
        raise HTTPException(404, "User is not a member of this case")
    u = _user(db, user_id)
    db.delete(row)
    db.commit()
    custody.append_entry(
        db, case_id, "member_removed", p.examiner, {"user_id": u.id, "username": u.username}
    )
    return {"removed": True, "members": _members(db, case_id)}
