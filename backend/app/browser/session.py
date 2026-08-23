"""Playwright session management.

Isolation guarantees per *clean* test:

* a brand new browser process with a throw-away user-data directory
  (=> no shared HTTP cache, no service workers, no code cache),
* a brand new BrowserContext (=> no cookies, localStorage, sessionStorage,
  IndexedDB, no login state),
* the temp directory is removed afterwards.

The ``returning_visitor`` profile is the only one that uses a *persistent*
user-data directory -- deliberately, and never mixed with clean runs.
"""
from __future__ import annotations

import os
import random
import shutil
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urlparse

from app.browser.profiles import BrowserProfile
from app.config import settings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)

PLAYWRIGHT_AVAILABLE = True
try:  # pragma: no cover - depends on environment
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    PLAYWRIGHT_AVAILABLE = False

    class PlaywrightError(Exception):  # type: ignore[no-redef]
        pass

    class PlaywrightTimeoutError(PlaywrightError):  # type: ignore[no-redef]
        pass

    def sync_playwright():
        raise RuntimeError(
            "Playwright ist in dieser Umgebung nicht installiert. "
            "Im Docker-Image (mcr.microsoft.com/playwright/python) ist es vorhanden."
        )


CHROMIUM_ARGS = [
    # Required for running Chromium inside a container.
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    # Keep the window size deterministic.
    "--hide-scrollbars",
]


def proxy_config(proxy_label: Optional[str]) -> Optional[Dict[str, str]]:
    """Translate a proxy *label* into a Playwright proxy config.

    The credentials never leave this function -- callers only ever see the
    label, which is what gets persisted and displayed.
    """
    if not proxy_label:
        return None
    url = settings.proxy_map().get(proxy_label)
    if not url:
        logger.warning("Proxy-Label '%s' ist nicht konfiguriert - Test laeuft direkt.", proxy_label)
        return None
    parsed = urlparse(url)
    if not parsed.hostname:
        logger.warning("Proxy-Label '%s' hat eine ungültige Konfiguration.", proxy_label)
        return None
    server = f"{parsed.scheme or 'http'}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    config: Dict[str, str] = {"server": server}
    if parsed.username:
        config["username"] = parsed.username
    if parsed.password:
        config["password"] = parsed.password
    return config


def human_pause(multiplier: float = 1.0) -> None:
    """Deliberately slow, polite pacing between interactions."""
    low = settings.min_delay_between_steps_ms / 1000.0
    high = max(low, settings.max_delay_between_steps_ms / 1000.0)
    time.sleep(random.uniform(low, high) * multiplier)


class BrowserSession:
    """Wraps an open context + page and exposes the isolation report."""

    def __init__(self, page: Any, context: Any, profile: BrowserProfile, isolation: Dict[str, Any]):
        self.page = page
        self.context = context
        self.profile = profile
        self.isolation = isolation


def _verify_clean(context: Any, page: Any) -> Dict[str, Any]:
    """Prove that a clean context really starts empty."""
    report: Dict[str, Any] = {"cookies": None, "local_storage": None, "session_storage": None}
    try:
        report["cookies"] = len(context.cookies())
    except Exception:  # pragma: no cover
        pass
    try:
        report["local_storage"] = page.evaluate("() => { try { return window.localStorage.length } catch (e) { return -1 } }")
        report["session_storage"] = page.evaluate("() => { try { return window.sessionStorage.length } catch (e) { return -1 } }")
    except Exception:  # pragma: no cover
        pass
    report["clean"] = (report["cookies"] in (0, None)) and (report["local_storage"] in (0, -1, None))
    return report


@contextmanager
def open_session(
    profile: BrowserProfile,
    *,
    proxy_label: Optional[str] = None,
    headless: Optional[bool] = None,
) -> Iterator[BrowserSession]:
    """Open a fully isolated browser session for one profile run."""
    headless = settings.headless if headless is None else headless
    proxy = proxy_config(proxy_label)
    tmp_dir: Optional[str] = None

    with sync_playwright() as pw:
        engine = getattr(pw, profile.browser, None)
        if engine is None:
            raise RuntimeError(f"Browser-Engine '{profile.browser}' ist nicht verfügbar.")

        launch_kwargs: Dict[str, Any] = {"headless": headless}
        if profile.browser == "chromium":
            launch_kwargs["args"] = list(CHROMIUM_ARGS)
        if proxy:
            launch_kwargs["proxy"] = proxy

        browser = None
        context = None
        try:
            if profile.persist_state:
                # Returning visitor: keep cookies/cache between runs on purpose.
                user_data_dir = os.path.join(settings.profile_state_dir, profile.key)
                os.makedirs(user_data_dir, exist_ok=True)
                context = engine.launch_persistent_context(
                    user_data_dir,
                    **launch_kwargs,
                    **profile.context_options(),
                )
                page = context.pages[0] if context.pages else context.new_page()
                isolation = {"mode": "persistent", "user_data_dir": profile.key, "clean": False}
            else:
                # Clean run: new browser process with a throw-away profile dir.
                tmp_dir = tempfile.mkdtemp(prefix=f"cpc-{profile.key}-")
                browser = engine.launch(**launch_kwargs)
                version = ""
                try:
                    version = browser.version or ""
                except Exception:  # pragma: no cover
                    version = ""
                chrome_major = version.split(" ")[-1] if version else None
                context = browser.new_context(**profile.context_options(chrome_major))
                page = context.new_page()
                isolation = {"mode": "isolated", "engine_version": version}
                isolation.update(_verify_clean(context, page))

            context.set_default_timeout(settings.browser_timeout_ms)
            context.set_default_navigation_timeout(settings.navigation_timeout_ms)
            yield BrowserSession(page=page, context=context, profile=profile, isolation=isolation)
        finally:
            for closer in (context, browser):
                if closer is None:
                    continue
                try:
                    closer.close()
                except Exception:  # pragma: no cover
                    pass
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)


def reset_persistent_profile(profile_key: str) -> bool:
    """Delete the stored state of a persistent profile (admin action)."""
    path = os.path.join(settings.profile_state_dir, profile_key)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        logger.info("Persistentes Browserprofil '%s' zurückgesetzt.", profile_key)
        return True
    return False
