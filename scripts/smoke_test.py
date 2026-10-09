"""Post-deploy smoke test: python scripts/smoke_test.py --base-url https://host [--keep]

Needs an examiner or admin account: NIRIKSHAN_SMOKE_USERNAME / NIRIKSHAN_SMOKE_PASSWORD (or
--username and the password prompt). Checks /healthz, login, case list, creates a case named
SMOKE-<time>, generates a report for it, downloads it and compares the SHA-256, verifies the custody
chain, then logs out. The smoke case stays in the database (cases are never deleted: it is a record)
unless the instance is a throw-away one. Exit code 0 only if every step passed.
"""

import argparse
import getpass
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request


def call(base, method, path, token=None, body=None, raw=False):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = r.read()
            return (
                r.status,
                (payload if raw else (json.loads(payload) if payload else None)),
                r.headers,
            )
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace"), e.headers


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--username", default=os.getenv("NIRIKSHAN_SMOKE_USERNAME"))
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    password = os.getenv("NIRIKSHAN_SMOKE_PASSWORD") or getpass.getpass("password: ")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        print(
            f"{'PASS' if ok else 'FAIL'}  {name}{(' - ' + detail) if detail and not ok else ''}"
        )
        if not ok:
            failures.append(name)
        return ok

    s, body, _ = call(base, "GET", "/healthz")
    check(
        "healthz answers ok with the database up",
        s == 200 and body.get("database") == "ok",
        str(body),
    )
    s, body, _ = call(
        base,
        "POST",
        "/api/auth/login",
        body={"username": args.username, "password": password},
    )
    if not check("login", s == 200, str(body)):
        return 1
    token = body["token"]
    s, me, _ = call(base, "GET", "/api/auth/me", token)
    check(
        "session identifies the user",
        s == 200 and me["username"] == args.username,
        str(me),
    )
    s, cases, _ = call(base, "GET", "/api/cases", token)
    check("list cases", s == 200 and isinstance(cases, list), str(cases))
    s, case, _ = call(
        base,
        "POST",
        "/api/cases",
        token,
        {
            "case_number": f"SMOKE-{int(time.time())}",
            "title": "Deployment smoke test",
            "description": "created by scripts/smoke_test.py",
        },
    )
    if check("create case", s == 201, str(case)):
        cid = case["id"]
        s, rep, _ = call(base, "POST", f"/api/cases/{cid}/report", token)
        if check("generate report", s in (200, 201), str(rep)):
            s, pdf, _ = call(
                base, "GET", f"/api/reports/{rep['id']}/download", token, raw=True
            )
            check(
                "report downloads and its SHA-256 matches",
                s == 200 and hashlib.sha256(pdf).hexdigest() == rep["sha256"],
            )
        s, chain, _ = call(base, "GET", f"/api/cases/{cid}/custody/verify", token)
        check("custody chain verifies", s == 200 and chain["ok"], str(chain))
    s, _b, _ = call(base, "POST", "/api/auth/logout", token)
    check("logout", s == 200)
    s, _b, _ = call(base, "GET", "/api/cases", token)
    check("token is refused after logout", s == 401)
    print(
        f"\n{'SMOKE TEST PASSED' if not failures else 'SMOKE TEST FAILED: ' + ', '.join(failures)}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
