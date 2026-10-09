"""Dependencies used by route modules: the current principal and the examiner string."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import service
from app.db import get_db


def current_principal(
    request: Request, db: Annotated[Session, Depends(get_db)]
) -> service.Principal:
    """The principal `authorize` resolved for this request (resolved here if it was not)."""
    return service.resolve(request, db)


CurrentPrincipal = Annotated[service.Principal, Depends(current_principal)]


def examiner_for(p: service.Principal) -> str:
    """Identity string for custody entries, runs and jobs. A dev-anonymous principal (dev mode,
    no header) keeps the historical 400 so mutations always carry a name."""
    if p.kind == "dev_anonymous":
        raise HTTPException(400, "X-Examiner header is required")
    return p.examiner


def require_user(p: service.Principal) -> service.Principal:
    if not p.is_user:
        raise HTTPException(
            403, "this action needs a logged-in user account (not the X-Examiner attestation)"
        )
    return p


def audit_identity(request: Request) -> str:
    """Identity recorded by the audit middleware: the principal resolved for the request, or
    "" when none was (public route, failed authentication)."""
    p = getattr(request.state, "principal", None)
    return p.examiner if p is not None else ""
