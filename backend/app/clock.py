"""UTC clock and best-effort NTP sync detection (reported as 'unknown' when not detectable)."""

import shutil
import subprocess
import time
from datetime import datetime, timezone

_cache: tuple[float, str] | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def ntp_status() -> str:
    """'synchronized' | 'not_synchronized' | 'unknown'. Only systemd's timedatectl is consulted."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < 30:
        return _cache[1]
    status = "unknown"
    if shutil.which("timedatectl"):
        try:
            out = subprocess.run(
                ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout.strip()
            status = {"yes": "synchronized", "no": "not_synchronized"}.get(out, "unknown")
        except (OSError, subprocess.SubprocessError):
            pass
    _cache = (time.monotonic(), status)
    return status
