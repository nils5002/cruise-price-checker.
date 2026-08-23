"""Startverhalten: App-Import, 204-Endpunkte, Warten auf die Datenbank.

Diese Tests sichern genau die Fehler ab, die den Container beim Deploy als
"unhealthy" markieren wuerden: ein Importfehler der App oder eine nicht
erreichbare Datenbank ohne verstaendliche Meldung.
"""
from __future__ import annotations

import pytest

from app import db as db_module
from app.main import create_app


def test_app_imports_and_registers_routes():
    """Faengt Inkompatibilitaeten mit den gepinnten Abhaengigkeiten ab."""
    app = create_app()
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/health" in paths
    assert "/api/meta" in paths
    assert "/api/cruises/{cruise_id}" in paths


def test_no_content_endpoints_have_no_response_body():
    """204-Routen duerfen kein Response-Model haben (sonst Assertion beim Import)."""
    app = create_app()
    for route in app.routes:
        status_code = getattr(route, "status_code", None)
        if status_code == 204:
            assert getattr(route, "response_model", None) is None, route.path


def test_health_needs_no_database(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_sanitized_dsn_hides_password(monkeypatch):
    monkeypatch.setattr(
        db_module.settings, "database_url", "postgresql+psycopg2://cruise:geheim@db:5432/cruise"
    )
    sanitized = db_module.sanitized_database_url()
    assert "geheim" not in sanitized
    assert "cruise:***@db:5432" in sanitized


def test_sanitized_dsn_handles_sqlite(monkeypatch):
    monkeypatch.setattr(db_module.settings, "database_url", "sqlite:////data/cruise.db")
    assert db_module.sanitized_database_url() == "sqlite:////data/cruise.db"


def test_wait_for_database_returns_when_reachable():
    # Die Test-Datenbank (SQLite) ist erreichbar -> kehrt sofort zurueck.
    db_module.wait_for_database(timeout_s=5, interval_s=0.1)


def test_wait_for_database_reports_cause(monkeypatch):
    """Nach dem Timeout muss die Meldung die haeufigste Ursache benennen."""

    def broken_connect():
        raise RuntimeError("FATAL: password authentication failed for user \"cruise\"")

    monkeypatch.setattr(db_module.engine, "connect", broken_connect)
    with pytest.raises(RuntimeError) as excinfo:
        db_module.wait_for_database(timeout_s=0.3, interval_s=0.1)
    message = str(excinfo.value)
    assert "nicht erreichbar" in message
    assert "POSTGRES_PASSWORD" in message
    assert "geheim" not in message


def test_wait_for_database_recovers_after_retry(monkeypatch):
    """Kurzzeitig nicht erreichbare Datenbank fuehrt nicht zum Abbruch."""
    calls = {"n": 0}
    original = db_module.engine.connect

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("connection refused")
        return original()

    monkeypatch.setattr(db_module.engine, "connect", flaky)
    db_module.wait_for_database(timeout_s=5, interval_s=0.05)
    assert calls["n"] >= 2
