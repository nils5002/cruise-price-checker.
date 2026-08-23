"""Periodic price checks.

Intervals are intentionally coarse (manual / 6h / 12h / daily) and combined
with the per-cruise daily limit in :mod:`app.scanner.queue`, so the target site
never sees more than a handful of requests per day and cruise.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import settings
from app.core.logging_setup import get_logger
from app.db import session_scope
from app.models import Cruise
from app.scanner.queue import RateLimitExceeded, queue

logger = get_logger(__name__)

INTERVAL_HOURS = {"6h": 6, "12h": 12, "daily": 24}
CHECK_EVERY_MINUTES = 10

_scheduler: Optional[BackgroundScheduler] = None


def due_cruises(now: Optional[datetime] = None) -> List[Cruise]:
    now = now or datetime.now(timezone.utc)
    db = session_scope()
    try:
        cruises = db.scalars(
            select(Cruise).where(
                Cruise.monitoring_enabled.is_(True),
                Cruise.schedule_interval.in_(list(INTERVAL_HOURS.keys())),
            )
        ).all()
        due = []
        for cruise in cruises:
            next_check = cruise.next_check_at
            if next_check is None:
                due.append(cruise)
                continue
            if next_check.tzinfo is None:
                next_check = next_check.replace(tzinfo=timezone.utc)
            if next_check <= now:
                due.append(cruise)
        return due
    finally:
        db.close()


def tick() -> None:
    """Queue all due cruises (called by the scheduler)."""
    from app.services import create_scan

    db = session_scope()
    try:
        now = datetime.now(timezone.utc)
        cruises = db.scalars(
            select(Cruise).where(
                Cruise.monitoring_enabled.is_(True),
                Cruise.schedule_interval.in_(list(INTERVAL_HOURS.keys())),
            )
        ).all()
        for cruise in cruises:
            next_check = cruise.next_check_at
            if next_check is not None:
                if next_check.tzinfo is None:
                    next_check = next_check.replace(tzinfo=timezone.utc)
                if next_check > now:
                    continue
            if queue.status()["running"]:
                logger.info("Scheduler wartet: es laeuft bereits ein Scan.")
                return
            try:
                scan = create_scan(
                    db,
                    cruise,
                    trigger="schedule",
                    rounds=settings.verification_rounds if settings.enable_multi_round_verification else 1,
                )
                logger.info("Geplanter Scan %s für Reise %s eingereiht.", scan.id, cruise.id)
            except RateLimitExceeded as exc:
                logger.info("Geplanter Scan für Reise %s übersprungen: %s", cruise.id, exc)
    except Exception:  # pragma: no cover
        logger.exception("Scheduler-Durchlauf fehlgeschlagen")
    finally:
        db.close()


def start_scheduler() -> Optional[BackgroundScheduler]:
    global _scheduler
    if not settings.enable_scheduler:
        logger.info("Scheduler ist deaktiviert (ENABLE_SCHEDULER=false).")
        return None
    if _scheduler is not None:
        return _scheduler
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        tick,
        IntervalTrigger(minutes=CHECK_EVERY_MINUTES),
        id="price-check-tick",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler gestartet (Prüfintervall: %s Minuten).", CHECK_EVERY_MINUTES)
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_status() -> Dict[str, Any]:
    jobs = []
    if _scheduler is not None:
        for job in _scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                }
            )
    return {
        "enabled": settings.enable_scheduler,
        "running": _scheduler is not None and getattr(_scheduler, "running", False),
        "check_every_minutes": CHECK_EVERY_MINUTES,
        "supported_intervals": ["manual", *INTERVAL_HOURS.keys()],
        "jobs": jobs,
    }
