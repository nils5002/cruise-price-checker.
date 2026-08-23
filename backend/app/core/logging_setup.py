"""Structured logging with hard redaction of secrets.

Cookies, session tokens, auth headers, proxy credentials and payment data must
never reach the log stream.  We therefore run every record through a filter
that (a) removes known secret values and (b) masks anything that *looks* like a
credential.
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from app.config import settings

REDACTED = "***REDACTED***"

# Patterns for things that must never be logged, even accidentally.
_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?i)\b(cookie|set-cookie|authorization|x-api-key|api[_-]?key|bearer)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|session[_-]?id)\b\s*[:=]\s*\S+"),
    # user:pass@host  (proxy / db URLs)
    re.compile(r"(?i)\b([a-z0-9+.\-]+)://[^\s/@]+:[^\s/@]+@"),
    # credit-card-ish digit runs
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
]


class RedactionFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        for pattern in _PATTERNS:
            if pattern.pattern.endswith("@"):
                text = pattern.sub(lambda m: f"{m.group(1)}://{REDACTED}@", text)
            else:
                text = pattern.sub(REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            record.msg = self._scrub(str(record.msg))
            if record.args:
                # Nur Strings scrubben -- Zahlen muessen Zahlen bleiben, sonst
                # brechen Formatangaben wie %d oder %.0f.
                if isinstance(record.args, dict):
                    record.args = {
                        key: (self._scrub(value) if isinstance(value, str) else value)
                        for key, value in record.args.items()
                    }
                else:
                    record.args = tuple(
                        self._scrub(arg) if isinstance(arg, str) else arg for arg in record.args
                    )
        except Exception:  # pragma: no cover - logging must never explode
            return True
        return True


def redact(text: str) -> str:
    """Public helper so API/debug output uses the same scrubbing."""
    return RedactionFilter(settings.secret_values())._scrub(text or "")


class LocalTimeFormatter(logging.Formatter):
    """Formatter mit Zeitstempeln in der konfigurierten Zeitzone.

    Bewusst ueber ``zoneinfo`` statt ueber die libc: das Basisimage bringt keine
    System-Zeitzonendatenbank mit, das pip-Paket ``tzdata`` genuegt so.
    """

    def __init__(self, fmt: str, datefmt: str, tz_name: Optional[str] = None) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._tz = self._resolve(tz_name)

    @staticmethod
    def _resolve(tz_name: Optional[str]):
        if not tz_name:
            return timezone.utc
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(tz_name)
        except Exception:  # noqa: BLE001 - Logging darf nie am Start scheitern
            return timezone.utc

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:  # noqa: N802
        stamp = datetime.fromtimestamp(record.created, tz=self._tz)
        return stamp.strftime(datefmt or self.datefmt or "%Y-%m-%d %H:%M:%S")


_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        LocalTimeFormatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            tz_name=settings.timezone,
        )
    )
    handler.addFilter(RedactionFilter(settings.secret_values()))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))

    for noisy in ("httpx", "httpcore", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
