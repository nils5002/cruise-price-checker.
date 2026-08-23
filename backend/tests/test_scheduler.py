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
