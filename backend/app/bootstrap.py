"""First-run account bootstrap (never prints or logs a password).

- First admin from the environment: NIRIKSHAN_FIRST_ADMIN_USERNAME plus the password from
  NIRIKSHAN_FIRST_ADMIN_PASSWORD_FILE (preferred: a file, first line) or
  NIRIKSHAN_FIRST_ADMIN_PASSWORD.
  Applied at startup only while NO active admin exists; afterwards the variables are ignored.
  `python -m app.cli create-admin <username>` does the same interactively.
- Demo viewer: `python -m app.cli create-demo-viewer` creates one read-only account that is a
  member of the reference-data demo case(s) only (see docs/DEPLOYMENT.md, public instances).
"""

import logging
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.access import add_member
from app.auth.models import User
from app.auth.routes import active_admins, create_user
from app.models import Case

log = logging.getLogger("nirikshan.bootstrap")
DEMO_CASE_PREFIX = "DEMO-REFERENCE"
VIEWER_USERNAME = "demo-viewer"


def read_secret(prefix: str) -> str | None:
    """`<prefix>_FILE` (first line) wins over `<prefix>`."""
    path = os.getenv(f"{prefix}_FILE")
    if path:
        lines = Path(path).read_text().splitlines()
        return lines[0] if lines else None
    return os.getenv(prefix) or None


def first_admin_from_env(db: Session) -> str | None:
    """Create the first admin from the environment when no active admin exists. Returns the
    username created, else None. Raises ValueError (message never contains the password)."""
    username = os.getenv("NIRIKSHAN_FIRST_ADMIN_USERNAME", "").strip()
    if not username or active_admins(db) > 0:
        return None
    password = read_secret("NIRIKSHAN_FIRST_ADMIN_PASSWORD")
    if not password:
        raise ValueError(
            "NIRIKSHAN_FIRST_ADMIN_USERNAME is set but neither "
            "NIRIKSHAN_FIRST_ADMIN_PASSWORD_FILE nor NIRIKSHAN_FIRST_ADMIN_PASSWORD "
            "gives a password"
        )
    display = os.getenv("NIRIKSHAN_FIRST_ADMIN_DISPLAY_NAME", "").strip() or username
    try:
        user = create_user(db, username, display, "admin", password, "env:first-admin")
    except (ValueError, LookupError) as exc:
        raise ValueError(f"first admin from environment refused: {exc}") from None
    log.info("first admin account created", extra={"fields": {"username": user.username}})
    return user.username


def create_demo_viewer(db: Session, password: str) -> tuple[str, list[str]]:
    """Create (or reuse) the read-only demo viewer and add it to every demo reference case."""
    user = db.scalars(select(User).where(User.username == VIEWER_USERNAME)).first()
    if user is None:
        user = create_user(
            db, VIEWER_USERNAME, "Demo viewer (read-only)", "readonly", password, "cli:demo-viewer"
        )
    added = []
    for case in db.scalars(select(Case).where(Case.case_number.like(f"{DEMO_CASE_PREFIX}%"))):
        if add_member(db, case.id, user, "cli:demo-viewer"):
            added.append(case.case_number)
    return user.username, added
