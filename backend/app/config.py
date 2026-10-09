"""Runtime paths. Read from the environment on every call so tests can redirect them."""

import os
from pathlib import Path


def data_dir() -> Path:
    """Case workspaces (acquired images, derived data). Never holds signing keys."""
    return Path(os.getenv("NIRIKSHAN_DATA_DIR", "./data")).expanduser().resolve()


def key_dir() -> Path:
    """Custody signing key location. Must be outside data_dir()."""
    default = Path.home() / ".nirikshan" / "keys"
    return Path(os.getenv("NIRIKSHAN_KEY_DIR", str(default))).expanduser().resolve()


def evidence_roots() -> list[Path]:
    """Folders acquisition sources must live under (os.pathsep-separated). Empty = deny all."""
    raw = os.getenv("NIRIKSHAN_EVIDENCE_ROOTS", "")
    return [Path(r).expanduser().resolve() for r in raw.split(os.pathsep) if r.strip()]


def allow_block_devices() -> bool:
    """Block devices are refused unless explicitly enabled (never on a public instance)."""
    if public_instance():
        return False
    return os.getenv("NIRIKSHAN_ALLOW_BLOCK_DEVICES", "").lower() in ("1", "true", "yes")


def _flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes")


def public_instance() -> bool:
    """A public (internet-facing) instance: reference data only. Disables browser uploads and
    block-device acquisition regardless of their own settings."""
    return _flag("NIRIKSHAN_PUBLIC_INSTANCE")


def max_upload_bytes() -> int:
    """Largest browser upload accepted (default 2 GiB)."""
    return int(os.getenv("NIRIKSHAN_MAX_UPLOAD_BYTES", str(2 * 1024**3)))


def incoming_dir() -> Path | None:
    """Locked folder that browser uploads stream into. Always inside an evidence root so that the
    acquisition policy accepts it; None when no evidence root is configured."""
    roots = evidence_roots()
    if not roots:
        return None
    raw = os.getenv("NIRIKSHAN_INCOMING_DIR")
    path = Path(raw).expanduser().resolve() if raw else roots[0] / "incoming"
    return path if any(path.is_relative_to(r) for r in roots) else None
