"""Deployment settings: everything comes from environment variables and is validated at startup.

`NIRIKSHAN_PRODUCTION=1` is the production flag. It turns the safe-by-default rules into hard
requirements: the process refuses to start (listing every problem) instead of running misconfigured.
docs/DEPLOYMENT.md has the full variable reference.
"""

import os
from pathlib import Path

from app.config import data_dir, evidence_roots, key_dir

TRUE = ("1", "true", "yes")


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE


def production() -> bool:
    return _flag("NIRIKSHAN_PRODUCTION")


def dev_header_auth_enabled() -> bool:
    return _flag("NIRIKSHAN_DEV_HEADER_AUTH")


def cookie_secure() -> bool:
    """Secure cookie: explicit NIRIKSHAN_COOKIE_SECURE, else on in production."""
    raw = os.getenv("NIRIKSHAN_COOKIE_SECURE")
    return production() if raw is None or raw == "" else raw.strip().lower() in TRUE


def cookie_samesite() -> str:
    return os.getenv("NIRIKSHAN_COOKIE_SAMESITE", "strict").strip().lower()


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS")
    if raw is None:
        return [] if production() else ["http://localhost:5173"]
    return [o.strip() for o in raw.split(",") if o.strip()]


def allowed_hosts() -> list[str]:
    """Optional Host-header allow-list (NIRIKSHAN_ALLOWED_HOSTS, comma separated)."""
    return [h.strip() for h in os.getenv("NIRIKSHAN_ALLOWED_HOSTS", "").split(",") if h.strip()]


def _int_env(name: str, problems: list[str], minimum: int = 0) -> None:
    raw = os.getenv(name)
    if raw in (None, ""):
        return
    try:
        if int(raw) < minimum:
            problems.append(f"{name} must be an integer >= {minimum} (got {raw!r})")
    except ValueError:
        problems.append(f"{name} must be an integer (got {raw!r})")


def _float_env(name: str, problems: list[str]) -> None:
    raw = os.getenv(name)
    if raw in (None, ""):
        return
    try:
        float(raw)
    except ValueError:
        problems.append(f"{name} must be a number (got {raw!r})")


def validate() -> list[str]:
    """Every configuration problem, as readable sentences (empty list = fine)."""
    p: list[str] = []
    for name, minimum in (
        ("NIRIKSHAN_DB_POOL_SIZE", 1),
        ("NIRIKSHAN_DB_MAX_OVERFLOW", 0),
        ("NIRIKSHAN_MAX_UPLOAD_BYTES", 1),
        ("NIRIKSHAN_LOGIN_ADDR_MAX_FAILURES", 1),
        ("NIRIKSHAN_LOGIN_USER_MAX_FAILURES", 1),
    ):
        _int_env(name, p, minimum)
    for name in (
        "NIRIKSHAN_DB_POOL_TIMEOUT_S",
        "NIRIKSHAN_SESSION_HOURS",
        "NIRIKSHAN_SESSION_IDLE_MINUTES",
    ):
        _float_env(name, p)
    if cookie_samesite() not in ("strict", "lax", "none"):
        p.append("NIRIKSHAN_COOKIE_SAMESITE must be strict, lax or none")
    if cookie_samesite() == "none" and not cookie_secure():
        p.append(
            "NIRIKSHAN_COOKIE_SAMESITE=none requires a secure cookie (NIRIKSHAN_COOKIE_SECURE=1)"
        )
    if os.getenv("NIRIKSHAN_LOG_FORMAT", "json") not in ("json", "text"):
        p.append("NIRIKSHAN_LOG_FORMAT must be json or text")
    if not production():
        return p
    # ---- production-only requirements -------------------------------------------------------
    if dev_header_auth_enabled():
        p.append(
            "NIRIKSHAN_DEV_HEADER_AUTH is enabled together with NIRIKSHAN_PRODUCTION: that mode is "
            "an unauthenticated attestation and must never run in production"
        )
    if not os.getenv("DATABASE_URL"):
        p.append("DATABASE_URL must be set explicitly in production")
    if not os.getenv("NIRIKSHAN_DATA_DIR"):
        p.append("NIRIKSHAN_DATA_DIR must be set explicitly in production")
    if not os.getenv("NIRIKSHAN_KEY_DIR"):
        p.append("NIRIKSHAN_KEY_DIR must be set explicitly in production (a persistent volume)")
    elif Path(data_dir()) in [key_dir(), *key_dir().parents] or key_dir().is_relative_to(
        data_dir()
    ):
        p.append("NIRIKSHAN_KEY_DIR must be outside NIRIKSHAN_DATA_DIR")
    if not evidence_roots():
        p.append("NIRIKSHAN_EVIDENCE_ROOTS must name at least one folder in production")
    origins = cors_origins()
    if not origins:
        p.append("CORS_ORIGINS must list the frontend origin(s) in production (comma separated)")
    if any(o == "*" or "localhost" in o or "127.0.0.1" in o for o in origins):
        p.append("CORS_ORIGINS must not contain '*' or a localhost origin in production")
    if not cookie_secure():
        p.append("NIRIKSHAN_COOKIE_SECURE must not be disabled in production")
    return p


def check_or_exit() -> None:
    """Called once at startup. A bad configuration stops the process before it serves anything."""
    problems = validate()
    if problems:
        raise SystemExit(
            "Nirikshan refuses to start: invalid configuration\n  - " + "\n  - ".join(problems)
        )
