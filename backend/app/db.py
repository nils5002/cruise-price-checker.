"""Database engine/session handling.

SQLite is the zero-config default; setting ``DATABASE_URL`` to a Postgres DSN
switches the whole application over without further code changes.
"""
from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


def _make_engine() -> Engine:
    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # Ensure the parent directory exists (e.g. /data).
        path = url.split("///")[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs.update({"pool_size": 5, "max_overflow": 10, "pool_recycle": 1800})
    return create_engine(url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):  # pragma: no cover
    if engine.url.get_backend_name() != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def init_db() -> None:
    """Create tables and the data directories."""
    from app import models  # noqa: F401  (register mappers)

    for directory in (
        settings.data_dir,
        settings.screenshot_dir,
        settings.snapshot_dir,
        settings.profile_state_dir,
    ):
        os.makedirs(directory, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    logger.info("Datenbank initialisiert (%s)", engine.url.get_backend_name())


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session_scope() -> Session:
    """Session for background workers (caller must close)."""
    return SessionLocal()
