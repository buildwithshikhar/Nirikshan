"""Tasks a worker may run (whitelist: the task name selects a function here, nothing else).

analyze_plan  read-only identification, vendor parsing and generic carving of an evidence image;
              returns a JSON plan that the parent validates and persists (app.workers.plan).
analytics     motion / object / face detection over one exported clip; returns the detections.
selftest_*    diagnostics that exercise the isolation itself (python -m app.cli worker-selftest
              and tests/test_workers_isolation.py); they touch no evidence.
"""

from __future__ import annotations

import hashlib
import os
import socket
import time
from dataclasses import asdict


def _sha256(f, size: int, progress) -> str:
    h = hashlib.sha256()
    f.seek(0)
    done = 0
    while chunk := f.read(4 << 20):
        h.update(chunk)
        done += len(chunk)
        progress("Worker: re-hashing the image", 0.25 * done / max(1, size))
    return h.hexdigest()


def analyze_plan(p: dict, progress) -> dict:
    from app.analyze import _dry_generic, _match_dict
    from app.carving.carve import CarveParams
    from app.carving.carve import Clip as CarvedClip
    from app.carving.ranges import carve_ranges, merge_spans, uncovered
    from app.vendors import default_registry

    size = int(p["size"])
    params = CarveParams(**p["params"])
    timings: dict[str, float] = {}
    with open(p["image_path"], "rb") as f:
        t0 = time.perf_counter()
        sha = _sha256(f, size, progress)
        timings["worker_hash"] = time.perf_counter() - t0
        if sha != p["expected_sha256"]:
            raise RuntimeError(
                f"image SHA-256 in the worker ({sha}) differs from the recorded value; refusing"
            )

        def read_at(off: int, n: int) -> bytes:
            f.seek(off)
            return f.read(n)

        registry = default_registry()
        progress("Worker: identifying vendor", 0.30)
        t0 = time.perf_counter()
        matches = registry.identify(f, size)
        timings["identify"] = time.perf_counter() - t0
        progress("Worker: running vendor parsers", 0.40)
        t0 = time.perf_counter()
        parsed = []
        for m in matches:
            parser = registry.parser_for(m.vendor)
            opts = (p.get("parser_options") or {}).get(m.vendor)
            res = parser.parse(f, size, opts) if parser else None
            parsed.append(asdict(res) if res is not None else None)
        timings["parse"] = time.perf_counter() - t0
        spans = [
            (c["extents"][0][0], c["extents"][-1][1])
            for r in parsed
            if r is not None
            for c in r["clips"]
        ]
        covered = merge_spans(spans)
        ranges = uncovered(covered, size) if p["generic_scope"] == "uncovered" else [(0, size)]
        progress("Worker: generic carving", 0.55)
        t0 = time.perf_counter()
        generic = []
        for item in carve_ranges(f, ranges, params):
            kind = "clip" if isinstance(item, CarvedClip) else "orphan"
            generic.append({"type": kind, **asdict(item)})
        timings["carve"] = time.perf_counter() - t0
        full = []
        if any(r is not None for r in parsed):
            progress("Worker: independent generic pass for the cross-check", 0.85)
            t0 = time.perf_counter()
            full = [asdict(c) for c in _dry_generic(f, size, read_at, params)]
            timings["crosscheck_pass"] = time.perf_counter() - t0
    progress("Worker: plan complete", 1.0)
    return {
        "sha256": sha,
        "size": size,
        "matches": [_match_dict(m) for m in matches],
        "parsed": parsed,
        "ranges": [list(r) for r in ranges],
        "generic": generic,
        "full_generic": full,
        "timings": {k: round(v, 6) for k, v in timings.items()},
    }


def analytics(p: dict, progress) -> dict:
    from app.analytics import detect, motion
    from app.analytics.runner import parse_params

    with open(p["mp4_path"], "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    if p.get("expected_sha256") and sha != p["expected_sha256"]:
        raise RuntimeError("exported MP4 changed since it was recorded; refusing to analyse")
    params = parse_params(p["kind"], p.get("params") or {})
    progress(f"Worker: {p['kind']} analytics", 0.1)
    t0 = time.perf_counter()
    if p["kind"] == "motion":
        res = motion.analyse_motion(p["mp4_path"], params)
    else:
        res = detect.analyse_detections(p["mp4_path"], p["kind"], params)
    res.pop("samples", None)  # per-frame samples are not persisted; keep the result small
    progress("Worker: analytics complete", 1.0)
    return {"res": res, "seconds": round(time.perf_counter() - t0, 6), "mp4_sha256": sha}


# ---- diagnostics (no evidence) ------------------------------------------------------------
def selftest_echo(p: dict, progress) -> dict:
    progress("echo", 0.5)
    return {"echo": p.get("value"), "env_keys": sorted(os.environ)}


def selftest_sleep(p: dict, progress) -> dict:
    end = time.monotonic() + float(p.get("seconds", 5))
    while time.monotonic() < end:
        progress("sleeping", 0.5)
        time.sleep(0.05)
    return {"slept": True}


def selftest_crash(p: dict, progress) -> dict:
    os._exit(int(p.get("code", 9)))


def selftest_raise(p: dict, progress) -> dict:
    raise ValueError(p.get("message", "deliberate failure"))


def selftest_socket(p: dict, progress) -> dict:
    out = {}
    for name, fn in (
        ("socket", lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM)),
        ("create_connection", lambda: socket.create_connection(("127.0.0.1", 9), timeout=1)),
        ("getaddrinfo", lambda: socket.getaddrinfo("localhost", 80)),
    ):
        try:
            fn()
            out[name] = "ALLOWED"
        except PermissionError as exc:
            out[name] = f"refused: {exc}"
        except OSError as exc:
            out[name] = f"ALLOWED (then failed: {exc})"
    return out


def selftest_write(p: dict, progress) -> dict:
    target = os.path.join(os.environ.get("TMPDIR", "/tmp"), "nrk-selftest-write")
    try:
        with open(target, "wb") as f:
            f.write(b"x" * 4096)
            f.flush()
        return {"write": "ALLOWED"}
    except OSError as exc:
        return {"write": f"refused: {exc.strerror or exc}"}


def selftest_cpu(p: dict, progress) -> dict:
    x = 0
    while True:  # spins until RLIMIT_CPU (SIGXCPU) or the wall-clock timeout
        x += 1


def selftest_alloc(p: dict, progress) -> dict:
    blocks = []
    try:
        for _ in range(int(p.get("mb", 8192))):
            blocks.append(os.urandom(1024 * 1024))  # incompressible, touched: counted in RSS
        time.sleep(float(p.get("hold", 0)))
        return {"alloc": "ALLOWED", "mb": len(blocks)}
    except MemoryError:
        return {"alloc": "refused (MemoryError)", "mb": len(blocks)}


TASKS = {
    "analyze_plan": analyze_plan,
    "analytics": analytics,
    "selftest_echo": selftest_echo,
    "selftest_sleep": selftest_sleep,
    "selftest_crash": selftest_crash,
    "selftest_raise": selftest_raise,
    "selftest_socket": selftest_socket,
    "selftest_write": selftest_write,
    "selftest_cpu": selftest_cpu,
    "selftest_alloc": selftest_alloc,
}
