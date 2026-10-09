"""Route-level authorisation: one global dependency (`authorize`) decides every request.

How a request is decided (docs/security/auth.md has the full matrix):
1. The matched route template + method select a Rule: an explicit entry in POLICY, else the
   default for case-scoped templates (a path parameter that names a case-scoped object, see
   RESOLVERS: GET/HEAD -> READ, anything else -> WRITE). A route with neither is refused with
   403 (fail closed), and tests/test_auth_policy.py fails if any registered route has no rule.
2. The principal is resolved (app.auth.service.resolve): 401 when absent or invalid.
3. Case scope: every case-scoped path parameter is resolved to its case. A missing object and a
   case the user is not a member of give the SAME 404 body, so existence is not leaked. Members
   whose role is not allowed get 403 (they already know the case exists).
Dev principals (NIRIKSHAN_DEV_HEADER_AUTH=1) skip membership and role checks but are refused for
rules with real_user=True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.models import ROLES, CaseMember
from app.db import get_db

ALL_ROLES = frozenset(ROLES)
WRITE_ROLES = frozenset({"admin", "examiner"})
REVIEW_ROLES = frozenset({"admin", "reviewer"})
SIGNOFF_ROLES = frozenset({"admin", "examiner", "reviewer"})


@dataclass(frozen=True)
class Rule:
    scope: str  # public | global | case | case_meta | audit
    roles: frozenset[str] = field(default=ALL_ROLES)
    real_user: bool = False  # refuse dev_header / dev_anonymous principals
    name: str = ""


PUBLIC = Rule("public", name="public")
ANY = Rule("global", name="authenticated")
USER = Rule("global", real_user=True, name="authenticated user (no dev header)")
ADMIN = Rule("global", frozenset({"admin"}), real_user=True, name="admin")
CASE_CREATE = Rule("global", WRITE_ROLES, name="admin or examiner")
CASE_META = Rule("case_meta", name="case member, or admin")
ADMIN_CASE = Rule("case_meta", frozenset({"admin"}), real_user=True, name="admin (any case)")
READ = Rule("case", name="case member (any role)")
WRITE = Rule("case", WRITE_ROLES, name="case member with role admin or examiner")
REVIEW = Rule("case", REVIEW_ROLES, real_user=True, name="case member with role admin or reviewer")
SIGNOFF = Rule(
    "case", SIGNOFF_ROLES, real_user=True, name="case member with role admin, examiner or reviewer"
)
AUDIT = Rule("audit", name="admin (all), or case member with ?case_id=")


def _resolvers() -> dict:
    """param -> (model, case_id getter, not-found message). Imported lazily (import cycles)."""
    from app.analytics.models import AnalyticsRun
    from app.jobs.models import Job
    from app.models import CarveRun, Case, Clip, Evidence
    from app.report.models import Report

    out = {
        "case_id": (Case, lambda r: r.id, "Case not found"),
        "evidence_id": (Evidence, lambda r: r.case_id, "Evidence not found"),
        "clip_id": (Clip, lambda r: r.case_id, "Clip not found"),
        "run_id": (CarveRun, lambda r: r.case_id, "Run not found"),
        "analytics_run_id": (AnalyticsRun, lambda r: r.case_id, "Analytics run not found"),
        "report_id": (Report, lambda r: r.case_id, "Report not found"),
        "job_id": (Job, lambda r: r.case_id, "Job not found"),
    }
    from app.acquire.models import AcquisitionSession
    from app.correlation.models import CorrelationLink, ExternalLog

    out["session_id"] = (AcquisitionSession, lambda r: r.case_id, "Acquisition not found")
    out["log_id"] = (ExternalLog, lambda r: r.case_id, "External log not found")
    out["link_id"] = (CorrelationLink, lambda r: r.case_id, "Link not found")
    try:
        from app.package.models import Package

        out["package_id"] = (Package, lambda r: r.case_id, "Package not found")
    except ImportError:  # pragma: no cover - package module absent
        pass
    return out


def resolver_key(template: str, param: str) -> str:
    if param == "run_id" and template.startswith("/api/analytics/"):
        return "analytics_run_id"
    return param


# Explicit rules. Keys are (METHOD, route template). Case-scoped routes not listed here get the
# default (GET/HEAD -> READ, else WRITE) from default_rule().
POLICY: dict[tuple[str, str], Rule] = {
    ("GET", "/health"): PUBLIC,
    ("GET", "/api/signing-key"): PUBLIC,  # public half only
    ("GET", "/api/package-key"): PUBLIC,  # public half only
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/logout"): USER,
    ("GET", "/api/auth/me"): USER,
    ("POST", "/api/auth/password"): USER,
    ("GET", "/api/system"): ANY,
    ("GET", "/api/analytics/models"): ANY,
    ("GET", "/api/cases"): ANY,  # filtered to member cases in the handler
    ("POST", "/api/cases"): CASE_CREATE,
    ("GET", "/api/cases/{case_id}"): CASE_META,
    ("GET", "/api/audit"): AUDIT,
    ("GET", "/api/users"): ADMIN,
    ("POST", "/api/users"): ADMIN,
    ("GET", "/api/users/{user_id}"): ADMIN,
    ("PATCH", "/api/users/{user_id}"): ADMIN,
    ("POST", "/api/users/{user_id}/password"): ADMIN,
    ("POST", "/api/users/{user_id}/unlock"): ADMIN,
    ("GET", "/api/cases/{case_id}/members"): CASE_META,
    ("POST", "/api/cases/{case_id}/members"): ADMIN_CASE,
    ("DELETE", "/api/cases/{case_id}/members/{user_id}"): ADMIN_CASE,
    # reference / read-only global data (no case content)
    ("GET", "/api/events/grammar"): ANY,
    ("GET", "/api/acquisition/capabilities"): ANY,
    ("GET", "/api/acquisition/ewf"): ANY,
    ("GET", "/api/recovery/fragment-reassembly"): ANY,
    ("GET", "/api/recovery/agreement"): ANY,
    ("GET", "/api/oem-registry"): ANY,
    ("GET", "/api/validation/summary"): ANY,
    ("GET", "/api/validation/scorecards"): ANY,
    ("GET", "/api/validation/regression"): ANY,
    ("GET", "/api/validation/false-rates"): ANY,
    ("GET", "/api/validation/crosscheck"): ANY,
    ("GET", "/api/validation/reruns"): ANY,
    ("GET", "/api/validation/reruns/{rerun_id}"): ANY,
    ("POST", "/api/validation/reruns"): CASE_CREATE,  # heavy subprocess: admin or examiner
    # approvals (app.approvals)
    ("POST", "/api/reports/{report_id}/request-approval"): WRITE,
    ("POST", "/api/reports/{report_id}/approve"): REVIEW,
    ("POST", "/api/reports/{report_id}/reject"): REVIEW,
    ("POST", "/api/reports/{report_id}/finalize"): SIGNOFF,
}


def default_rule(method: str, template: str, params: list[str]) -> Rule | None:
    known = _resolvers()
    if any(resolver_key(template, p) in known for p in params):
        return READ if method in ("GET", "HEAD") else WRITE
    return None


def rule_for(method: str, template: str, params: list[str]) -> Rule | None:
    if method == "HEAD":
        method_key = "GET"
    else:
        method_key = method
    rule = POLICY.get((method_key, template))
    return rule if rule is not None else default_rule(method_key, template, params)


def is_member(db: Session, case_id: int, user_id: int | None) -> bool:
    if user_id is None:
        return False
    return (
        db.scalars(
            select(CaseMember.id).where(
                CaseMember.case_id == case_id, CaseMember.user_id == user_id
            )
        ).first()
        is not None
    )


def member_case_ids(db: Session, user_id: int) -> list[int]:
    return list(db.scalars(select(CaseMember.case_id).where(CaseMember.user_id == user_id)))


def _case_ids_from_path(db: Session, template: str, path_params: dict) -> list[int]:
    """Resolve every case-scoped path parameter. Missing objects -> 404 with the route's own
    not-found message (identical to what a non-member gets)."""
    known = _resolvers()
    case_ids: list[int] = []
    for param, raw in path_params.items():
        key = resolver_key(template, param)
        if key not in known:
            continue
        model, getter, msg = known[key]
        try:
            obj_id = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(404, msg) from None
        row = db.get(model, obj_id)
        if row is None:
            raise HTTPException(404, msg)
        case_ids.append(getter(row))
    if len(set(case_ids)) > 1:  # e.g. /cases/1/.../evidence/2 where evidence 2 is in case 3
        raise HTTPException(404, "Not found")
    return case_ids


def _not_found_for(template: str, path_params: dict) -> str:
    known = _resolvers()
    for param in path_params:
        key = resolver_key(template, param)
        if key in known:
            return known[key][2]
    return "Not found"


def check_case_access(
    db: Session, p: service.Principal, case_id: int, rule: Rule, msg: str
) -> None:
    """Membership + role for one case. Raises 404 (not a member) or 403 (role)."""
    if p.is_dev:
        return
    if rule.scope == "case_meta" and p.role == "admin":
        return  # admins see case metadata and manage membership without being members
    if not is_member(db, case_id, p.user_id):  # membership before role: never leak existence
        raise HTTPException(404, msg)
    if p.role not in rule.roles:
        raise HTTPException(403, f"your role ({p.role}) does not allow this: requires {rule.name}")


def authorize(request: Request, db: Annotated[Session, Depends(get_db)]) -> None:
    """Global dependency registered on the FastAPI app (app.main)."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    regex = getattr(route, "path_regex", None)
    # The template must be the FULL request path (routers carry their own /api prefix). A router
    # included under an extra prefix would make the template differ: refuse instead of guessing.
    if template is None or regex is None or not regex.match(request.url.path):
        raise HTTPException(403, "no access rule for this route (fail closed)")
    params = list(request.path_params)
    rule = rule_for(request.method, template, params)
    if rule is None:
        raise HTTPException(403, f"no access rule for {request.method} {template} (fail closed)")
    if rule.scope == "public":
        return
    p = service.resolve(request, db)
    if rule.real_user and not p.is_user:
        raise HTTPException(
            403,
            "this action needs a logged-in user account; the X-Examiner development "
            "attestation is not accepted for it",
        )
    if rule.scope == "global":
        if not p.is_dev and p.role not in rule.roles:
            raise HTTPException(
                403, f"your role ({p.role}) does not allow this: requires {rule.name}"
            )
        return
    if rule.scope == "audit":
        if p.is_dev or p.role == "admin":
            return
        raw = request.query_params.get("case_id")
        try:
            cid = int(raw) if raw is not None else None
        except ValueError:
            cid = None
        if cid is None:
            raise HTTPException(
                403, "non-admin users must pass ?case_id= for a case they are a member of"
            )
        if not is_member(db, cid, p.user_id):
            raise HTTPException(404, "Case not found")
        return
    # case / case_meta
    if p.is_dev:
        return  # dev mode: no case scoping (the route's own 404s and 400s apply, as before)
    case_ids = _case_ids_from_path(db, template, request.path_params)
    if not case_ids:
        raise HTTPException(403, f"no case-scoped parameter on {template} (fail closed)")
    check_case_access(db, p, case_ids[0], rule, _not_found_for(template, request.path_params))


def visible_case_ids(db: Session, p: service.Principal) -> list[int] | None:
    """None = all cases (admin, dev principals); otherwise the member case ids."""
    if p.is_dev or p.role == "admin":
        return None
    return member_case_ids(db, p.user_id)


def iter_routes(app) -> list[tuple[str, str]]:
    """(METHOD, full path template) for every API route, walking included routers (FastAPI
    >= 0.13x includes routers lazily). Used by the tests that enumerate the whole API."""
    from fastapi.routing import APIRoute

    out: list[tuple[str, str]] = []

    def walk(routes, prefix: str) -> None:
        for r in routes:
            if isinstance(r, APIRoute):
                for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                    out.append((m, prefix + r.path))
            elif hasattr(r, "original_router"):
                ctx = getattr(r, "include_context", None)
                walk(r.original_router.routes, prefix + (getattr(ctx, "prefix", "") or ""))

    walk(app.router.routes, "")
    return out
