"""Regression: N concurrent requests must not exhaust the database pool.

The audit middleware used to open a second session while each request's own session was still
open, so more concurrent requests than the pool size blocked for the pool timeout (30 s).
Needs a real server (the TestClient serialises requests), so it starts uvicorn on a free port.
"""

import concurrent.futures as cf
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PASSWORD = "demo-account-not-for-casework"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_twenty_parallel_logins_and_requests_do_not_exhaust_the_pool(tmp_path):
    port = _free_port()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'c.db'}",
        "NIRIKSHAN_DATA_DIR": str(tmp_path / "d"),
        "NIRIKSHAN_KEY_DIR": str(tmp_path / "k"),
        "NIRIKSHAN_DB_POOL_SIZE": "5",  # small on purpose: the old bug needed only > pool in flight
        "NIRIKSHAN_DB_MAX_OVERFLOW": "5",
        "NIRIKSHAN_DB_POOL_TIMEOUT_S": "10",
        "NIRIKSHAN_PASSWORD_SCRYPT_LOG2N": "12",
    }
    env.pop("NIRIKSHAN_DEV_HEADER_AUTH", None)
    backend = Path(__file__).resolve().parent.parent
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=backend,
        env=env,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/health", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        subprocess.run(
            [sys.executable, "-m", "app.demo_data", "seed-users"],
            cwd=backend, env=env, check=True, capture_output=True,
        )

        def one(_):
            req = urllib.request.Request(
                base + "/api/auth/login",
                data=json.dumps({"username": "demo-examiner", "password": PASSWORD}).encode(),
                headers={"Content-Type": "application/json"},
            )
            token = json.load(urllib.request.urlopen(req, timeout=30))["token"]
            for path in ("/api/auth/me", "/api/cases", "/api/system"):
                r = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"})
                assert urllib.request.urlopen(r, timeout=30).status == 200
            return True

        t0 = time.time()
        with cf.ThreadPoolExecutor(20) as ex:
            results = list(ex.map(one, range(20)))
        assert all(results)
        assert time.time() - t0 < 9, "requests queued behind the pool (pool exhaustion)"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
