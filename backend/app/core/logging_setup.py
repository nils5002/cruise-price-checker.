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
from typing import Iterable, List

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


_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
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
