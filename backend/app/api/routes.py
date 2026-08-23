"""HTTP API.

Everything that changes state (or reveals debug information) is behind the
optional ``X-API-Key`` dependency.  No endpoint ever returns secrets: proxies
are exposed by label only, and log/debug output is scrubbed.
"""
from __future__ import annotations

import mimetypes
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app import __version__
from app.browser.profiles import COOKIE_MODE_LABELS, PROFILES, REFERRER_MODES, UNIFIED_CONDITIONS
from app.browser.session import PLAYWRIGHT_AVAILABLE, reset_persistent_profile
from app.config import settings
from app.core.logging_setup import get_logger, redact
from app.core.security import ALLOWED_DOMAIN_SUFFIXES, UrlValidationError, require_api_key, resolve_within
from app.db import get_db
from app.flights.base import flight_status
from app.models import Cruise, PriceAlert, PriceHistory, ResultStatus, Scan, ScanLog, ScanResult, ScanStatus
from app.notify.channels import CHANNELS, channel_status
from app.providers.registry import provider_info
from app.scanner.queue import RateLimitExceeded, queue
from app.scheduler.service import scheduler_status
from app.schemas import (
    AlertCreate,
    AlertOut,
    CruiseCreate,
    CruiseOut,
    CruiseOverviewOut,
    CruiseUpdate,
    HealthOut,
    MetaOut,
    ParsedUrlOut,
    PriceHistoryOut,
    ScanDetailOut,
    ScanLogOut,
    ScanOptions,
    ScanOut,
    UrlPreviewRequest,
)
from app.services import create_scan, cruise_overview, get_or_create_cruise, parse_and_validate

logger = get_logger(__name__)

router = APIRouter()
admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_api_key)])


# ---------------------------------------------------------------------------
# health & meta
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthOut, tags=["system"])
def health() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/meta", response_model=MetaOut, tags=["system"])
def meta() -> MetaOut:
    return MetaOut(
        app_name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        headless=settings.headless,
        profiles=[
            {
                **profile.to_dict(),
                "available": profile.browser != "firefox" or settings.enable_firefox,
            }
            for profile in PROFILES.values()
        ],
        cookie_modes=[{"key": key, "label": label} for key, label in COOKIE_MODE_LABELS.items()],
        referrers=list(REFERRER_MODES),
        unified_conditions=UNIFIED_CONDITIONS,
        providers=provider_info(),
        proxy_labels=settings.proxy_labels(),
        schedule_intervals=["manual", "6h", "12h", "daily"],
        notification_channels=channel_status(),
        flights=flight_status(),
        limits={
            "max_concurrent_scans": settings.max_concurrent_scans,
            "max_scans_per_cruise_per_day": settings.max_scans_per_cruise_per_day,
            "verification_rounds": settings.verification_rounds,
            "delay_between_profiles_s": settings.delay_between_profiles_s,
            "referrer_tests_enabled": settings.enable_referrer_tests,
            "multi_round_enabled": settings.enable_multi_round_verification,
            "html_snapshots": settings.enable_html_snapshots,
            "playwright_available": PLAYWRIGHT_AVAILABLE,
        },
        allowed_domains=[f"*.{domain}" for domain in ALLOWED_DOMAIN_SUFFIXES],
        api_key_required=bool(settings.api_key),
    )


# ---------------------------------------------------------------------------
# cruises
# ---------------------------------------------------------------------------
@router.post("/parse-url", response_model=ParsedUrlOut, tags=["cruises"])
def preview_url(payload: UrlPreviewRequest) -> ParsedUrlOut:
    """Show what can be read from a link -- without storing anything."""
    try:
        _, parsed = parse_and_validate(payload.url)
    except UrlValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ParsedUrlOut(**parsed.to_dict())


