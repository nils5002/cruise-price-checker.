"""Application services shared by API and scheduler."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging_setup import get_logger
from app.core.security import UrlValidationError, validate_target_url
from app.models import Cruise, PriceHistory, Scan, ScanResult, ScanStatus
from app.providers.base import ParsedUrl
from app.providers.registry import provider_for_url
from app.scanner.queue import check_rate_limit, queue

logger = get_logger(__name__)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:32]


def parse_and_validate(url: str) -> tuple:
    """Validate the URL against the allowlist and parse it with a provider."""
    normalised = validate_target_url(url)
    provider = provider_for_url(normalised)
    if provider is None:
        raise UrlValidationError(
            "Für diese URL ist kein Provider vorhanden. Unterstuetzt wird derzeit MSC Cruises."
        )
    parsed: ParsedUrl = provider.parse_url(normalised)
    return provider, parsed


def apply_parsed(cruise: Cruise, parsed: ParsedUrl) -> Cruise:
    cruise.external_id = cruise.external_id or parsed.external_id
    cruise.ship = cruise.ship or parsed.ship
    cruise.departure_date = cruise.departure_date or parsed.departure_date
    cruise.return_date = cruise.return_date or parsed.return_date
    cruise.nights = cruise.nights or parsed.nights
    cruise.origin = cruise.origin or parsed.origin
    cruise.destination = cruise.destination or parsed.destination
    cruise.cabin_type = cruise.cabin_type or parsed.cabin_type
    cruise.cabin_category = cruise.cabin_category or parsed.cabin_category
    cruise.rate_code = cruise.rate_code or parsed.rate_code
    cruise.price_code = cruise.price_code or parsed.price_code
    cruise.adults = cruise.adults if cruise.adults is not None else parsed.adults
    cruise.children = cruise.children if cruise.children is not None else parsed.children
    cruise.passenger_count = cruise.passenger_count or parsed.passenger_count
    if cruise.flight_included is None:
        cruise.flight_included = parsed.flight_included
    cruise.currency = parsed.currency or cruise.currency or "EUR"
    cruise.parsed_params = parsed.to_dict()
    if not cruise.title:
        parts = [parsed.ship or "Kreuzfahrt"]
        if parsed.departure_date:
            parts.append(parsed.departure_date)
        cruise.title = " ".join(parts)
    cruise.updated_at = datetime.now(timezone.utc)
    return cruise


def get_or_create_cruise(db: Session, url: str) -> Cruise:
    provider, parsed = parse_and_validate(url)
    digest = url_hash(parsed.url)
    cruise = db.scalar(select(Cruise).where(Cruise.url_hash == digest))
    if cruise is None:
        cruise = Cruise(provider=provider.key, url=parsed.url, url_hash=digest)
        db.add(cruise)
    apply_parsed(cruise, parsed)
    db.commit()
    db.refresh(cruise)
    return cruise


def create_scan(
    db: Session,
    cruise: Cruise,
    *,
    trigger: str = "manual",
    profiles: Optional[List[str]] = None,
    cookie_modes: Optional[List[str]] = None,
    referrers: Optional[List[str]] = None,
    proxies: Optional[List[str]] = None,
    rounds: Optional[int] = None,
    enforce_rate_limit: bool = True,
) -> Scan:
    if enforce_rate_limit:
        check_rate_limit(db, cruise.id)
    planned_rounds = int(rounds or 1)
    if planned_rounds < 1:
        planned_rounds = 1
    planned_rounds = min(planned_rounds, max(1, settings.verification_rounds))
    scan = Scan(
        cruise_id=cruise.id,
        status=ScanStatus.QUEUED.value,
        trigger=trigger,
        rounds_planned=planned_rounds,
        conditions={
            "profiles": profiles,
            "cookie_modes": cookie_modes,
            "referrers": referrers,
            "proxies": proxies,
            "rounds": planned_rounds,
        },
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    queue.submit(scan.id)
    return scan


def cruise_overview(db: Session, cruise: Cruise) -> Dict[str, Any]:
    """Dashboard row: best/current price, change, last/next check."""
    history = db.scalars(
        select(PriceHistory).where(PriceHistory.cruise_id == cruise.id).order_by(PriceHistory.timestamp)
    ).all()
    lowest_values = [h.lowest_price for h in history if h.lowest_price is not None]
    latest = history[-1] if history else None
    previous = history[-2] if len(history) > 1 else None
    best_ever = min(lowest_values) if lowest_values else None
    current = latest.lowest_price if latest else None
    change = None
    if current is not None and previous and previous.lowest_price is not None:
        change = round(current - previous.lowest_price, 2)
    last_scan = db.scalar(
        select(Scan).where(Scan.cruise_id == cruise.id).order_by(Scan.id.desc()).limit(1)
    )
    return {
        "id": cruise.id,
        "provider": cruise.provider,
        "title": cruise.title,
        "url": cruise.url,
        "ship": cruise.ship,
        "departure_date": cruise.departure_date,
        "return_date": cruise.return_date,
        "nights": cruise.nights,
        "origin": cruise.origin,
        "destination": cruise.destination,
        "cabin_type": cruise.cabin_type,
        "cabin_category": cruise.cabin_category,
        "passenger_count": cruise.passenger_count,
        "adults": cruise.adults,
        "children": cruise.children,
        "flight_included": cruise.flight_included,
        "currency": cruise.currency,
        "monitoring_enabled": cruise.monitoring_enabled,
        "schedule_interval": cruise.schedule_interval,
        "best_price_ever": best_ever,
        "current_price": current,
        "highest_price": max([h.highest_price for h in history if h.highest_price is not None], default=None),
        "change_since_previous": change,
        "last_checked_at": cruise.last_checked_at,
        "next_check_at": cruise.next_check_at,
        "last_scan_id": last_scan.id if last_scan else None,
        "last_scan_status": last_scan.status if last_scan else None,
        "last_verdict": (last_scan.analysis or {}).get("verdict") if last_scan and last_scan.analysis else None,
        "history_points": len(history),
    }


def scan_result_rows(db: Session, scan: Scan) -> List[ScanResult]:
    return list(
        db.scalars(
            select(ScanResult).where(ScanResult.scan_id == scan.id).order_by(ScanResult.round, ScanResult.id)
        ).all()
    )
