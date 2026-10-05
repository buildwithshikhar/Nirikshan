"""Command line helpers. Usage: python -m app.cli head <case_id> [--json]"""

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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nirikshan")
    sub = p.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("head", help="verify a case's custody chain and print its head_hash")
    h.add_argument("case_id", type=int)
    h.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    return head(args.case_id, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
