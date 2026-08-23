"""Database engine/session handling.

SQLite is the zero-config default; setting ``DATABASE_URL`` to a Postgres DSN
switches the whole application over without further code changes.
"""
from __future__ import annotations

import os
import time
from typing import Generator, Optional
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, event, text
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


def sanitized_database_url() -> str:
    """DSN ohne Passwort -- damit die Logs die Konfiguration zeigen duerfen."""
    try:
        parts = urlsplit(settings.database_url)
    except ValueError:
        return "<nicht parsebar>"
    if not parts.netloc or "@" not in parts.netloc:
        return settings.database_url
    credentials, host = parts.netloc.rsplit("@", 1)
    user = credentials.split(":", 1)[0]
    return urlunsplit((parts.scheme, f"{user}:***@{host}", parts.path, "", ""))


def wait_for_database(timeout_s: float = 90.0, interval_s: float = 3.0) -> None:
    """Auf die Datenbank warten, statt beim Start sofort abzubrechen.

    In Compose-Umgebungen ist Postgres kurz nach dem Start noch nicht bereit.
    Ohne dieses Warten wuerde uvicorn beenden und der Container als
    "unhealthy" gelten -- mit einer wenig aussagekraeftigen Meldung.
    """
    deadline = time.monotonic() + timeout_s
    attempt = 0
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        attempt += 1
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            if attempt > 1:
                logger.info("Datenbank erreichbar (Versuch %s).", attempt)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "Datenbank (%s) noch nicht erreichbar, neuer Versuch in %.0fs: %s",
                sanitized_database_url(),
                interval_s,
                type(exc).__name__,
            )
            time.sleep(interval_s)
    raise RuntimeError(
        "Datenbank ist nach "
        f"{timeout_s:.0f}s nicht erreichbar ({sanitized_database_url()}). "
        "Haeufigste Ursache: POSTGRES_PASSWORD und das Passwort in DATABASE_URL "
        "stimmen nicht ueberein. Details: "
        f"{type(last_error).__name__}: {last_error}"
    )


def init_db() -> None:
    """Create tables and the data directories."""
    from app import models  # noqa: F401  (register mappers)

    for directory in (
        settings.data_dir,
        settings.screenshot_dir,
        settings.snapshot_dir,
        settings.profile_state_dir,
    ):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Datenverzeichnis '{directory}' kann nicht angelegt werden ({exc.strerror}). "
                "Rechte des Volumes pruefen (im Container gehoert /data dem Benutzer pwuser)."
            ) from exc

    logger.info("Verbinde mit Datenbank: %s", sanitized_database_url())
    wait_for_database()
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
