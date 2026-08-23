"""Scheduler intervals and due-date logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Cruise
from app.scheduler.service import INTERVAL_HOURS, due_cruises, scheduler_status
from app.services import url_hash


def _cruise(db, suffix, interval, next_check):
    cruise = Cruise(
        provider="mock",
        url=f"mock://cruise/{suffix}",
        url_hash=url_hash(f"mock://cruise/sched-{suffix}"),
        schedule_interval=interval,
        next_check_at=next_check,
        monitoring_enabled=True,
    )
    db.add(cruise)
    db.commit()
    return cruise


def test_supported_intervals():
    assert set(INTERVAL_HOURS) == {"6h", "12h", "daily"}
    assert scheduler_status()["supported_intervals"] == ["manual", "6h", "12h", "daily"]


def test_due_selection(db):
    now = datetime.now(timezone.utc)
    overdue = _cruise(db, "sched-due", "6h", now - timedelta(hours=1))
    future = _cruise(db, "sched-future", "6h", now + timedelta(hours=5))
    manual = _cruise(db, "sched-manual", "manual", None)
    fresh = _cruise(db, "sched-fresh", "daily", None)

    due_ids = {c.id for c in due_cruises(now)}
    assert overdue.id in due_ids
    assert fresh.id in due_ids       # never checked -> due
    assert future.id not in due_ids
    assert manual.id not in due_ids  # manual is never scheduled


def test_disabled_monitoring_is_skipped(db):
    now = datetime.now(timezone.utc)
    cruise = _cruise(db, "sched-off", "6h", now - timedelta(hours=2))
    cruise.monitoring_enabled = False
    db.commit()
    assert cruise.id not in {c.id for c in due_cruises(now)}


def test_next_check_is_set_after_a_scan(db):
    from app.scanner.runner import _update_schedule

    cruise = _cruise(db, "sched-next", "12h", None)
    _update_schedule(cruise)
    assert cruise.next_check_at is not None
    delta = cruise.next_check_at - datetime.now(timezone.utc)
    assert timedelta(hours=11) < delta < timedelta(hours=13)

    cruise.schedule_interval = "manual"
    _update_schedule(cruise)
    assert cruise.next_check_at is None


def test_timezone_is_resolved():
    """Zeitzone muss auflösbar sein -- sonst fehlt tzdata im Image."""
    from zoneinfo import ZoneInfo

    from app.scheduler.service import resolve_timezone

    zone = resolve_timezone("Europe/Berlin")
    assert zone == ZoneInfo("Europe/Berlin")


def test_missing_timezone_database_falls_back_to_utc(monkeypatch):
    """Fehlende Zeitzonendatenbank darf den Start nicht verhindern."""
    from datetime import timezone as dt_timezone
    from zoneinfo import ZoneInfoNotFoundError

    from app.scheduler import service

    def broken(_name):
        raise ZoneInfoNotFoundError("No time zone found with key Europe/Berlin")

    monkeypatch.setattr(service, "ZoneInfo", broken)
    assert service.resolve_timezone("Europe/Berlin") is dt_timezone.utc
    assert "tzdata" in (service.scheduler_status()["timezone_warning"] or "")


def test_unknown_timezone_falls_back_to_utc():
    from datetime import timezone as dt_timezone

    from app.scheduler.service import resolve_timezone

    assert resolve_timezone("Gibt/EsNicht") is dt_timezone.utc
    assert resolve_timezone(None) is dt_timezone.utc


def test_scheduler_start_failure_does_not_break_the_app(monkeypatch):
    """Ein kaputter Scheduler darf die Anwendung nicht am Start hindern."""
    from app.scheduler import service

    monkeypatch.setattr(service.settings, "enable_scheduler", True)
    monkeypatch.setattr(service, "_scheduler", None)

    class Exploding:
        def __init__(self, *a, **kw):
            raise RuntimeError("kaputt")

    monkeypatch.setattr(service, "BackgroundScheduler", Exploding)
    assert service.start_scheduler() is None
    assert service.scheduler_status()["running"] is False


def test_app_starts_even_without_scheduler(monkeypatch, caplog):
    """Startup-Sequenz der App bleibt trotz Scheduler-Fehler heil.

    Genau dieser Fall trat im Container auf: ohne Zeitzonendatenbank warf
    BackgroundScheduler(timezone=...) beim Start, uvicorn beendete sich mit
    "Application startup failed" und der Healthcheck blieb rot.
    """
    import logging

    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.scheduler import service

    def explode():
        raise RuntimeError("Scheduler kaputt (simuliert)")

    monkeypatch.setattr(service, "start_scheduler", explode)
    with caplog.at_level(logging.ERROR, logger="app.main"):
        with TestClient(create_app()) as client:
            assert client.get("/health").json() == {"status": "ok"}
            assert client.get("/api/meta").status_code == 200
    assert any("Scheduler-Start fehlgeschlagen" in record.message for record in caplog.records), (
        "Der Scheduler-Fehler wurde nicht abgefangen und protokolliert"
    )
