import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./nirikshan.db")
    # Hosted providers often hand out postgres:// or postgresql:// URLs; use the psycopg3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


_url = database_url()
# Pool sizing is env-configurable (a request holds one connection for its duration; job threads
# hold more). Defaults are larger than SQLAlchemy's 5+10 and sized for the 40-thread request pool.
# In-memory SQLite (tests) uses a different pool class that takes no sizing arguments.
_pool_args = (
    {}
    if _url in ("sqlite://", "sqlite:///:memory:")
    else {
        "pool_size": int(os.getenv("NIRIKSHAN_DB_POOL_SIZE", "20")),
        "max_overflow": int(os.getenv("NIRIKSHAN_DB_MAX_OVERFLOW", "30")),
        "pool_timeout": float(os.getenv("NIRIKSHAN_DB_POOL_TIMEOUT_S", "30")),
    }
)
engine = create_engine(
    _url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {},
    **_pool_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
