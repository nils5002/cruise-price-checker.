"""Price alert evaluation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging_setup import get_logger
from app.models import Cruise, PriceAlert, PriceHistory, Scan
from app.notify.channels import CHANNELS

logger = get_logger(__name__)

#: Never send the same alert more than once per this window.
DEBOUNCE = timedelta(hours=6)


def _format_money(value: Optional[float], currency: str = "EUR") -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + f" {currency}"


def build_message(cruise: Cruise, scan: Scan, analysis: Dict[str, Any]) -> str:
    currency = analysis.get("currency") or "EUR"
    lines = [
        f"Reise: {cruise.title or cruise.ship or 'Kreuzfahrt'}",
        f"Zeitraum: {cruise.departure_date or '?'} bis {cruise.return_date or '?'}",
        f"Günstigster Preis: {_format_money(analysis.get('lowest_price'), currency)}",
        f"Teuerstes Ergebnis: {_format_money(analysis.get('highest_price'), currency)}",
        f"Bewertung: {analysis.get('headline', '-')}",
        f"Scan-ID: {scan.id}",
    ]
    for text in (analysis.get("interpretation") or [])[:3]:
        lines.append(f"- {text}")
    return "\n".join(lines)


def evaluate_alerts(db: Session, cruise: Cruise, scan: Scan, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Check all alerts of a cruise and dispatch notifications."""
    price = analysis.get("lowest_price")
    if price is None:
        return []
    alerts = db.scalars(
        select(PriceAlert).where(PriceAlert.cruise_id == cruise.id, PriceAlert.enabled.is_(True))
    ).all()
    if not alerts:
        return []

    history = db.scalars(
        select(PriceHistory)
        .where(PriceHistory.cruise_id == cruise.id, PriceHistory.id != None)  # noqa: E711
        .order_by(PriceHistory.timestamp)
    ).all()
    earlier = [h.lowest_price for h in history[:-1] if h.lowest_price is not None]
    reference = min(earlier) if earlier else None

    now = datetime.now(timezone.utc)
    dispatched: List[Dict[str, Any]] = []
    for alert in alerts:
        reasons: List[str] = []
        if alert.threshold_total is not None and price <= alert.threshold_total:
            reasons.append(
                f"Gesamtpreis {_format_money(price)} liegt unter der Schwelle "
                f"{_format_money(alert.threshold_total)}."
            )
        if alert.drop_percent is not None and reference:
            drop = (reference - price) / reference * 100
            if drop >= alert.drop_percent:
                reasons.append(
                    f"Preis ist um {drop:.1f} % gegenueber dem bisherigen Tiefstpreis "
                    f"{_format_money(reference)} gefallen."
                )
        if not reasons:
            continue
        last = alert.last_triggered_at
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if now - last < DEBOUNCE and alert.last_notified_price == price:
                logger.info("Preisalarm %s unterdrueckt (Debounce).", alert.id)
                continue

        channel = CHANNELS.get(alert.channel)
        if channel is None or not channel.configured:
            logger.warning(
                "Preisalarm %s: Kanal '%s' ist nicht konfiguriert - keine Benachrichtigung.",
                alert.id,
                alert.channel,
            )
            continue
        subject = f"Preisalarm: {cruise.title or 'Kreuzfahrt'} - {_format_money(price)}"
        message = build_message(cruise, scan, analysis) + "\n\nGrund:\n" + "\n".join(f"- {r}" for r in reasons)
        ok = channel.send(subject, message, alert.target)
        if ok:
            alert.last_triggered_at = now
            alert.last_notified_price = price
            db.commit()
        dispatched.append({"alert_id": alert.id, "channel": alert.channel, "sent": ok, "reasons": reasons})
    return dispatched
