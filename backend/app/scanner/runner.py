"""Scan execution.

One scan = the same offer opened under N browser conditions, optionally
repeated for several rounds to verify a detected difference.

Politeness is built in: profiles run strictly sequentially, with pauses between
steps and between profiles, a hard cap on concurrent scans and a per-cruise
daily limit.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.browser.profiles import (
    COOKIE_MODE_LABELS,
    UNIFIED_CONDITIONS,
    BrowserProfile,
    available_profiles,
    get_profile,
)
from app.comparison.analysis import build_analysis
from app.config import settings
from app.core.logging_setup import get_logger
from app.db import session_scope
from app.models import Cruise, PriceHistory, ResultStatus, Scan, ScanLog, ScanResult, ScanStatus
from app.providers.base import PRICE_FIELDS, FlowResult, ParsedUrl, RunContext, Status
from app.providers.registry import get_provider
from app.scanner.artifacts import ArtifactWriter

logger = get_logger(__name__)

MAX_TESTS_PER_ROUND = 24
#: Statuses worth retrying -- a block is never retried, we accept it.
RETRYABLE = {
    Status.TIMEOUT,
    Status.UNREACHABLE,
    Status.SITE_ERROR,
    Status.ERROR,
    Status.SELECTOR_CHANGED,
}


# ---------------------------------------------------------------------------
# Test matrix
# ---------------------------------------------------------------------------
class TestSpec:
    """One concrete test: profile x cookie mode x referrer x proxy."""

    __slots__ = ("profile", "cookie_mode", "referrer", "proxy_name")

    def __init__(self, profile: BrowserProfile, cookie_mode: str, referrer: str, proxy_name: Optional[str]):
        self.profile = profile
        self.cookie_mode = cookie_mode
        self.referrer = referrer
        self.proxy_name = proxy_name

    @property
    def key(self) -> str:
        return f"{self.profile.key}|{self.cookie_mode}|{self.referrer}|{self.proxy_name or 'direkt'}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TestSpec {self.key}>"


def build_matrix(
    *,
    profile_keys: Optional[List[str]] = None,
    cookie_modes: Optional[List[str]] = None,
    referrers: Optional[List[str]] = None,
    proxy_names: Optional[List[Optional[str]]] = None,
) -> Tuple[List[TestSpec], List[str]]:
    """Build the test matrix and report everything that was dropped."""
    notes: List[str] = []
    if profile_keys:
        profiles = []
        for key in profile_keys:
            try:
                profiles.append(get_profile(key))
            except KeyError:
                notes.append(f"Profil '{key}' ist unbekannt und wurde übersprungen.")
    else:
        profiles = available_profiles(settings.enable_firefox)
    if not settings.enable_firefox:
        removed = [p.key for p in profiles if p.browser == "firefox"]
        if removed:
            notes.append("Firefox-Profile sind per Konfiguration deaktiviert (ENABLE_FIREFOX=false).")
        profiles = [p for p in profiles if p.browser != "firefox"]

    cookie_modes = cookie_modes or []
    referrers = referrers or (["direct", "google", "bing"] if settings.enable_referrer_tests else ["direct"])
    proxy_names = proxy_names or [None]
    known_proxies = settings.proxy_labels()
    cleaned_proxies: List[Optional[str]] = []
    for name in proxy_names:
        if name in (None, "", "direkt"):
            cleaned_proxies.append(None)
        elif name in known_proxies:
            cleaned_proxies.append(name)
        else:
            notes.append(f"Proxy '{name}' ist nicht konfiguriert und wurde übersprungen.")
    if not cleaned_proxies:
        cleaned_proxies = [None]

    specs: List[TestSpec] = []
    for profile in profiles:
        modes = cookie_modes or [profile.default_cookie_mode]
        for mode in modes:
            if mode not in COOKIE_MODE_LABELS:
                notes.append(f"Cookie-Variante '{mode}' ist unbekannt und wurde übersprungen.")
                continue
            for referrer in referrers:
                for proxy in cleaned_proxies:
                    specs.append(TestSpec(profile, mode, referrer, proxy))

    if len(specs) > MAX_TESTS_PER_ROUND:
        dropped = [s.key for s in specs[MAX_TESTS_PER_ROUND:]]
        notes.append(
            f"Testmatrix auf {MAX_TESTS_PER_ROUND} Tests pro Runde begrenzt - "
            f"nicht ausgeführt: {', '.join(dropped)}"
        )
        specs = specs[:MAX_TESTS_PER_ROUND]
    return specs, notes


# ---------------------------------------------------------------------------
# Single test execution
# ---------------------------------------------------------------------------
def _conditions(spec: TestSpec, parsed: Optional[ParsedUrl], cruise: Cruise) -> Dict[str, Any]:
    return {
        "language": UNIFIED_CONDITIONS["language"],
        "locale": UNIFIED_CONDITIONS["locale"],
        "timezone": UNIFIED_CONDITIONS["timezone"],
        "currency": cruise.currency or UNIFIED_CONDITIONS["currency"],
        "country": UNIFIED_CONDITIONS["country"],
        "viewport": spec.profile.viewport,
        "device_scale_factor": spec.profile.device_scale_factor,
        "user_agent": spec.profile.resolved_user_agent(),
        "cookie_mode": spec.cookie_mode,
        "cookie_mode_label": COOKIE_MODE_LABELS.get(spec.cookie_mode, spec.cookie_mode),
        "referrer": spec.referrer,
        "proxy_name": spec.proxy_name,
        "session_type": spec.profile.session_type,
        "passengers": {
            "adults": cruise.adults,
            "children": cruise.children,
            "total": cruise.passenger_count,
        },
        "requested_trip": {
            "ship": cruise.ship,
            "departure_date": cruise.departure_date,
            "return_date": cruise.return_date,
            "cabin_type": cruise.cabin_type,
            "cabin_category": cruise.cabin_category,
            "rate_code": cruise.rate_code,
            "flight_included": cruise.flight_included,
        },
        "headless": settings.headless,
    }


def run_single_test(
    db: Session,
    scan: Scan,
    cruise: Cruise,
    spec: TestSpec,
    round_no: int,
) -> ScanResult:
    """Execute one profile run and persist the result (never raises)."""
    provider = get_provider(cruise.provider)
    parsed = None
    try:
        parsed = provider.parse_url(cruise.url)
    except Exception:
        parsed = None

    writer = ArtifactWriter(scan.id, spec.profile.key, round_no)
    log_rows: List[ScanLog] = []
    started = time.time()

    result = ScanResult(
        scan_id=scan.id,
        round=round_no,
        profile=spec.profile.key,
        profile_label=spec.profile.label,
        device=spec.profile.device,
        browser=spec.profile.browser,
        platform=spec.profile.platform,
        cookie_mode=spec.cookie_mode,
        referrer=spec.referrer,
        proxy_name=spec.proxy_name,
        session_type=spec.profile.session_type,
        conditions=_conditions(spec, parsed, cruise),
        status=ResultStatus.ERROR.value,
    )

    ctx = RunContext(
        scan_id=scan.id,
        profile_key=spec.profile.key,
        profile_label=spec.profile.label,
        device=spec.profile.device,
        browser=spec.profile.browser,
        cookie_mode=spec.cookie_mode,
        referrer=spec.referrer,
        proxy_name=spec.proxy_name,
        session_type=spec.profile.session_type,
        round=round_no,
        parsed_url=parsed,
    )

    def record(message: str = "", step: Optional[str] = None, level: str = "INFO", **extra: Any) -> None:
        url = extra.get("url")
        if url is None:
            try:
                url = ctx.page.url if ctx.page else None
            except Exception:
                url = None
        log_rows.append(
            ScanLog(
                scan_id=scan.id,
                profile=spec.profile.key,
                round=round_no,
                level=level,
                step=step,
                message=str(message)[:2000],
                url=str(url)[:1000] if url else None,
                page_type=ctx.page_type,
                screenshot_path=extra.get("screenshot_path"),
            )
        )
        logger.info(
            "%s %s [%s/%s] %s",
            cruise.provider.upper(),
            spec.profile.label,
            step or "-",
            round_no,
            message,
        )

    ctx.record_step = record
    ctx.save_screenshot = lambda name: writer.screenshot(ctx.page, name)
    ctx.save_html = lambda name: writer.html(ctx.page, name)

    attempts = 0
    flow: FlowResult = FlowResult(status=Status.ERROR, error="Kein Ergebnis")
    while attempts < max(1, settings.max_retries_per_profile):
        attempts += 1
        try:
            if provider.requires_browser:
                from app.browser.session import open_session

                with open_session(spec.profile, proxy_label=spec.proxy_name) as session:
                    ctx.page = session.page
                    record(
                        f"Browser gestartet ({spec.profile.browser}, {spec.profile.device}, "
                        f"Isolation: {session.isolation.get('mode')}, Cookies zu Beginn: "
                        f"{session.isolation.get('cookies')})",
                        step="session",
                    )
                    result.conditions = {**(result.conditions or {}), "isolation": session.isolation}
                    flow = provider.run_flow(ctx, cruise.url)
                ctx.page = None
            else:
                flow = provider.run_flow(ctx, cruise.url)
        except Exception as exc:  # noqa: BLE001 - contain every failure
            logger.exception("Profil-Run fehlgeschlagen (%s)", spec.profile.key)
            flow = FlowResult(status=Status.ERROR, error=f"{type(exc).__name__}: {exc}")

        if flow.status not in RETRYABLE or attempts >= settings.max_retries_per_profile:
            break
        backoff = settings.retry_backoff_base_s * (2 ** (attempts - 1))
        record(
            f"Versuch {attempts} endete mit '{flow.status}' - neuer Versuch in {backoff:.0f}s.",
            step="retry",
            level="WARNING",
        )
        time.sleep(backoff)

    # --- map the flow result onto the DB row ------------------------------
    prices = flow.prices
    for name in PRICE_FIELDS:
        setattr(result, name, getattr(prices, name, None))
    result.currency = prices.currency or "EUR"
    result.promo_code = prices.promo_code
    result.tariff = prices.tariff or flow.trip.tariff
    result.cabin_category = prices.cabin_category or flow.trip.cabin_category
    result.cabin_type = flow.trip.cabin_type
    result.offer_name = prices.offer_name or flow.trip.offer_name
    result.price_code = prices.price_code or flow.trip.price_code
    result.price_details = prices.to_dict()
    result.identity = flow.trip.to_dict()
    result.final_url = flow.final_url
    result.page_type = flow.page_type
    result.deepest_step = flow.deepest_step
    result.cookie_mode_applied = flow.cookie_mode_applied or ctx.cookie_mode_applied
    result.status = flow.status
    result.error = flow.error
    result.attempts = attempts
    result.duration_ms = int((time.time() - started) * 1000)
    result.artifacts = ctx.artifacts or flow.artifacts
    result.steps = [
        {"step": row.step, "level": row.level, "message": row.message, "url": row.url}
        for row in log_rows
    ][-60:]
    screenshots = [a.get("screenshot") for a in (result.artifacts or []) if a.get("screenshot")]
    result.screenshot_path = screenshots[-1] if screenshots else None

    db.add(result)
    for row in log_rows:
        db.add(row)
    db.commit()

    logger.info(
        "%s %s - final price detected: %s %s (Status %s)",
        cruise.provider.upper(),
        spec.profile.label,
        result.final_price if result.final_price is not None else "n/a",
        result.currency,
        result.status,
    )
    return result


# ---------------------------------------------------------------------------
# Full scan
# ---------------------------------------------------------------------------
def execute_scan(scan_id: int) -> None:
    """Run a queued scan to completion.  Never raises."""
    db = session_scope()
    try:
        scan = db.get(Scan, scan_id)
        if scan is None:
            logger.warning("Scan %s existiert nicht mehr.", scan_id)
            return
        cruise = db.get(Cruise, scan.cruise_id)
        if cruise is None:
            scan.status = ScanStatus.FAILED.value
            scan.error = "Reise wurde entfernt."
            db.commit()
            return

        options = dict(scan.conditions or {})
        specs, notes = build_matrix(
            profile_keys=options.get("profiles"),
            cookie_modes=options.get("cookie_modes"),
            referrers=options.get("referrers"),
            proxy_names=options.get("proxies"),
        )
        if not specs:
            scan.status = ScanStatus.FAILED.value
            scan.error = "Keine gültigen Testprofile ausgewählt."
            scan.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        scan.status = ScanStatus.RUNNING.value
        scan.profiles_requested = [s.key for s in specs]
        scan.conditions = {
            **options,
            "matrix_notes": notes,
            "unified": UNIFIED_CONDITIONS,
            "tests_per_round": len(specs),
        }
        db.commit()
        for note in notes:
            db.add(ScanLog(scan_id=scan.id, level="WARNING", step="matrix", message=note))
        db.commit()

        max_rounds = int(options.get("rounds") or 1)
        if settings.enable_multi_round_verification:
            max_rounds = max(max_rounds, 1)
        rounds_done = 0

        for round_no in range(1, max_rounds + 1):
            logger.info("Scan %s: Runde %s/%s startet (%s Tests).", scan.id, round_no, max_rounds, len(specs))
            for index, spec in enumerate(specs):
                run_single_test(db, scan, cruise, spec, round_no)
                if index < len(specs) - 1:
                    time.sleep(settings.delay_between_profiles_s)
            rounds_done = round_no
            scan.rounds_completed = rounds_done
            db.commit()

            results = db.scalars(select(ScanResult).where(ScanResult.scan_id == scan.id)).all()
            interim = build_analysis(results, rounds_planned=max_rounds)
            scan.analysis = interim
            db.commit()

            # Stop early when there is nothing to verify.
            if round_no < max_rounds:
                if interim.get("verdict") == "no_difference":
                    db.add(
                        ScanLog(
                            scan_id=scan.id,
                            level="INFO",
                            step="rounds",
                            message=(
                                "Kein Preisunterschied in Runde "
                                f"{round_no} - weitere Verifikationsrunden entfallen."
                            ),
                        )
                    )
                    db.commit()
                    break
                time.sleep(settings.delay_between_profiles_s)

        results = db.scalars(select(ScanResult).where(ScanResult.scan_id == scan.id)).all()
        analysis = build_analysis(results, rounds_planned=max_rounds)
        scan.analysis = analysis
        scan.rounds_planned = max_rounds
        scan.rounds_completed = rounds_done
        scan.status = ScanStatus.DONE.value
        scan.finished_at = datetime.now(timezone.utc)

        _write_history(db, cruise, scan, analysis)
        _update_schedule(cruise)
        db.commit()

        try:
            from app.notify.dispatcher import evaluate_alerts

            evaluate_alerts(db, cruise, scan, analysis)
        except Exception:  # pragma: no cover - notifications must not fail a scan
            logger.exception("Preisalarm-Auswertung fehlgeschlagen")

        logger.info(
            "Scan %s abgeschlossen: %s (günstigster Preis: %s)",
            scan.id,
            analysis.get("verdict"),
            analysis.get("lowest_price"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Scan %s fehlgeschlagen", scan_id)
        try:
            scan = db.get(Scan, scan_id)
            if scan:
                scan.status = ScanStatus.FAILED.value
                scan.error = f"{type(exc).__name__}: {exc}"
                scan.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:  # pragma: no cover
            pass
    finally:
        db.close()


def _write_history(db: Session, cruise: Cruise, scan: Scan, analysis: Dict[str, Any]) -> None:
    lowest = analysis.get("lowest_price")
    highest = analysis.get("highest_price")
    if lowest is None and highest is None:
        return
    db.add(
        PriceHistory(
            cruise_id=cruise.id,
            scan_id=scan.id,
            timestamp=datetime.now(timezone.utc),
            lowest_price=lowest,
            highest_price=highest,
            currency=analysis.get("currency") or "EUR",
            lowest_profile=(analysis.get("cheapest") or {}).get("profile"),
            highest_profile=(analysis.get("most_expensive") or {}).get("profile"),
            results_with_price=analysis.get("profiles_with_price") or 0,
        )
    )
    cruise.last_checked_at = datetime.now(timezone.utc)


def _update_schedule(cruise: Cruise) -> None:
    interval_hours = {"6h": 6, "12h": 12, "daily": 24}.get(cruise.schedule_interval or "manual")
    if interval_hours and cruise.monitoring_enabled:
        cruise.next_check_at = datetime.now(timezone.utc) + timedelta(hours=interval_hours)
    else:
        cruise.next_check_at = None
