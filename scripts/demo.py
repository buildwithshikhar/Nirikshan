"""One-command SYNTHETIC demo: `make demo` (full) or `make demo-data` (data only).

Full mode starts the backend (uvicorn) and the frontend dev server with a dedicated, gitignored
data directory (./demo-data: database, case workspaces, evidence images and a demo-only signing
key; ~/.nirikshan is never touched), builds the SYNTHETIC demo case through the HTTP API, prints
the URLs and waits. Ctrl-C stops everything. Everything shown is SYNTHETIC test data.

Data-only mode (--data-only) builds the demo case against an already running backend. That
backend must allow --evidence-dir through NIRIKSHAN_EVIDENCE_ROOTS.
"""

import argparse
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import demo_data

BANNER = "SYNTHETIC DEMO: generated test images in per-paper vendor layouts, not real DVR data."


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise SystemExit("no free port")


def wait_http(url: str, timeout: float, proc: subprocess.Popen | None = None) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if proc is not None and proc.poll() is not None:
            raise SystemExit(
                f"process exited early (code {proc.returncode}) while waiting for {url}"
            )
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.3)
    raise SystemExit(f"timed out waiting for {url}")


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def print_urls(api_url: str, web_url: str | None, summary: dict) -> None:
    cid = summary.get("case_id")
    print("\n" + "=" * 78)
    print(BANNER)
    print(f"  API        {api_url}/docs")
    if web_url:
        print(f"  Web UI     {web_url}")
        if cid:
            print(f"  Demo case  {web_url}/cases/{cid}")
            print(f"  Timeline   {web_url}/cases/{cid}/timeline")
            print(f"  Custody    {web_url}/cases/{cid}/custody")
    for note in summary.get("skipped", []):
        print(f"  skipped    {note}")
    print("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument(
        "--data-dir", default=str(ROOT / "demo-data"), help="demo data directory"
    )
    ap.add_argument("--api-port", type=int, default=8100)
    ap.add_argument("--web-port", type=int, default=5273)
    ap.add_argument(
        "--keep", action="store_true", help="keep an existing demo data dir"
    )
    ap.add_argument(
        "--no-web", action="store_true", help="API only (no frontend dev server)"
    )
    ap.add_argument(
        "--exit-after-seed", action="store_true", help="stop after building the data"
    )
    ap.add_argument(
        "--data-only", action="store_true", help="only build data against --api-url"
    )
    ap.add_argument(
        "--api-url", default="http://localhost:8000", help="with --data-only"
    )
    ap.add_argument(
        "--evidence-dir",
        default=None,
        help="where SYNTHETIC images are written (must be under the backend's evidence roots)",
    )
    args = ap.parse_args()
    print(BANNER)

    if args.data_only:
        evdir = Path(args.evidence_dir or ROOT / "demo-data" / "evidence").resolve()
        status, _ = demo_data.UrlApi(args.api_url).call("GET", "/health")
        if status != 200:
            raise SystemExit(f"no backend answering at {args.api_url}")
        summary = demo_data.seed(demo_data.UrlApi(args.api_url), evdir)
        print_urls(args.api_url, None, summary)
        return 0

    data = Path(args.data_dir).resolve()
    if data.exists() and not args.keep:
        shutil.rmtree(data)
    evdir = (
        Path(args.evidence_dir).resolve() if args.evidence_dir else data / "evidence"
    )
    for sub in ("data", "keys", "evidence"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    api_port = free_port(args.api_port)
    web_port = free_port(args.web_port)
    api_url, web_url = f"http://localhost:{api_port}", f"http://localhost:{web_port}"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{data / 'demo.db'}",
        "NIRIKSHAN_DATA_DIR": str(data / "data"),
        "NIRIKSHAN_KEY_DIR": str(data / "keys"),  # demo-only key, never ~/.nirikshan
        "NIRIKSHAN_EVIDENCE_ROOTS": str(evdir),
        "CORS_ORIGINS": web_url,
        "PATH": f"/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}",
    }
    procs: list[subprocess.Popen] = []
    files = contextlib.ExitStack()
    try:
        print(f"Data dir {data} (demo-only database, workspaces and signing key)")
        logs = [
            files.enter_context((data / n).open("w"))
            for n in ("backend.log", "frontend.log")
        ]
        print(f"Server logs: {data / 'backend.log'}, {data / 'frontend.log'}")
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(api_port)],
            cwd=ROOT / "backend",
            env=env,
            start_new_session=True,
            stdout=logs[0],
            stderr=subprocess.STDOUT,
        )
        procs.append(backend)
        wait_http(f"{api_url}/health", 60, backend)
        web = None
        if not args.no_web:
            if not (ROOT / "frontend" / "node_modules").is_dir():
                raise SystemExit(
                    "frontend/node_modules missing: run `npm ci` in frontend/ first"
                )
            web = subprocess.Popen(
                ["npx", "vite", "--port", str(web_port), "--strictPort"],
                cwd=ROOT / "frontend",
                env={**env, "VITE_PROXY_TARGET": api_url},
                start_new_session=True,
                stdout=logs[1],
                stderr=subprocess.STDOUT,
            )
            procs.append(web)
            wait_http(web_url, 60, web)
        summary = demo_data.seed(demo_data.UrlApi(api_url), evdir)
        print_urls(api_url, None if args.no_web else web_url, summary)
        if args.exit_after_seed:
            return 0
        print("Press Ctrl-C to stop the demo.")
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        print("A demo process exited; stopping.")
        return 1
    except KeyboardInterrupt:
        print("\nStopping demo ...")
        return 0
    finally:
        for p in reversed(procs):
            stop(p)
        files.close()


if __name__ == "__main__":
    sys.exit(main())
