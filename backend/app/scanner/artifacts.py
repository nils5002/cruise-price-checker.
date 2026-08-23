"""Screenshots and HTML snapshots.

Layout::

    /data/screenshots/<scan-id>/<profile>/<nn>-<step>.png
    /data/snapshots/<scan-id>/<profile>/<nn>-<step>.html

All paths are built with :func:`app.core.security.safe_relpath`, so a profile or
step name can never escape the data directory.  HTML is sanitised before it is
written: scripts, form values and anything that looks like a token or cookie are
removed.
"""
from __future__ import annotations

import os
import re
from typing import Any, List, Optional

from app.config import settings
from app.core.logging_setup import get_logger, redact
from app.core.security import safe_relpath

logger = get_logger(__name__)

MAX_HTML_BYTES = 2_500_000

_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_NOSCRIPT_RE = re.compile(r"<noscript\b[^>]*>.*?</noscript>", re.IGNORECASE | re.DOTALL)
_IFRAME_RE = re.compile(r"<iframe\b[^>]*>.*?</iframe>", re.IGNORECASE | re.DOTALL)
_VALUE_RE = re.compile(r'\bvalue\s*=\s*"(?:[^"]{0,4000})"', re.IGNORECASE)
_HIDDEN_INPUT_RE = re.compile(r'<input\b[^>]*type\s*=\s*"hidden"[^>]*>', re.IGNORECASE)
_SENSITIVE_ATTR_RE = re.compile(
    r'\b(?:data-[\w-]*(?:token|session|auth|user|customer|email|cookie)[\w-]*|'
    r'csrf[\w-]*|authenticity_token|nonce|integrity)\s*=\s*"[^"]*"',
    re.IGNORECASE,
)
_JSON_SECRET_RE = re.compile(
    r'"(?:[\w]*(?:token|session|cookie|password|secret|auth|jwt|email|phone)[\w]*)"\s*:\s*"[^"]*"',
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")


def sanitize_html(html: str) -> str:
    """Remove scripts, form values and anything credential-like."""
    if not html:
        return ""
    text = html[:MAX_HTML_BYTES]
    text = _SCRIPT_RE.sub("<!-- script entfernt -->", text)
    text = _NOSCRIPT_RE.sub("", text)
    text = _IFRAME_RE.sub("<!-- iframe entfernt -->", text)
    text = _HIDDEN_INPUT_RE.sub("<!-- hidden input entfernt -->", text)
    text = _VALUE_RE.sub('value="[entfernt]"', text)
    text = _SENSITIVE_ATTR_RE.sub('data-removed="1"', text)
    text = _JSON_SECRET_RE.sub('"removed":"[entfernt]"', text)
    text = _EMAIL_RE.sub("[email entfernt]", text)
    return redact(text)


class ArtifactWriter:
    """Per profile-run artifact sink."""

    def __init__(self, scan_id: int, profile: str, round_no: int = 1) -> None:
        self.scan_id = scan_id
        self.profile = profile
        self.round = round_no
        self._counter = 0
        self._names: dict = {}
        folder = safe_relpath(f"scan-{scan_id}", f"{profile}-r{round_no}")
        self.screenshot_dir = os.path.join(settings.screenshot_dir, folder)
        self.snapshot_dir = os.path.join(settings.snapshot_dir, folder)
        self.rel_screenshot_dir = folder
        self.saved: List[str] = []

    # -- helpers -------------------------------------------------------
    def _next_name(self, step: str) -> str:
        """Stable name per step: screenshot and HTML snapshot share it."""
        if step in self._names:
            return self._names[step]
        self._counter += 1
        clean = re.sub(r"[^A-Za-z0-9._-]+", "-", step).strip("-") or "schritt"
        name = f"{self._counter:02d}-{clean[:60]}"
        self._names[step] = name
        return name

    def screenshot(self, page: Any, step: str) -> Optional[str]:
        """Full page screenshot; returns the path relative to the data dir."""
        name = self._next_name(step)
        rel = os.path.join("screenshots", self.rel_screenshot_dir, f"{name}.png")
        target = os.path.join(settings.data_dir, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            if page is None:
                # Mock/test runs: write a placeholder so the gallery works.
                from app.providers.mock.adapter import PNG_1PX

                with open(target, "wb") as handle:
                    handle.write(PNG_1PX)
            else:
                page.screenshot(path=target, full_page=True, timeout=20_000)
        except Exception as exc:
            logger.warning("Screenshot '%s' fehlgeschlagen: %s", step, type(exc).__name__)
            return None
        self.saved.append(rel)
        return rel

    def html(self, page: Any, step: str) -> Optional[str]:
        if not settings.enable_html_snapshots:
            return None
        name = self._next_name(step)
        rel = os.path.join("snapshots", self.rel_screenshot_dir, f"{name}.html")
        target = os.path.join(settings.data_dir, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            raw = "<html><!-- mock run --></html>" if page is None else page.content()
            with open(target, "w", encoding="utf-8", errors="replace") as handle:
                handle.write(sanitize_html(raw))
        except Exception as exc:
            logger.warning("HTML-Snapshot '%s' fehlgeschlagen: %s", step, type(exc).__name__)
            return None
        self.saved.append(rel)
        return rel
