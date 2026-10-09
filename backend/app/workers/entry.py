"""Worker process entry point: `python -E -s -B -m app.workers.entry <task>`.

Order matters: limits and the socket guard are installed BEFORE the payload is read and before
any task module is imported. Protocol on stdout, one line each: `P\\t<fraction>\\t<stage>`
(progress), then exactly one of `R\\t<json result>` or `E\\t<json {"error": ...}>`.
"""

from __future__ import annotations

import json
import os
import sys

APPLIED: dict[str, str] = {}


def _apply_limits() -> None:
    import resource
    import signal

    raw = os.environ.get("NIRIKSHAN_WORKER_LIMITS", "{}")
    lim = json.loads(raw)

    def setlim(name: str, which: int, soft: int, hard: int) -> None:
        try:
            resource.setrlimit(which, (soft, hard))
            APPLIED[name] = str(soft)
        except (ValueError, OSError) as exc:
            APPLIED[name] = f"not enforced ({type(exc).__name__})"

    cpu = int(lim.get("cpu_s", 3600))
    setlim("RLIMIT_CPU", resource.RLIMIT_CPU, cpu, cpu + 5)
    mem = int(lim.get("mem_mb", 4096)) * 1024 * 1024
    if sys.platform.startswith("linux"):
        setlim("RLIMIT_AS", resource.RLIMIT_AS, mem, mem)
    else:  # macOS accepts RLIMIT_AS calls inconsistently and does not enforce them
        APPLIED["RLIMIT_AS"] = "not enforced on this platform"
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)  # a write then fails with EFBIG, no kill
    setlim("RLIMIT_FSIZE", resource.RLIMIT_FSIZE, 0, 0)
    setlim("RLIMIT_CORE", resource.RLIMIT_CORE, 0, 0)


class NetworkDisabled(PermissionError):
    pass


def _guard_network() -> None:
    import socket

    def refuse(*_a, **_k):
        raise NetworkDisabled("network access is disabled in isolated workers")

    class _NoSocket(socket.socket):  # noqa: D401 - construction always refused
        def __init__(self, *a, **k):  # noqa: ARG002
            refuse()

    socket.socket = _NoSocket  # type: ignore[misc]
    for name in ("create_connection", "getaddrinfo", "gethostbyname", "socketpair", "fromfd"):
        if hasattr(socket, name):
            setattr(socket, name, refuse)
    APPLIED["network"] = "socket API disabled in-process (best effort)"


def emit(tag: str, text: str) -> None:
    sys.stdout.write(f"{tag}\t{text}\n")
    sys.stdout.flush()


def progress(stage: str, fraction: float) -> None:
    emit("P", f"{max(0.0, min(1.0, fraction)):.4f}\t{stage.replace(chr(9), ' ')[:200]}")


def _json_default(o):
    if hasattr(o, "item"):  # numpy scalar
        return o.item()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, bytes):
        return {"__bytes_hex__": o.hex()}
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def main(argv: list[str]) -> int:
    _apply_limits()
    _guard_network()
    task = argv[1] if len(argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        from app.workers.tasks import TASKS

        fn = TASKS.get(task)
        if fn is None:
            raise ValueError(f"unknown worker task {task!r}")
        result = fn(payload, progress)
        result = {"result": result, "limits_applied": dict(APPLIED), "pid": os.getpid()}
        emit("R", json.dumps(result, default=_json_default, separators=(",", ":")))
        return 0
    except BaseException as exc:  # noqa: BLE001 - reported to the parent, then exit non-zero
        emit("E", json.dumps({"error": f"{type(exc).__name__}: {exc}"[:4000]}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
