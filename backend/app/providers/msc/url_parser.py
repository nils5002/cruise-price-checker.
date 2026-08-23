"""Tolerant parser for MSC booking links.

MSC uses several different link shapes (marketing pages, deep links into the
booking engine, campaign links).  Instead of guessing we:

1. read every query parameter we recognise via a broad alias table,
2. add a few conservative path heuristics,
3. keep *all* raw parameters so nothing is lost,
4. leave everything we could not determine at ``None`` -- it is then read from
   the booking page itself.

Nothing is ever invented.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlparse

from app.providers.base import ParsedUrl

PROVIDER_KEY = "msc"

MSC_HOST_RE = re.compile(r"(^|\.)msccruises\.(de|com|at|ch)$", re.IGNORECASE)

# --- parameter aliases -----------------------------------------------------
ALIASES: Dict[str, List[str]] = {
    "external_id": [
        "cruiseid", "cruisecode", "cruise", "tripid", "trip", "itineraryid", "itinerary",
        "sailingid", "sailing", "voyagecode", "voyage", "packageid", "packagecode", "offerid",
        "productid", "id", "code",
    ],
    "ship": ["ship", "shipcode", "shipname", "schiff", "vessel"],
    "departure_date": [
        "departuredate", "saildate", "sailingdate", "startdate", "datefrom", "embarkdate",
        "departure", "abfahrt", "abfahrtsdatum", "from", "checkin", "date",
    ],
    "return_date": [
        "returndate", "enddate", "dateto", "disembarkdate", "arrival", "rueckkehr", "to", "checkout",
    ],
    "nights": ["nights", "naechte", "nachte", "duration", "durationnights", "days", "tage"],
    "origin": [
        "port", "embarkport", "departureport", "fromport", "portofdeparture", "hafen",
        "abfahrtshafen", "startport", "portcode", "embarkation",
    ],
    "destination": ["destination", "area", "region", "ziel", "zielgebiet", "geo", "destinationcode"],
    "cabin_type": [
        "cabintype", "cabinkind", "experience", "cabin", "kabine", "kabinenart", "stateroomtype",
        "cabinexperience",
    ],
    "cabin_category": [
        "cabincategory", "category", "categorycode", "grade", "cabingrade", "kabinenkategorie",
        "cat",
    ],
    "adults": ["adults", "adult", "numadults", "erwachsene", "nradults", "adt", "pax", "guests"],
    "children": ["children", "child", "numchildren", "kinder", "nrchildren", "chd", "kids"],
    "rate_code": [
        "rate", "ratecode", "fare", "farecode", "faretype", "tariff", "tarif", "tarifcode",
        "bestrate", "ratetype",
    ],
    "price_code": [
        "pricecode", "promocode", "promo", "promotion", "campaign", "campaigncode", "offercode",
        "priceid", "aktionscode", "discountcode", "coupon",
    ],
    "currency": ["currency", "curr", "währung"],
    "flight_included": [
        "flight", "withflight", "includeflight", "flightincluded", "flug", "mitflug", "flightpackage",
        "packagetype", "airinclusive",
    ],
}

CABIN_TYPE_WORDS = {
    "inside": "Innenkabine",
    "innen": "Innenkabine",
    "interior": "Innenkabine",
    "oceanview": "Aussenkabine",
    "outside": "Aussenkabine",
    "aussen": "Aussenkabine",
    "balcony": "Balkonkabine",
    "balkon": "Balkonkabine",
    "suite": "Suite",
    "aurea": "Aurea",
    "yachtclub": "MSC Yacht Club",
    "yc": "MSC Yacht Club",
}

TRUTHY = {"1", "true", "yes", "ja", "y", "on", "inkl", "inklusive", "with", "mit", "air", "flight"}
FALSY = {"0", "false", "no", "nein", "n", "off", "ohne", "without", "cruiseonly", "nurschiff"}

SHIP_SLUG_RE = re.compile(r"msc[- ]([a-z]{3,20})", re.IGNORECASE)
ISO_DATE_IN_PATH = re.compile(r"(20\d{2})[-/](\d{2})[-/](\d{2})")


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def normalise_date(value: Any) -> Optional[str]:
    """Return an ISO date string or ``None`` -- never a guessed date."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return (value.date() if isinstance(value, datetime) else value).isoformat()
    text = str(value).strip()
    if not text:
        return None
    text = text.split("T")[0].split(" ")[0]
    patterns = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%d.%m.%y", "%Y.%m.%d"]
    for pattern in patterns:
        try:
            parsed = datetime.strptime(text, pattern).date()
        except ValueError:
            continue
        if 2000 <= parsed.year <= 2100:
            return parsed.isoformat()
    match = ISO_DATE_IN_PATH.search(text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return None
    return None


def _to_int(value: Any, *, low: int = 0, high: int = 40) -> Optional[int]:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        digits = re.findall(r"\d+", str(value or ""))
        if not digits:
            return None
        try:
            number = int(digits[0])
        except ValueError:
            return None
    return number if low <= number <= high else None


def _to_bool(value: Any) -> Optional[bool]:
    token = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    if not token:
        return None
    if token in TRUTHY:
        return True
    if token in FALSY:
        return False
    if "flug" in token or "flight" in token or "air" in token:
        return True
    return None


def _normalise_cabin_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    token = re.sub(r"[^a-z]", "", str(value).lower())
    for needle, label in CABIN_TYPE_WORDS.items():
        if needle in token:
            return label
    return str(value).strip() or None


def is_msc_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return bool(MSC_HOST_RE.search(host))


def parse_msc_url(url: str) -> ParsedUrl:
    parsed = urlparse(url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
    raw: Dict[str, Any] = {}
    for key, value in query_pairs:
        raw.setdefault(key, value)

    lookup = {_norm_key(k): v for k, v in raw.items()}

    def pick(field: str) -> Optional[str]:
        for alias in ALIASES[field]:
            if alias in lookup and str(lookup[alias]).strip():
                return str(lookup[alias]).strip()
        return None

    result = ParsedUrl(provider=PROVIDER_KEY, url=url, raw_params=raw)

    result.external_id = pick("external_id")
    result.ship = pick("ship")
    result.departure_date = normalise_date(pick("departure_date"))
    result.return_date = normalise_date(pick("return_date"))
    result.nights = _to_int(pick("nights"), low=1, high=200)
    result.origin = pick("origin")
    result.destination = pick("destination")
    result.cabin_type = _normalise_cabin_type(pick("cabin_type"))
    result.cabin_category = pick("cabin_category")
    result.adults = _to_int(pick("adults"), low=0, high=20)
    result.children = _to_int(pick("children"), low=0, high=20)
    result.rate_code = pick("rate_code")
    result.price_code = pick("price_code")
    result.currency = (pick("currency") or "").upper() or None
    result.flight_included = _to_bool(pick("flight_included"))

    # --- path heuristics (only used when the query gave us nothing) --------
    path = parsed.path or ""
    if not result.ship:
        match = SHIP_SLUG_RE.search(path.replace("_", "-"))
        if match:
            result.ship = f"MSC {match.group(1).capitalize()}"
    elif result.ship and not result.ship.lower().startswith("msc") and len(result.ship) > 3:
        result.ship = f"MSC {result.ship.strip().capitalize()}"

    if not result.departure_date:
        result.departure_date = normalise_date(path)

    segments = [s for s in path.split("/") if s]
    if not result.destination and len(segments) >= 2 and segments[0].lower() in {
        "kreuzfahrt", "kreuzfahrten", "cruise", "cruises", "reise", "angebote",
    }:
        result.destination = segments[1].replace("-", " ").title()

    # --- consistency: derive only what is mathematically implied ----------
    if result.departure_date and result.return_date and result.nights is None:
        try:
            start = date.fromisoformat(result.departure_date)
            end = date.fromisoformat(result.return_date)
            delta = (end - start).days
            if 1 <= delta <= 200:
                result.nights = delta
        except ValueError:
            pass
    elif result.departure_date and result.nights and not result.return_date:
        try:
            start = date.fromisoformat(result.departure_date)
            result.return_date = (start + timedelta(days=result.nights)).isoformat()
        except ValueError:
            pass

    if result.adults is None and result.children is not None:
        # Never invent a passenger count from a partial hint.
        pass

    if not result.external_id:
        # Long alphanumeric token in the path is often the cruise code.
        for segment in reversed(segments):
            token = segment.strip()
            if 5 <= len(token) <= 24 and re.fullmatch(r"[A-Z0-9]{5,24}", token):
                result.external_id = token
                break

    return result
