import os

# Tests use in-memory SQLite unless TEST_DATABASE_URL points at e.g. the compose Postgres.
TEST_DB = os.getenv("TEST_DATABASE_URL", "sqlite://")
os.environ["DATABASE_URL"] = TEST_DB  # must be set before the app is imported

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    if TEST_DB.startswith("sqlite"):
        db.engine.dispose()
        db.engine.pool = StaticPool(
            creator=lambda: __import__("sqlite3").connect(":memory:", check_same_thread=False)
        )
    db.Base.metadata.drop_all(db.engine)  # clean slate (Postgres persists between tests)
    with TestClient(app) as c:  # runs lifespan -> create_all
        yield c
    db.Base.metadata.drop_all(db.engine)