@router.get("/cruises", response_model=List[CruiseOverviewOut], tags=["cruises"])
def list_cruises(db: Session = Depends(get_db)) -> List[CruiseOverviewOut]:
    cruises = db.scalars(select(Cruise).order_by(desc(Cruise.updated_at))).all()
    return [CruiseOverviewOut(**cruise_overview(db, cruise)) for cruise in cruises]


@router.post(
    "/cruises",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    tags=["cruises"],
    dependencies=[Depends(require_api_key)],
)
def create_cruise(payload: CruiseCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        cruise = get_or_create_cruise(db, payload.url)
    except UrlValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.schedule_interval:
        cruise.schedule_interval = payload.schedule_interval
        db.commit()

    scan_id: Optional[int] = None
    warning: Optional[str] = None
    if payload.start_scan:
        options = payload.options or ScanOptions()
        try:
            scan = create_scan(
                db,
                cruise,
                trigger="manual",
                profiles=options.profiles,
                cookie_modes=options.cookie_modes,
                referrers=options.referrers,
                proxies=options.proxies,
                rounds=options.rounds,
            )
            scan_id = scan.id
        except RateLimitExceeded as exc:
            warning = str(exc)
    return {
        "cruise": CruiseOut.model_validate(cruise).model_dump(mode="json"),
        "scan_id": scan_id,
        "warning": warning,
    }


@router.get("/cruises/{cruise_id}", response_model=Dict[str, Any], tags=["cruises"])
def get_cruise(cruise_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    cruise = db.get(Cruise, cruise_id)
    if cruise is None:
        raise HTTPException(status_code=404, detail="Reise nicht gefunden.")
    history = db.scalars(
        select(PriceHistory).where(PriceHistory.cruise_id == cruise_id).order_by(PriceHistory.timestamp)
    ).all()
    scans = db.scalars(
        select(Scan).where(Scan.cruise_id == cruise_id).order_by(desc(Scan.id)).limit(25)
    ).all()
    latest_done = next((s for s in scans if s.status == ScanStatus.DONE.value), None)
    return {
        "cruise": CruiseOut.model_validate(cruise).model_dump(mode="json"),
        "overview": CruiseOverviewOut(**cruise_overview(db, cruise)).model_dump(mode="json"),
        "history": [PriceHistoryOut.model_validate(h).model_dump(mode="json") for h in history],
        "scans": [ScanOut.model_validate(s).model_dump(mode="json") for s in scans],
        "latest_analysis": (latest_done.analysis if latest_done else None),
        "latest_scan_id": latest_done.id if latest_done else None,
        "alerts": [
            AlertOut.model_validate(a).model_dump(mode="json")
            for a in db.scalars(select(PriceAlert).where(PriceAlert.cruise_id == cruise_id)).all()
        ],
    }


@router.patch(
    "/cruises/{cruise_id}",
    response_model=CruiseOut,
    tags=["cruises"],
    dependencies=[Depends(require_api_key)],
)
def update_cruise(cruise_id: int, payload: CruiseUpdate, db: Session = Depends(get_db)) -> CruiseOut:
    cruise = db.get(Cruise, cruise_id)
    if cruise is None:
        raise HTTPException(status_code=404, detail="Reise nicht gefunden.")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(cruise, key, value)
    if "schedule_interval" in data and data["schedule_interval"] == "manual":
        cruise.next_check_at = None
    if data.get("schedule_interval") in ("6h", "12h", "daily") and cruise.next_check_at is None:
        cruise.next_check_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cruise)
    return CruiseOut.model_validate(cruise)


@router.delete(
    "/cruises/{cruise_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["cruises"],
    dependencies=[Depends(require_api_key)],
)
def delete_cruise(cruise_id: int, db: Session = Depends(get_db)) -> Response:
    cruise = db.get(Cruise, cruise_id)
    if cruise is None:
        raise HTTPException(status_code=404, detail="Reise nicht gefunden.")
    db.delete(cruise)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cruises/{cruise_id}/history", response_model=List[PriceHistoryOut], tags=["cruises"])
def cruise_history(cruise_id: int, db: Session = Depends(get_db)) -> List[PriceHistoryOut]:
    if db.get(Cruise, cruise_id) is None:
        raise HTTPException(status_code=404, detail="Reise nicht gefunden.")
    rows = db.scalars(
        select(PriceHistory).where(PriceHistory.cruise_id == cruise_id).order_by(PriceHistory.timestamp)
    ).all()
    return [PriceHistoryOut.model_validate(row) for row in rows]


# ---------------------------------------------------------------------------
# scans
# ---------------------------------------------------------------------------
@router.post(
    "/cruises/{cruise_id}/scans",
    response_model=ScanOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["scans"],
    dependencies=[Depends(require_api_key)],
)
def start_scan(cruise_id: int, options: ScanOptions, db: Session = Depends(get_db)) -> ScanOut:
    cruise = db.get(Cruise, cruise_id)
    if cruise is None:
        raise HTTPException(status_code=404, detail="Reise nicht gefunden.")
    try:
        scan = create_scan(
            db,
            cruise,
            trigger="manual",
            profiles=options.profiles,
            cookie_modes=options.cookie_modes,
            referrers=options.referrers,
            proxies=options.proxies,
            rounds=options.rounds,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    return ScanOut.model_validate(scan)


@router.get("/scans", response_model=List[ScanOut], tags=["scans"])
def list_scans(
    limit: int = Query(default=50, ge=1, le=200),
    cruise_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> List[ScanOut]:
    query = select(Scan).order_by(desc(Scan.id)).limit(limit)
    if cruise_id is not None:
        query = select(Scan).where(Scan.cruise_id == cruise_id).order_by(desc(Scan.id)).limit(limit)
    return [ScanOut.model_validate(scan) for scan in db.scalars(query).all()]


@router.get("/scans/{scan_id}", response_model=ScanDetailOut, tags=["scans"])
def get_scan(scan_id: int, db: Session = Depends(get_db)) -> ScanDetailOut:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan nicht gefunden.")
    results = db.scalars(
        select(ScanResult).where(ScanResult.scan_id == scan_id).order_by(ScanResult.round, ScanResult.id)
    ).all()
    payload = ScanOut.model_validate(scan).model_dump()
    return ScanDetailOut.model_validate({**payload, "results": results})


@router.get("/scans/{scan_id}/logs", response_model=List[ScanLogOut], tags=["scans"])
def get_scan_logs(
    scan_id: int,
    profile: Optional[str] = None,
    limit: int = Query(default=400, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> List[ScanLogOut]:
    if db.get(Scan, scan_id) is None:
        raise HTTPException(status_code=404, detail="Scan nicht gefunden.")
    query = select(ScanLog).where(ScanLog.scan_id == scan_id)
    if profile:
        query = query.where(ScanLog.profile == profile)
    rows = db.scalars(query.order_by(ScanLog.id).limit(limit)).all()
    out: List[ScanLogOut] = []
    for row in rows:
        item = ScanLogOut.model_validate(row)
        item.message = redact(item.message)
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------
@router.get("/cruises/{cruise_id}/alerts", response_model=List[AlertOut], tags=["alerts"])
def list_alerts(cruise_id: int, db: Session = Depends(get_db)) -> List[AlertOut]:
    return [
        AlertOut.model_validate(alert)
        for alert in db.scalars(select(PriceAlert).where(PriceAlert.cruise_id == cruise_id)).all()
    ]


@router.post(
    "/cruises/{cruise_id}/alerts",
    response_model=AlertOut,
    status_code=status.HTTP_201_CREATED,
    tags=["alerts"],
    dependencies=[Depends(require_api_key)],
)
def create_alert(cruise_id: int, payload: AlertCreate, db: Session = Depends(get_db)) -> AlertOut:
    if db.get(Cruise, cruise_id) is None:
        raise HTTPException(status_code=404, detail="Reise nicht gefunden.")
    if payload.threshold_total is None and payload.drop_percent is None:
        raise HTTPException(
            status_code=400, detail="Es muss eine Preisschwelle oder ein prozentualer Rückgang angegeben werden."
        )
    channel = CHANNELS.get(payload.channel)
    alert = PriceAlert(
        cruise_id=cruise_id,
        channel=payload.channel,
        target=payload.target,
        threshold_total=payload.threshold_total,
        drop_percent=payload.drop_percent,
        enabled=payload.enabled,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    if channel is not None and not channel.configured:
        logger.warning("Preisalarm %s erstellt, Kanal '%s' ist aber nicht konfiguriert.", alert.id, payload.channel)
    return AlertOut.model_validate(alert)


@router.delete(
    "/alerts/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["alerts"],
    dependencies=[Depends(require_api_key)],
)
def delete_alert(alert_id: int, db: Session = Depends(get_db)) -> Response:
    alert = db.get(PriceAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Preisalarm nicht gefunden.")
    db.delete(alert)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/alerts/{alert_id}/test",
    response_model=Dict[str, Any],
    tags=["alerts"],
    dependencies=[Depends(require_api_key)],
)
def test_alert(alert_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    alert = db.get(PriceAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Preisalarm nicht gefunden.")
    channel = CHANNELS.get(alert.channel)
    if channel is None or not channel.configured:
        return {"sent": False, "detail": f"Kanal '{alert.channel}' ist nicht konfiguriert."}
    sent = channel.send(
        "Cruise Price Checker - Testbenachrichtigung",
        "Dies ist eine Testnachricht. Der Kanal funktioniert.",
        alert.target,
    )
    return {"sent": sent, "detail": "Testnachricht versendet." if sent else "Versand fehlgeschlagen."}


# ---------------------------------------------------------------------------
# artifacts (screenshots / html snapshots)
# ---------------------------------------------------------------------------
@router.get("/artifacts/{path:path}", tags=["artifacts"])
def get_artifact(path: str):
    """Serve a screenshot or HTML snapshot from the data directory."""
    try:
        target = resolve_within(settings.data_dir, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungültiger Pfad.") from exc
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    suffix = os.path.splitext(target)[1].lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".html", ".htm", ".txt", ".json"):
        raise HTTPException(status_code=403, detail="Dateityp nicht erlaubt.")
    if suffix in (".html", ".htm"):
        # Never execute a stored snapshot in the browser -- serve as text.
        with open(target, encoding="utf-8", errors="replace") as handle:
            return PlainTextResponse(handle.read(), media_type="text/plain; charset=utf-8")
    media_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


# ---------------------------------------------------------------------------
# admin
# ---------------------------------------------------------------------------
@admin_router.get("/status", response_model=Dict[str, Any])
def admin_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    counts = {
        "cruises": db.scalar(select(func.count(Cruise.id))) or 0,
        "scans": db.scalar(select(func.count(Scan.id))) or 0,
        "results": db.scalar(select(func.count(ScanResult.id))) or 0,
        "alerts": db.scalar(select(func.count(PriceAlert.id))) or 0,
        "history_points": db.scalar(select(func.count(PriceHistory.id))) or 0,
    }
    by_status: Dict[str, int] = {
        str(status_value): int(count)
        for status_value, count in db.execute(
            select(ScanResult.status, func.count(ScanResult.id)).group_by(ScanResult.status)
        ).all()
    }
    storage: Dict[str, Any] = {}
    for label, directory in (
        ("screenshots", settings.screenshot_dir),
        ("snapshots", settings.snapshot_dir),
        ("browser_profiles", settings.profile_state_dir),
    ):
        total = 0
        files = 0
        for root, _dirs, names in os.walk(directory):
            for name in names:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                    files += 1
                except OSError:
                    continue
        storage[label] = {"files": files, "bytes": total}
    return {
        "version": __version__,
        "environment": settings.environment,
        "database_backend": settings.database_url.split(":")[0],
        "playwright_available": PLAYWRIGHT_AVAILABLE,
        "headless": settings.headless,
        "counts": counts,
        "result_status_counts": by_status,
        "queue": queue.status(),
        "scheduler": scheduler_status(),
        "profiles": [p.to_dict() for p in PROFILES.values()],
        "providers": provider_info(),
        "proxy_profiles": [
            {"label": label, "configured": True} for label in settings.proxy_labels()
        ],
        "notification_channels": channel_status(),
        "flights": flight_status(),
        "storage": storage,
        "limits": {
            "max_concurrent_scans": settings.max_concurrent_scans,
            "max_scans_per_cruise_per_day": settings.max_scans_per_cruise_per_day,
            "delay_between_profiles_s": settings.delay_between_profiles_s,
            "max_retries_per_profile": settings.max_retries_per_profile,
        },
    }


@admin_router.get("/errors", response_model=List[Dict[str, Any]])
def admin_errors(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    ok_states = (ResultStatus.OK.value, ResultStatus.PARTIAL.value)
    rows = db.scalars(
        select(ScanResult).where(ScanResult.status.notin_(ok_states)).order_by(desc(ScanResult.id)).limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "scan_id": row.scan_id,
            "profile": row.profile,
            "round": row.round,
            "status": row.status,
            "error": redact(row.error or ""),
            "page_type": row.page_type,
            "deepest_step": row.deepest_step,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "screenshot_path": row.screenshot_path,
        }
        for row in rows
    ]


@admin_router.get("/debug/scan/{scan_id}", response_model=Dict[str, Any])
def admin_debug_scan(scan_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Debug view: URL, page type, prices, Playwright steps, errors, screenshots.

    Contains no cookies, tokens, proxy credentials or other secrets.
    """
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan nicht gefunden.")
    results = db.scalars(select(ScanResult).where(ScanResult.scan_id == scan_id).order_by(ScanResult.id)).all()
    logs = db.scalars(select(ScanLog).where(ScanLog.scan_id == scan_id).order_by(ScanLog.id)).all()
    return {
        "scan": ScanOut.model_validate(scan).model_dump(mode="json"),
        "profiles": [
            {
                "profile": row.profile,
                "round": row.round,
                "status": row.status,
                "current_url": row.final_url,
                "page_type": row.page_type,
                "deepest_step": row.deepest_step,
                "cookie_mode": row.cookie_mode,
                "cookie_mode_applied": row.cookie_mode_applied,
                "proxy_name": row.proxy_name,
                "prices_found": {
                    key: value
                    for key, value in (row.price_details or {}).items()
                    if value is not None and key != "source_labels"
                },
                "price_sources": (row.price_details or {}).get("source_labels"),
                "identity": row.identity,
                "error": redact(row.error or ""),
                "screenshots": [a.get("screenshot") for a in (row.artifacts or []) if a.get("screenshot")],
                "html_snapshots": [a.get("html") for a in (row.artifacts or []) if a.get("html")],
                "steps": row.steps,
                "attempts": row.attempts,
                "duration_ms": row.duration_ms,
            }
            for row in results
        ],
        "logs": [
            {
                "profile": row.profile,
                "round": row.round,
                "level": row.level,
                "step": row.step,
                "message": redact(row.message),
                "url": row.url,
                "page_type": row.page_type,
                "screenshot_path": row.screenshot_path,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in logs
        ],
    }


@admin_router.post("/profiles/{profile_key}/reset", response_model=Dict[str, Any])
def admin_reset_profile(profile_key: str) -> Dict[str, Any]:
    if profile_key not in PROFILES:
        raise HTTPException(status_code=404, detail="Profil nicht gefunden.")
    removed = reset_persistent_profile(profile_key)
    return {
        "profile": profile_key,
        "reset": removed,
        "detail": "Persistenter Profilzustand gelöscht." if removed else "Kein gespeicherter Zustand vorhanden.",
    }


router.include_router(admin_router)
