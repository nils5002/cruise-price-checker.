"""Scan queue.

Deliberately small: at most ``MAX_CONCURRENT_SCANS`` scans run at the same time
(default 1), each in its own worker thread.  Playwright's sync API is used
inside those threads, which keeps the adapters simple and avoids event-loop
pitfalls.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging_setup import get_logger
from app.models import Scan, ScanStatus

logger = get_logger(__name__)


class RateLimitExceeded(RuntimeError):
    pass


class ScanQueue:
    def __init__(self, max_workers: Optional[int] = None) -> None:
        self._max_workers = max(1, int(max_workers or settings.max_concurrent_scans))
        self._executor: Optional[ThreadPoolExecutor] = None
        self._closed = False
        self._lock = threading.Lock()
        self._running: Dict[int, Future] = {}
        self._queued: List[int] = []

    def _ensure_executor(self) -> ThreadPoolExecutor:
        """Create (or re-create) the pool.

        The pool is rebuilt after a shutdown so an application restart inside
        the same process (uvicorn --reload, tests) keeps working.
        """
        if self._executor is None or self._closed:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers, thread_name_prefix="scan"
            )
            self._closed = False
        return self._executor

    # -- introspection -------------------------------------------------
    @property
    def max_workers(self) -> int:
        return self._max_workers

    def status(self) -> Dict[str, object]:
        with self._lock:
            return {
                "max_concurrent_scans": self._max_workers,
                "running": sorted(scan_id for scan_id, fut in self._running.items() if not fut.done()),
                "queued": list(self._queued),
            }

    def is_active(self, scan_id: int) -> bool:
        with self._lock:
            future = self._running.get(scan_id)
            return future is not None and not future.done()

    # -- submission ----------------------------------------------------
    def submit(self, scan_id: int) -> None:
        from app.scanner.runner import execute_scan

        def job() -> None:
            with self._lock:
                if scan_id in self._queued:
                    self._queued.remove(scan_id)
            try:
                execute_scan(scan_id)
            finally:
                with self._lock:
                    self._running.pop(scan_id, None)

        with self._lock:
            if scan_id in self._running and not self._running[scan_id].done():
                logger.info("Scan %s laeuft bereits.", scan_id)
                return
            self._queued.append(scan_id)
            future = self._ensure_executor().submit(job)
            self._running[scan_id] = future
        logger.info("Scan %s eingereiht (max. %s parallel).", scan_id, self._max_workers)

    def shutdown(self) -> None:
        with self._lock:
            executor, self._executor, self._closed = self._executor, None, True
        if executor is not None:
            executor.shutdown(wait=False)


queue = ScanQueue()


def check_rate_limit(db: Session, cruise_id: int) -> None:
    """Protect the target site: only a few checks per cruise and day."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    count = db.scalar(
        select(func.count(Scan.id)).where(Scan.cruise_id == cruise_id, Scan.started_at >= since)
    ) or 0
    if count >= settings.max_scans_per_cruise_per_day:
        raise RateLimitExceeded(
            f"Limit erreicht: maximal {settings.max_scans_per_cruise_per_day} Preischecks pro Reise "
            "und Tag. Das schützt die Zielseite vor unnötiger Last."
        )


def running_scan_count(db: Session) -> int:
    return db.scalar(
        select(func.count(Scan.id)).where(Scan.status.in_([ScanStatus.RUNNING.value, ScanStatus.QUEUED.value]))
    ) or 0
