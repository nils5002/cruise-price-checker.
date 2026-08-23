"""Test bootstrap.

Environment variables are set *before* the application modules are imported so
the settings singleton points at a temporary data dir and SQLite file, and all
politeness delays are zero.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TMP_DIR = tempfile.mkdtemp(prefix="cpc-tests-")

os.environ.update(
    {
        "ENV_FILE": os.path.join(TMP_DIR, "nonexistent.env"),
        "DATA_DIR": TMP_DIR,
        "DATABASE_URL": f"sqlite:///{os.path.join(TMP_DIR, 'test.db')}",
        "ENABLE_SCHEDULER": "false",
        "ENABLE_MOCK_PROVIDER": "true",
        "HEADLESS": "true",
        "MIN_DELAY_BETWEEN_STEPS_MS": "0",
        "MAX_DELAY_BETWEEN_STEPS_MS": "0",
        "DELAY_BETWEEN_PROFILES_S": "0",
        "RETRY_BACKOFF_BASE_S": "0",
        "MAX_SCANS_PER_CRUISE_PER_DAY": "50",
        "LOG_LEVEL": "WARNING",
        "PROXY_DE_1": "http://proxyuser:proxysecret@203.0.113.10:3128",
        "PROXY_DE_1_LABEL": "DE Testanschluss",
    }
)

from app.db import Base, engine, init_db  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)
    shutil.rmtree(TMP_DIR, ignore_errors=True)


@pytest.fixture()
def db():
    from app.db import session_scope

    session = session_scope()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def mock_url():
    return "mock://cruise/test-1?variant=default&adults=2"
