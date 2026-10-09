"""Regenerate tests/fixtures/custody_signature_fixture.json (run ONLY to rebuild the fixture).

The fixture was first generated with cryptography 46.0.7, BEFORE the dependency upgrade, so the
test in test_signature_compat.py proves signatures made by the old library still verify with the
new one. The key below is a fixed TEST key derived from a public constant: it protects nothing.

    cd backend && .venv/bin/python tests/make_custody_fixture.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

SEED = bytes(range(32))  # public test constant, not a secret
OUT = Path(__file__).with_name("fixtures") / "custody_signature_fixture.json"


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    os.environ.update(
        DATABASE_URL=f"sqlite:///{tmp / 'f.db'}",
        NIRIKSHAN_DATA_DIR=str(tmp / "data"),
        NIRIKSHAN_KEY_DIR=str(tmp / "keys"),
    )
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import cryptography
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from sqlalchemy import select

    from app import custody, schema, signing
    from app.db import SessionLocal, engine
    from app.models import Case, CustodyEntry

    key = Ed25519PrivateKey.from_private_bytes(SEED)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    (tmp / "keys").mkdir(mode=0o700)
    kp = tmp / "keys" / signing.KEY_FILE
    kp.write_bytes(pem)
    kp.chmod(0o600)
    schema.check_and_init(engine)
    with SessionLocal() as db:
        db.add(Case(id=1, case_number="FIXTURE-1", title="signature fixture", examiner="fixture"))
        db.commit()
        for i, action in enumerate(("case_created", "evidence_acquired", "evidence_verified")):
            custody.append_entry(db, 1, action, "fixture", {"i": i, "note": "stored fixture"})
        rows = db.scalars(select(CustodyEntry).order_by(CustodyEntry.seq)).all()
        entries = [
            {c.name: getattr(r, c.name) for c in CustodyEntry.__table__.columns if c.name != "id"}
            for r in rows
        ]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "generated_with": f"cryptography {cryptography.__version__}",
                "note": "TEST key from a public constant; protects nothing.",
                "private_key_pem": pem.decode(),
                "public_key_hex": signing.public_key_hex(),
                "key_id": signing.key_id(signing.public_key()),
                "entries": entries,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    print("wrote", OUT, "with cryptography", cryptography.__version__)


if __name__ == "__main__":
    main()
