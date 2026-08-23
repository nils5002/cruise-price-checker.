"""Flight comparison interface -- prepared, disabled by default.

Goal (later): compare "cruise incl. flight package" against "cruise only +
separate flight".  There is intentionally *no* scraper here: without a clean,
permitted data source we do not guess prices.  Implement a provider against an
official API (or a licensed data feed) and register it below.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import settings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class FlightQuery:
    origin_airports: List[str]
    destination: str
    outbound_date: str
    inbound_date: Optional[str] = None
    adults: int = 2
    children: int = 0
    currency: str = "EUR"


@dataclass
class FlightOffer:
    origin: str
    destination: str
    price: Optional[float]
    currency: str = "EUR"
    airline: Optional[str] = None
    source: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class FlightProvider(abc.ABC):
    key = "base"
    label = "Base"
    enabled = False

    @abc.abstractmethod
    def search(self, query: FlightQuery) -> List[FlightOffer]: ...


class DisabledFlightProvider(FlightProvider):
    """Placeholder so the API can answer honestly instead of inventing data."""

    key = "disabled"
    label = "Kein Flugdatenanbieter konfiguriert"
    enabled = False

    def search(self, query: FlightQuery) -> List[FlightOffer]:
        logger.info("Flugvergleich angefragt, aber kein Anbieter aktiv - es werden keine Preise geschaetzt.")
        return []


_PROVIDER: FlightProvider = DisabledFlightProvider()


def flight_status() -> Dict[str, Any]:
    return {
        "enabled": bool(settings.enable_flight_comparison and _PROVIDER.enabled),
        "provider": _PROVIDER.label,
        "preferred_airports": settings.airport_list,
        "note": (
            "Der Flugvergleich ist als Schnittstelle vorbereitet, aber bewusst deaktiviert: "
            "ohne saubere, zulaessige Datenquelle werden keine Flugpreise ermittelt oder geschaetzt."
        ),
    }


def search_flights(query: FlightQuery) -> List[FlightOffer]:
    if not settings.enable_flight_comparison or not _PROVIDER.enabled:
        return []
    return _PROVIDER.search(query)
