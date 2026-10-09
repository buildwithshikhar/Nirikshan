"""Local users, sessions and case membership. Imported by app.main so create_all sees them."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import _now

ROLES = ("admin", "examiner", "reviewer", "readonly")


class User(Base):
    """A local account. Never deleted (custody entries name it); deactivate instead."""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    password_changed_at: Mapped[str] = mapped_column(String(40), default=_now)
    last_login_at: Mapped[str] = mapped_column(String(40), default="")


class AuthSession(Base):
    """An opaque bearer token. Only SHA-256(token) is stored, so a database reader cannot
    replay a session."""

    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[str] = mapped_column(String(40), default=_now)
    expires_at: Mapped[str] = mapped_column(String(40))
    last_seen_at: Mapped[str] = mapped_column(String(40), default=_now)
    revoked_at: Mapped[str] = mapped_column(String(40), default="")
    revoked_reason: Mapped[str] = mapped_column(String(100), default="")
    client: Mapped[str] = mapped_column(String(100), default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")


class CaseMember(Base):
    """A user may see and act on a case only while a row links them (see app.auth.policy)."""

    __tablename__ = "case_members"
    __table_args__ = (UniqueConstraint("case_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    added_by: Mapped[str] = mapped_column(String(200), default="")
    added_at: Mapped[str] = mapped_column(String(40), default=_now)
