"""One-command reference-test-data demo: `make demo` (full) or `make demo-data` (data only).

Full mode starts the backend (uvicorn) and the frontend dev server with a dedicated, gitignored
data directory (./demo-data: database, case workspaces, evidence images and a demo-only signing
key; ~/.nirikshan is never touched), builds the reference-data demo case through the HTTP API,
prints the URLs and waits. Ctrl-C stops everything. Everything shown is reference test data, not
captured from a physical DVR.

Data-only mode (--data-only) builds the demo case against an already running backend. That
backend must allow --evidence-dir through NIRIKSHAN_EVIDENCE_ROOTS.
"""

import argparse
import contextlib
import errno
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

from app import demo_data  # noqa: E402

BANNER = (
    "REFERENCE TEST DATA: built from published research and open-source format documentation, "
    "with known ground truth. Not captured from a physical DVR."
)


def free_port(preferred: int) -> int:
    """First port from `preferred` upward that is free on both IPv4 and IPv6 loopback (Vite
    listens on ::1, uvicorn on 127.0.0.1; probing one family hides a listener on the other)."""

    def free(port: int) -> bool:
        for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            try:
                with socket.socket(family, socket.SOCK_STREAM) as s:
                    s.bind((host, port))
            except OSError as exc:
                if family == socket.AF_INET6 and exc.errno in (
                    errno.EADDRNOTAVAIL,
                    errno.EAFNOSUPPORT,
                ):
                    continue  # no IPv6 loopback on this host
                return False
        return True

    for port in range(preferred, preferred + 50):
        if free(port):
            return port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-dir", default=str(ROOT / "demo-data"), help="demo data directory")
    ap.add_argument("--api-port", type=int, default=8100)
    ap.add_argument("--web-port", type=int, default=5273)
    ap.add_argument("--keep", action="store_true", help="keep an existing demo data dir")
    ap.add_argument("--no-web", action="store_true", help="API only (no frontend dev server)")
    ap.add_argument("--exit-after-seed", action="store_true", help="stop after building the data")
    ap.add_argument("--data-only", action="store_true", help="only build data against --api-url")
    ap.add_argument("--api-url", default="http://localhost:8000", help="with --data-only")
    ap.add_argument(
        "--evidence-dir",
        default=None,
        help="where reference-data images are written (must be under the backend's evidence roots)",
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
    evdir = Path(args.evidence_dir).resolve() if args.evidence_dir else data / "evidence"
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
        # The demo UI/seeder still identify the examiner with the X-Examiner attestation header
        # (the login UI is Round D part 2). Dev-only, unauthenticated; never use for real cases.
        "NIRIKSHAN_DEV_HEADER_AUTH": "1",
        "PATH": f"/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}",
    }
    procs: list[subprocess.Popen] = []
    files = contextlib.ExitStack()
    try:
        print(f"Data dir {data} (demo-only database, workspaces and signing key)")
        logs = [files.enter_context((data / n).open("w")) for n in ("backend.log", "frontend.log")]
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
                raise SystemExit("frontend/node_modules missing: run `npm ci` in frontend/ first")
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
