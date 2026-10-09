"""Command line helpers.

python -m app.cli head <case_id> [--json]   verify a custody chain and print its head_hash
python -m app.cli reset-db --yes             DEV ONLY: drop and recreate the database schema
python -m app.cli create-admin <username>    create the FIRST admin (password prompted twice)
python -m app.cli verify-package <file>      verify an evidence package offline (no database)
python -m app.cli protect-key [--key ...]    passphrase-protect a plaintext signing key
python -m app.cli key-status                 show whether each signing key is protected
"""

import argparse
import getpass
import json
import os
import sys

from app import custody
from app.db import SessionLocal
from app.models import Case


def head(case_id: int, as_json: bool) -> int:
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        if case is None:
            print(f"case {case_id} not found", file=sys.stderr)
            return 2
        res = custody.verify_chain(db, case_id)
    if as_json:
        print(json.dumps({"case_id": case_id, "case_number": case.case_number, **res}))
    else:
        print(f"case:        {case.case_number} (id {case_id})")
        print(f"entries:     {res['entries']}")
        print(f"key_id:      {res['key_id']}")
        print(f"chain:       {'VALID' if res['ok'] else 'INVALID'}")
        for f in res["failures"]:
            print(f"  entry {f['seq']}: {f['reason']}")
        print(f"head_hash:   {res['head_hash']}")
        print(
            "Record head_hash outside this system (paper log, email, report) to detect truncation."
        )
    return 0 if res["ok"] else 1


def reset_db(yes: bool) -> int:
    from sqlalchemy.engine import make_url

    from app import schema
    from app.db import engine

    target = make_url(str(engine.url)).render_as_string(hide_password=True)
    if not yes:
        print(
            f"Refusing to reset {target} without --yes. This DROPS every table (cases, evidence "
            "records, custody log, runs, clips). Case workspaces on disk are not deleted.",
            file=sys.stderr,
        )
        return 2
    schema.reset(engine)
    print(
        f"Reset {target} to schema version {schema.SCHEMA_VERSION}. "
        "Evidence images and clips already on disk were NOT removed."
    )
    return 0


def _prompt_new_password(label: str) -> str | None:
    pw = getpass.getpass(f"{label}: ")
    if pw != getpass.getpass(f"{label} (again): "):
        print("passwords do not match", file=sys.stderr)
        return None
    return pw


def create_admin(username: str, display_name: str) -> int:
    """Bootstrap only: refused once any active admin exists (use the API from then on). The
    password is always prompted (never an argument, never a default)."""
    from app import schema
    from app.auth.routes import active_admins, create_user
    from app.db import engine

    schema.check_and_init(engine)
    with SessionLocal() as db:
        if active_admins(db) > 0:
            print(
                "an active admin already exists; create further users through the API "
                "(POST /api/users) as that admin",
                file=sys.stderr,
            )
            return 2
        pw = _prompt_new_password(f"password for {username}")
        if pw is None:
            return 2
        try:
            u = create_user(db, username, display_name or username, "admin", pw, "cli:create-admin")
        except (ValueError, LookupError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
    print(f"created admin '{u.username}' (id {u.id}). Log in at POST /api/auth/login.")
    return 0


KEY_STEMS = {"custody": "custody_ed25519", "package": "package_ed25519"}


def _key_passphrase(confirm: bool) -> bytes | None:
    from app.keystore import env_passphrase

    pw = env_passphrase()
    if pw:
        return pw
    if not sys.stdin.isatty():
        print(
            "no passphrase: set NIRIKSHAN_KEY_PASSPHRASE_FILE or run interactively",
            file=sys.stderr,
        )
        return None
    if confirm:
        raw = _prompt_new_password("key passphrase")
    else:
        raw = getpass.getpass("key passphrase: ")
    return raw.encode() if raw else None


def protect_key(which: str) -> int:
    from app import keystore

    stems = list(KEY_STEMS.values()) if which == "all" else [KEY_STEMS[which]]
    todo = [s for s in stems if keystore.status(s)["state"] == "plaintext"]
    if not todo:
        print("no plaintext key to protect", file=sys.stderr)
        return 2
    pw = _key_passphrase(confirm=True)
    if not pw:
        return 2
    for stem in todo:
        try:
            path = keystore.protect(stem, pw)
        except keystore.KeyStoreError as exc:
            print(f"{stem}: {exc}", file=sys.stderr)
            return 1
        print(f"{stem}: protected -> {path}")
    print(
        "The plaintext PEM was unlinked; copies in backups or old disk blocks are not erased. "
        "Start the server with NIRIKSHAN_KEY_PASSPHRASE_FILE set."
    )
    return 0


def key_status() -> int:
    from app import keystore

    for stem in KEY_STEMS.values():
        st = keystore.status(stem)
        print(f"{st['key']:<18} {st['state']:<30} {st['dir']}")
    return 0


def verify_package_cmd(path: str, expect_key_id: str | None, as_json: bool) -> int:
    from app.package.verify import PackageError, verify_package

    passphrase: bytes | None = None
    env = os.getenv("NIRIKSHAN_PACKAGE_PASSPHRASE")
    if env:
        passphrase = env.encode()
    try:
        res = verify_package(
            path,
            passphrase=passphrase,
            ask_passphrase=(lambda: getpass.getpass("package passphrase: ").encode())
            if sys.stdin.isatty()
            else None,
            expect_key_id=expect_key_id,
        )
    except PackageError as exc:
        if as_json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"FAILED: {exc}")
        return 2
    if as_json:
        print(json.dumps(res, indent=2))
    else:
        for line in res["lines"]:
            print(line)
        print("RESULT: " + ("VERIFIED" if res["ok"] else "FAILED"))
    return 0 if res["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nirikshan")
    sub = p.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("head", help="verify a case's custody chain and print its head_hash")
    h.add_argument("case_id", type=int)
    h.add_argument("--json", action="store_true")
    r = sub.add_parser("reset-db", help="DEV ONLY: drop and recreate the schema")
    r.add_argument("--yes", action="store_true", help="confirm the destructive reset")
    a = sub.add_parser("create-admin", help="create the first admin account (prompts)")
    a.add_argument("username")
    a.add_argument("--display-name", default="")
    v = sub.add_parser("verify-package", help="verify an evidence package offline")
    v.add_argument("file")
    v.add_argument("--expect-key-id", default=None, help="key_id recorded outside the package")
    v.add_argument("--json", action="store_true")
    k = sub.add_parser("protect-key", help="passphrase-protect plaintext signing key(s)")
    k.add_argument("--key", choices=["custody", "package", "all"], default="all")
    sub.add_parser("key-status", help="show signing key protection state")
    args = p.parse_args(argv)
    if args.cmd == "reset-db":
        return reset_db(args.yes)
    if args.cmd == "create-admin":
        return create_admin(args.username, args.display_name)
    if args.cmd == "verify-package":
        return verify_package_cmd(args.file, args.expect_key_id, args.json)
    if args.cmd == "protect-key":
        return protect_key(args.key)
    if args.cmd == "key-status":
        return key_status()
    return head(args.case_id, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
