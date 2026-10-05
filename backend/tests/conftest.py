import os

# Tests use in-memory SQLite unless TEST_DATABASE_URL points at e.g. the compose Postgres.
TEST_DB = os.getenv("TEST_DATABASE_URL", "sqlite://")
os.environ["DATABASE_URL"] = TEST_DB  # must be set before the app is imported

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    """Per-test workspace and signing-key dirs (key dir deliberately outside the data dir)."""
    monkeypatch.setenv("NIRIKSHAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NIRIKSHAN_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("NIRIKSHAN_EVIDENCE_ROOTS", str(tmp_path.resolve()))
    monkeypatch.delenv("NIRIKSHAN_ALLOW_BLOCK_DEVICES", raising=False)
    return tmp_path


EXAMINER = {"X-Examiner": "Insp. Test"}


@pytest.fixture
def client():
    if TEST_DB.startswith("sqlite"):
        db.engine.dispose()
        db.engine.pool = StaticPool(
            creator=lambda: __import__("sqlite3").connect(":memory:", check_same_thread=False)
        )
    db.Base.metadata.drop_all(db.engine)  # clean slate (Postgres persists between tests)
    with TestClient(app, headers=EXAMINER) as c:  # runs lifespan -> create_all
        yield c
    db.Base.metadata.drop_all(db.engine)


@pytest.fixture
def session(client):
    with db.SessionLocal() as s:
        yield s


@pytest.fixture
def image(tmp_path):
    """A small file-backed 'disk image' (synthetic bytes, not a real DVR)."""
    p = tmp_path / "src.dd"
    p.write_bytes(bytes(range(256)) * 4096 + b"tail")
    return p
