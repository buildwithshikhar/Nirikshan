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
    """Block devices are refused unless explicitly enabled."""
    return os.getenv("NIRIKSHAN_ALLOW_BLOCK_DEVICES", "").lower() in ("1", "true", "yes")
