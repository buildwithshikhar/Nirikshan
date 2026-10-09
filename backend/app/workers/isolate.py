"""Run one compute task (parse/carve plan, analytics) in a separate, restricted Python process.

What the isolation is (and is not) - see docs/workers.md for the measured platform table:
- a fresh interpreter (`python -E -s -B -m app.workers.entry`): no inherited Python state, no
  PYTHON* variables, no user site-packages, no bytecode writes;
- a scrubbed environment: only PATH, LANG/LC_ALL, a throw-away HOME/TMPDIR and the explicitly
  forwarded NIRIKSHAN_MODELS_DIR. No DATABASE_URL, no key passphrase, no proxy variables: the
  worker has no database credentials and cannot sign custody entries; the parent validates and
  persists its JSON result;
- resource limits the worker applies to itself before reading its input: RLIMIT_CPU, RLIMIT_AS
  (Linux only; macOS does not enforce it, so there the parent samples the worker's RSS and kills
  it above the limit), RLIMIT_FSIZE=0 (no file writes; pipes are unaffected), RLIMIT_CORE=0 (no
  core dumps of evidence bytes);
- a wall-clock timeout enforced by the parent (SIGKILL of the worker's process group);
- network: BEST-EFFORT only. The worker replaces socket creation/resolution with functions that
  raise before any task code runs, and the task code opens no sockets. This is an in-process
  guard: native code or a child process (ffmpeg, used by analytics) is not covered, and there is
  no OS network namespace/seccomp/sandbox profile. Deploy on an offline host for a real guarantee.
- same user id as the server: the worker CAN read files the server can read (e.g. the signing
  key file). Isolation here limits damage from a crash, hang, memory blow-up or accidental
  network use in parser/carver/analytics code; it is not a security boundary against code
  execution by a malicious input.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MAX_RESULT_BYTES = 512 * 1024 * 1024
STDERR_TAIL = 4000


class WorkerError(RuntimeError):
    """The task raised inside the worker (message is the worker's error)."""


class WorkerCrashed(RuntimeError):
    """The worker died (signal, limit, non-zero exit) without a result."""


class WorkerTimeout(RuntimeError):
    pass


class WorkerCancelled(RuntimeError):
    pass


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, "") or default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Limits:
    timeout_s: int
    cpu_s: int
    mem_mb: int

    @classmethod
    def from_env(cls, kind: str = "") -> Limits:
        timeout = _env_int("NIRIKSHAN_WORKER_TIMEOUT_S", 3600)
        return cls(
            timeout_s=timeout,
            cpu_s=_env_int("NIRIKSHAN_WORKER_CPU_S", timeout),
            mem_mb=_env_int("NIRIKSHAN_WORKER_MEM_MB", 4096, 64),
        )


def isolation_enabled() -> bool:
    return os.getenv("NIRIKSHAN_ISOLATE_JOBS", "1").strip().lower() not in ("0", "false", "no")


def worker_env(home: str, limits: Limits) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": home,
        "TMPDIR": home,
        "PYTHONHASHSEED": "0",
        "OMP_NUM_THREADS": os.environ.get("NIRIKSHAN_WORKER_THREADS", "2"),
        "NIRIKSHAN_WORKER_LIMITS": json.dumps(
            {"cpu_s": limits.cpu_s, "mem_mb": limits.mem_mb}, sort_keys=True
        ),
    }
    if os.getenv("NIRIKSHAN_MODELS_DIR"):
        env["NIRIKSHAN_MODELS_DIR"] = os.environ["NIRIKSHAN_MODELS_DIR"]
    return env


