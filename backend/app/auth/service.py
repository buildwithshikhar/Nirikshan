"""Principals, sessions and login.

Identity source, in order (docs/security/auth.md):
1. `Authorization: Bearer <token>` (any method), or the `nirikshan_session` cookie for safe
   methods (GET/HEAD) only, so a cross-site form cannot perform a mutation with the cookie.
   `POST /api/auth/logout` also accepts the cookie (logging someone out is not a privilege).
2. Only when NIRIKSHAN_DEV_HEADER_AUTH=1 (default off; development/tests): with no token, the
   `X-Examiner` header is accepted as an UNAUTHENTICATED attestation (principal kind
   "dev_header"), and a request with neither is "dev_anonymous" (reads only; mutations get the
   old 400 "X-Examiner header is required"). Dev principals bypass case membership but are
   refused for user management, membership changes, approvals and finalisation.
3. Otherwise 401.
A presented token that is invalid, expired or revoked is always 401; it never falls back to (2).
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import passwords
from app.auth.models import AuthSession, User
from app.auth.ratelimit import address_limiter, user_lock_s, user_max_failures

COOKIE = "nirikshan_session"
TOKEN_PREFIX = "nrk_"
SAFE_METHODS = ("GET", "HEAD")
LAST_SEEN_STEP_S = 60


def now() -> datetime:
    """Single clock for session/lockout decisions (tests monkeypatch this)."""
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds")


def parse(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def dev_header_auth() -> bool:
    return os.getenv("NIRIKSHAN_DEV_HEADER_AUTH", "").strip().lower() in ("1", "true", "yes")


def session_hours() -> float:
    try:
        return max(0.05, float(os.getenv("NIRIKSHAN_SESSION_HOURS", "") or 8))
    except ValueError:
        return 8.0


def idle_minutes() -> float:
    try:
        return max(1.0, float(os.getenv("NIRIKSHAN_SESSION_IDLE_MINUTES", "") or 30))
    except ValueError:
        return 30.0


def trust_forwarded_for() -> bool:
    return os.getenv("NIRIKSHAN_TRUST_X_FORWARDED_FOR", "").strip() in ("1", "true", "yes")


def client_address(request: Request) -> str:
    if trust_forwarded_for():
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[-1].strip()[:100]  # the hop our trusted proxy appended
    return (request.client.host if request.client else "unknown")[:100]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    kind: str  # user | dev_header | dev_anonymous
    role: str
    username: str = ""
    display_name: str = ""
    user_id: int | None = None
    session_id: int | None = None

    @property
    def is_user(self) -> bool:
        return self.kind == "user"

    @property
    def is_dev(self) -> bool:
        return self.kind != "user"

    @property
    def examiner(self) -> str:
        """The string written to custody entries, audit rows, runs and jobs."""
        if self.kind == "user":
            return f"{self.display_name} ({self.username})"
        return self.display_name  # dev_header: the attested header value; anonymous: ""


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def _presented_token(request: Request) -> str | None:
    authz = request.headers.get("authorization")
    if authz is not None:
        scheme, _, value = authz.partition(" ")
        if scheme.lower() != "bearer" or not value.strip():
            raise _unauthorized("Authorization header must be 'Bearer <token>'")
        return value.strip()
    cookie = request.cookies.get(COOKIE)
    if cookie:
        path = request.url.path
        if request.method in SAFE_METHODS or path == "/api/auth/logout":
            return cookie
        raise _unauthorized(
            "the session cookie is accepted for GET requests only; send the token as "
            "'Authorization: Bearer <token>' for this request"
        )
    return None


def principal_from_token(db: Session, token: str) -> Principal:
    row = db.scalars(select(AuthSession).where(AuthSession.token_hash == token_hash(token))).first()
    t = now()
    if row is None or row.revoked_at:
        raise _unauthorized("invalid or revoked session")
    exp, seen = parse(row.expires_at), parse(row.last_seen_at)
    if exp is None or t >= exp:
        raise _unauthorized("session expired; log in again")
    if seen is not None and t - seen >= timedelta(minutes=idle_minutes()):
        _revoke(db, row, "idle timeout")
        raise _unauthorized("session expired after inactivity; log in again")
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        _revoke(db, row, "account deactivated")
        raise _unauthorized("account is deactivated")
    if seen is None or (t - seen).total_seconds() >= LAST_SEEN_STEP_S:
        db.execute(update(AuthSession).where(AuthSession.id == row.id).values(last_seen_at=iso(t)))
        db.commit()
    return Principal(
        kind="user",
        role=user.role,
        username=user.username,
        display_name=user.display_name,
        user_id=user.id,
        session_id=row.id,
    )


def resolve(request: Request, db: Session) -> Principal:
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    token = _presented_token(request)
    if token is not None:
        p = principal_from_token(db, token)
    elif dev_header_auth():
        name = request.headers.get("x-examiner", "").strip()
        p = (
            Principal(kind="dev_header", role="admin", display_name=name[:200])
            if name
            else Principal(kind="dev_anonymous", role="admin")
        )
    else:
        detail = "authentication required: log in at POST /api/auth/login"
        if request.headers.get("x-examiner"):
            detail += " (X-Examiner is accepted only when NIRIKSHAN_DEV_HEADER_AUTH=1)"
        raise _unauthorized(detail)
    request.state.principal = p
    return p


def _revoke(db: Session, row: AuthSession, reason: str) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.id == row.id, AuthSession.revoked_at == "")
        .values(revoked_at=iso(now()), revoked_reason=reason[:100])
    )
    db.commit()


def revoke_session(db: Session, session_id: int, reason: str) -> None:
    row = db.get(AuthSession, session_id)
    if row is not None:
        _revoke(db, row, reason)


def revoke_user_sessions(db: Session, user_id: int, reason: str, keep: int | None = None) -> int:
    q = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at == "")
    if keep is not None:
        q = q.where(AuthSession.id != keep)
    n = db.execute(q.values(revoked_at=iso(now()), revoked_reason=reason[:100])).rowcount
    db.commit()
    return n


class LoginRefused(Exception):
    def __init__(self, status: int, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.status, self.detail, self.retry_after = status, detail, retry_after


GENERIC_FAILURE = "invalid username or password, or the account is locked or deactivated"


def login(
    db: Session, username: str, password: str, address: str, user_agent: str
) -> tuple[str, AuthSession, User]:
    """Returns (token, session, user) or raises LoginRefused. The token is returned once and
    never stored."""
    wait = address_limiter.retry_after(address)
    if wait:
        raise LoginRefused(429, "too many failed logins from this address; try later", wait)
    user = db.scalars(select(User).where(User.username == username.strip().lower())).first()
    t = now()
    if user is None:
        passwords.dummy_verify(password)
        address_limiter.failure(address)
        raise LoginRefused(401, GENERIC_FAILURE)
    locked = parse(user.locked_until)
    ok = passwords.verify_password(password, user.password_hash)
    if locked is not None and t < locked:
        address_limiter.failure(address)
        raise LoginRefused(401, GENERIC_FAILURE)
    if not ok or not user.active:
        address_limiter.failure(address)
        if not ok:
            fails = user.failed_logins + 1
            vals: dict = {"failed_logins": fails}
            if fails >= user_max_failures():
                vals = {
                    "failed_logins": 0,
                    "locked_until": iso(t + timedelta(seconds=user_lock_s())),
                }
            db.execute(update(User).where(User.id == user.id).values(**vals))
            db.commit()
        raise LoginRefused(401, GENERIC_FAILURE)
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    sess = AuthSession(
        user_id=user.id,
        token_hash=token_hash(token),
        created_at=iso(t),
        last_seen_at=iso(t),
        expires_at=iso(t + timedelta(hours=session_hours())),
        client=address,
        user_agent=user_agent[:500],
    )
    db.add(sess)
    user.failed_logins, user.locked_until, user.last_login_at = 0, "", iso(t)
    db.commit()
    return token, sess, user


def is_locked(user: User) -> bool:
    locked = parse(user.locked_until)
    return locked is not None and now() < locked
