"""Command line helpers.

python -m app.cli head <case_id> [--json]   verify a custody chain and print its head_hash
python -m app.cli reset-db --yes             DEV ONLY: drop and recreate the database schema
"""

import argparse
import json
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nirikshan")
    sub = p.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("head", help="verify a case's custody chain and print its head_hash")
    h.add_argument("case_id", type=int)
    h.add_argument("--json", action="store_true")
    r = sub.add_parser("reset-db", help="DEV ONLY: drop and recreate the schema")
    r.add_argument("--yes", action="store_true", help="confirm the destructive reset")
    args = p.parse_args(argv)
    if args.cmd == "reset-db":
        return reset_db(args.yes)
    return head(args.case_id, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