def _reader(stream, q: queue.Queue) -> None:
    total = 0
    try:
        for line in stream:
            total += len(line)
            if total > MAX_RESULT_BYTES:
                q.put(("X", "worker output exceeded the result size limit"))
                return
            q.put(("L", line))
    finally:
        q.put(("EOF", None))


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def run_task(
    task: str,
    payload: dict,
    *,
    limits: Limits | None = None,
    on_progress: Callable[[str, float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    poll_s: float = 0.1,
) -> dict:
    """Run `task` (a name from app.workers.tasks.TASKS) and return its JSON result. Raises
    WorkerError / WorkerCrashed / WorkerTimeout / WorkerCancelled; the worker is always dead
    when this returns or raises."""
    limits = limits or Limits.from_env()
    with tempfile.TemporaryDirectory(prefix="nrk-worker-") as home:
        err_path = Path(home) / "stderr.txt"
        with open(err_path, "w+b") as err:
            proc = subprocess.Popen(
                [sys.executable, "-E", "-s", "-B", "-m", "app.workers.entry", task],
                cwd=str(BACKEND_ROOT),
                env=worker_env(home, limits),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=err,
                start_new_session=True,
                close_fds=True,
            )
            try:
                return _drive(proc, payload, limits, on_progress, should_cancel, poll_s, err)
            finally:
                if proc.poll() is None:
                    _kill(proc)
                proc.wait()


def _stderr_tail(err) -> str:
    try:
        err.flush()
        err.seek(0)
        data = err.read()
        return data[-STDERR_TAIL:].decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _drive(proc, payload, limits, on_progress, should_cancel, poll_s, err) -> dict:
    try:
        proc.stdin.write(json.dumps(payload).encode())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()
    deadline = time.monotonic() + limits.timeout_s
    result: dict | None = None
    error: str | None = None
    next_rss = 0.0
    while True:
        if should_cancel is not None and should_cancel():
            _kill(proc)
            raise WorkerCancelled("cancelled while the worker was running")
        now = time.monotonic()
        if now > deadline:
            _kill(proc)
            raise WorkerTimeout(f"worker exceeded the wall-clock limit of {limits.timeout_s} s")
        if RSS_WATCHDOG and now >= next_rss:
            next_rss = now + RSS_INTERVAL_S
            rss = rss_mb(proc.pid)
            if rss is not None and rss > limits.mem_mb:
                _kill(proc)
                raise WorkerCrashed(
                    f"worker exceeded the memory limit ({rss} MiB > {limits.mem_mb} MiB, "
                    "sampled watchdog)"
                )
        try:
            kind, item = q.get(timeout=poll_s)
        except queue.Empty:
            continue
        if kind == "EOF":
            break
        if kind == "X":
            _kill(proc)
            raise WorkerCrashed(item)
        tag, _, rest = item.decode("utf-8", "replace").rstrip("\n").partition("\t")
        if tag == "P" and on_progress is not None:
            frac, _, stage = rest.partition("\t")
            try:
                on_progress(stage[:200], float(frac))
            except ValueError:
                pass
        elif tag == "R":
            result = json.loads(rest)
        elif tag == "E":
            error = json.loads(rest).get("error", "worker error")
    code = proc.wait(timeout=max(1.0, deadline - time.monotonic()))
    if error is not None:
        raise WorkerError(error)
    if result is not None and code == 0:
        return result
    why = describe_exit(code)
    tail = _stderr_tail(err)
    raise WorkerCrashed(f"worker {why} without a result" + (f": {tail[-500:]}" if tail else ""))


# RLIMIT_AS is not enforced on macOS, so there the parent samples the worker's memory once per
# RSS_INTERVAL_S and kills it above the limit (a short spike between samples can pass). On macOS
# the sample is the physical footprint (proc_pid_rusage: resident + compressed + swapped, what
# Activity Monitor shows), so swapping does not hide usage; elsewhere `ps -o rss`.
RSS_WATCHDOG = not sys.platform.startswith("linux")
RSS_INTERVAL_S = 0.5


class _RusageV0(ctypes.Structure):
    _fields_ = [
        ("uuid", ctypes.c_uint8 * 16),
        ("user_time", ctypes.c_uint64),
        ("system_time", ctypes.c_uint64),
        ("pkg_idle_wkups", ctypes.c_uint64),
        ("interrupt_wkups", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("wired_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("phys_footprint", ctypes.c_uint64),
        ("proc_start_abstime", ctypes.c_uint64),
        ("proc_exit_abstime", ctypes.c_uint64),
    ]


def _darwin_footprint_mb(pid: int) -> int | None:
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        info = _RusageV0()
        if lib.proc_pid_rusage(ctypes.c_int(pid), ctypes.c_int(0), ctypes.byref(info)) != 0:
            return None
        return int(info.phys_footprint) // (1024 * 1024)
    except (OSError, AttributeError):
        return None


def rss_mb(pid: int) -> int | None:
    if sys.platform == "darwin":
        mb = _darwin_footprint_mb(pid)
        if mb is not None:
            return mb
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        )
        return int(out.stdout.strip()) // 1024 if out.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def describe_exit(code: int | None) -> str:
    if code is None:
        return "did not exit"
    if code < 0:
        try:
            name = signal.Signals(-code).name
        except ValueError:
            name = str(-code)
        hint = {
            "SIGXCPU": " (CPU time limit)",
            "SIGKILL": " (killed: memory, timeout or operator)",
            "SIGSEGV": " (crash)",
            "SIGXFSZ": " (file-size limit)",
        }.get(name, "")
        return f"was terminated by {name}{hint}"
    return f"exited with status {code}"
