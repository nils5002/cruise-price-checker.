"""Deterministic mock provider.

Purpose: exercise the *entire* pipeline (scan -> results -> comparison ->
history -> alerts -> UI) without touching a real website.  Every value it
produces is clearly marked as demo data.

URL shape::

    mock://cruise/<id>?variant=<default|dynamic|blocked|noprice|identity>&adults=2

Variants:
  default   stable prices, iPhone + returning visitor are more expensive
  dynamic   prices jitter on every run   -> "Preis dynamisch"
  blocked   simulates a CAPTCHA wall     -> BLOCKED_CAPTCHA
  blocked_all  jedes Profil wird blockiert -> Scan bricht ab
  noprice   page loads but no price      -> PRICE_NOT_FOUND
  identity  one profile shows a different tariff -> "Angebote unterscheiden sich"
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlparse

from app.providers.base import (
    CruiseProvider,
    FlowResult,
    ParsedUrl,
    PriceBreakdown,
    RunContext,
    Status,
    TripDetails,
)

# Smallest valid PNG (1x1, transparent) so artifact handling can be tested.
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)

BASE_PRICE = 2876.0
PROFILE_DELTA = {
    "clean_win_chrome": 0.0,
    "clean_mac_chrome": 0.0,
    "clean_iphone": 122.0,
    "clean_android": 0.0,
    "clean_firefox": 0.0,
    "returning_visitor": 180.0,
}


class MockProvider(CruiseProvider):
    key = "mock"
    label = "Mock (Demo/Test)"
    requires_browser = False
    allowed_hosts = ()

    # ------------------------------------------------------------------
    def can_handle_url(self, url: str) -> bool:
        return str(url or "").startswith("mock://")

    def parse_url(self, url: str) -> ParsedUrl:
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query))
        identifier = (parsed.path or "/demo").strip("/") or "demo"
        adults = int(params.get("adults", 2) or 2)
        children = int(params.get("children", 0) or 0)
        return ParsedUrl(
            provider=self.key,
            url=url,
            external_id=identifier,
            ship="MSC Euribia (Demo)",
            departure_date="2026-09-11",
            return_date="2026-09-18",
            nights=7,
            origin="Kiel",
            destination="Nordeuropa",
            cabin_type="Balkonkabine",
            cabin_category="BS",
            adults=adults,
            children=children,
            rate_code="Fantastica",
            price_code="DEMO",
            flight_included=False,
            currency="EUR",
            raw_params={**params, "variant": params.get("variant", "default")},
        )

    # -- helpers -------------------------------------------------------
    def _variant(self, ctx: RunContext) -> str:
        if ctx.parsed_url and ctx.parsed_url.raw_params:
            return str(ctx.parsed_url.raw_params.get("variant", "default"))
        return "default"

    def _jitter(self, ctx: RunContext) -> float:
        seed = f"{ctx.scan_id}-{ctx.profile_key}-{ctx.round}"
        digest = hashlib.sha256(seed.encode()).hexdigest()
        return float(int(digest[:4], 16) % 7) * 13.0

    # -- interface -----------------------------------------------------
    def open_offer(self, ctx: RunContext, url: str) -> None:
        ctx.log(f"(Mock) Angebot geoeffnet: {url}", step="open_offer", url=url)

    def accept_cookies(self, ctx: RunContext, mode: str) -> str:
        applied = {"all": "alle_akzeptiert", "necessary": "nur_notwendige", "none": "banner_ignoriert"}.get(
            mode, "nur_notwendige"
        )
        ctx.cookie_mode_applied = applied
        ctx.log(f"(Mock) Cookie-Variante angewendet: {applied}", step="cookies")
        return applied

    def extract_trip_details(self, ctx: RunContext) -> TripDetails:
        parsed = ctx.parsed_url
        tariff = "Fantastica"
        if self._variant(ctx) == "identity" and ctx.profile_key == "clean_iphone":
            tariff = "Bella"  # deliberately a different offer
        return TripDetails(
            ship=(parsed.ship if parsed else "MSC Euribia (Demo)"),
            departure_date="2026-09-11",
            return_date="2026-09-18",
            nights=7,
            route="Kiel - Kopenhagen - Tallinn - Stockholm - Kiel (Demo)",
            origin="Kiel",
            destination="Nordeuropa",
            cabin_type="Balkonkabine",
            cabin_category="BS",
            tariff=tariff,
            board="Vollpension",
            adults=(parsed.adults if parsed else 2),
            children=(parsed.children if parsed else 0),
            passenger_count=(parsed.passenger_count if parsed else 2),
            flight_included=False,
            drinks_package=None,
            cancellation_terms="Umbuchung kostenpflichtig (Demo)",
            offer_name="Demo-Angebot Nordeuropa",
            price_code="DEMO",
            currency="EUR",
        )

    def select_cabin(self, ctx: RunContext, preferred: Optional[str] = None) -> Optional[str]:
        ctx.log("(Mock) Kabinenkategorie BS gewählt.", step="select_cabin")
        return "BS"

    def select_rate(self, ctx: RunContext, preferred: Optional[str] = None) -> Optional[str]:
        details = self.extract_trip_details(ctx)
        ctx.log(f"(Mock) Tarif {details.tariff} gewählt.", step="select_rate")
        return details.tariff

    def extract_price(self, ctx: RunContext) -> PriceBreakdown:
        return PriceBreakdown(currency="EUR", starting_price=799.0).stamp()

    def extract_final_price(self, ctx: RunContext) -> PriceBreakdown:
        variant = self._variant(ctx)
        if variant == "noprice":
            return PriceBreakdown(currency="EUR").stamp()
        total = BASE_PRICE + PROFILE_DELTA.get(ctx.profile_key, 0.0)
        if variant == "dynamic":
            total += self._jitter(ctx)
        if variant == "identity" and ctx.profile_key == "clean_iphone":
            total = BASE_PRICE - 210.0  # cheaper, but a different tariff
        passengers = (ctx.parsed_url.passenger_count if ctx.parsed_url else 2) or 2
        details = self.extract_trip_details(ctx)
        return PriceBreakdown(
            currency="EUR",
            starting_price=799.0,
            price_per_person=round(total / passengers, 2),
            cabin_price=total,
            total_price=total,
            service_fee=round(passengers * 49.0, 2),
            flight_price=None,
            transfer_price=None,
            drinks_package_price=None,
            extras_price=None,
            discount=None,
            final_price=total,
            promo_code="DEMO",
            tariff=details.tariff,
            cabin_category="BS",
            offer_name="Demo-Angebot Nordeuropa",
            price_code="DEMO",
            source_labels={"final_price": "mock"},
        ).stamp()

    def take_snapshot(self, ctx: RunContext, name: str) -> Dict[str, Any]:
        artifact = {
            "name": name,
            "url": f"mock://step/{name}",
            "page_type": ctx.page_type,
            "screenshot": ctx.save_screenshot(name),
            "html": ctx.save_html(name),
        }
        ctx.artifacts.append(artifact)
        return artifact

    def detect_page_type(self, ctx: RunContext) -> str:
        ctx.page_type = "summary"
        return "summary"

    # -- flow ----------------------------------------------------------
    def run_flow(self, ctx: RunContext, url: str) -> FlowResult:
        result = FlowResult()
        self.open_offer(ctx, url)
        result.cookie_mode_applied = self.accept_cookies(ctx, ctx.cookie_mode)
        variant = self._variant(ctx)

        self.detect_page_type(ctx)
        self.take_snapshot(ctx, "01-angebot-start")

        if variant == "blocked_all" or (
            variant == "blocked" and ctx.profile_key in ("clean_iphone", "clean_firefox")
        ):
            result.status = Status.BLOCKED_CAPTCHA
            result.error = "(Mock) CAPTCHA erkannt - Test wurde sauber beendet."
            result.deepest_step = "offer_start"
            result.trip = self.extract_trip_details(ctx)
            return result

        result.trip = self.extract_trip_details(ctx)
        self.select_cabin(ctx)
        self.take_snapshot(ctx, "03-kabinenauswahl")
        self.select_rate(ctx)
        self.take_snapshot(ctx, "04-tarifauswahl")
        prices = self.extract_price(ctx).merge(self.extract_final_price(ctx))
        self.take_snapshot(ctx, "05-preisuebersicht")
        self.take_snapshot(ctx, "06-zusammenfassung")

        result.prices = prices
        result.page_type = "summary"
        result.final_url = f"{url}#zusammenfassung"
        result.deepest_step = "summary"
        result.status = Status.OK if prices.final_price is not None else Status.PRICE_NOT_FOUND
        if prices.final_price is None:
            result.error = "Preis konnte nicht zuverlässig ermittelt werden."
        return result


def write_placeholder_png(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(PNG_1PX)
