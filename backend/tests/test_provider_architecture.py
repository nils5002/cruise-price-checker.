"""Provider architecture: a new vendor needs the interface -- nothing else."""
from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from app.providers.base import (
    CruiseProvider,
    ParsedUrl,
    PriceBreakdown,
    RunContext,
    Status,
    TripDetails,
)
from app.providers.registry import get_provider, provider_for_url, provider_info, register


class DemoVendorProvider(CruiseProvider):
    """Minimal adapter: only the required methods, no own run_flow."""

    key = "demovendor"
    label = "Demo Vendor"
    requires_browser = False

    def can_handle_url(self, url: str) -> bool:
        return url.startswith("demo://")

    def parse_url(self, url: str) -> ParsedUrl:
        return ParsedUrl(provider=self.key, url=url, ship="Demo Ship", adults=2)

    def open_offer(self, ctx: RunContext, url: str) -> None:
        ctx.log("geoeffnet", step="open_offer")

    def accept_cookies(self, ctx: RunContext, mode: str) -> str:
        return "nur_notwendige"

    def extract_trip_details(self, ctx: RunContext) -> TripDetails:
        return TripDetails(ship="Demo Ship", nights=7, tariff="Basis", passenger_count=2)

    def select_cabin(self, ctx: RunContext, preferred: Optional[str] = None) -> Optional[str]:
        return "AA"

    def select_rate(self, ctx: RunContext, preferred: Optional[str] = None) -> Optional[str]:
        return "Basis"

    def extract_price(self, ctx: RunContext) -> PriceBreakdown:
        return PriceBreakdown(currency="EUR", starting_price=500.0)

    def extract_final_price(self, ctx: RunContext) -> PriceBreakdown:
        return PriceBreakdown(currency="EUR", total_price=1999.0, final_price=1999.0)

    def take_snapshot(self, ctx: RunContext, name: str) -> Dict[str, Any]:
        artifact = {"name": name, "screenshot": None, "html": None}
        ctx.artifacts.append(artifact)
        return artifact


class PriceLessProvider(DemoVendorProvider):
    key = "pricelessvendor"

    def extract_price(self, ctx: RunContext) -> PriceBreakdown:
        return PriceBreakdown(currency="EUR")

    def extract_final_price(self, ctx: RunContext) -> PriceBreakdown:
        return PriceBreakdown(currency="EUR")


def make_ctx() -> RunContext:
    return RunContext(
        scan_id=1,
        profile_key="clean_win_chrome",
        profile_label="Clean Windows",
        device="desktop",
        browser="chromium",
        cookie_mode="necessary",
        referrer="direct",
        proxy_name=None,
        session_type="clean",
        round=1,
    )


def test_default_flow_works_without_custom_orchestration():
    provider = DemoVendorProvider()
    ctx = make_ctx()
    result = provider.run_flow(ctx, "demo://offer/1")
    assert result.status == Status.OK
    assert result.prices.final_price == 1999.0
    assert result.prices.starting_price == 500.0     # merged from the listing page
    assert result.trip.ship == "Demo Ship"
    assert result.deepest_step == "summary"
    names = [artifact["name"] for artifact in ctx.artifacts]
    assert names == ["01-angebot-start", "03-kabinenauswahl", "04-tarifauswahl", "05-preisuebersicht"]


def test_default_flow_reports_missing_price_instead_of_guessing():
    result = PriceLessProvider().run_flow(make_ctx(), "demo://offer/2")
    assert result.status == Status.PRICE_NOT_FOUND
    assert result.prices.final_price is None
    assert "nicht zuverlässig" in (result.error or "")


def test_registry_accepts_new_providers():
    provider = DemoVendorProvider()
    register(provider)
    assert get_provider("demovendor") is provider
    assert provider_for_url("demo://offer/1") is provider
    assert provider_for_url("https://www.msccruises.de/booking?x=1").key == "msc"


def test_planned_providers_are_listed():
    keys = {entry["key"] for entry in provider_info()}
    assert {"msc"} <= keys
    for planned in ("ehoi", "kreuzfahrtberater", "dreamlines", "logitravel", "holidaycheck", "check24"):
        assert planned in keys


def test_interface_is_enforced():
    class Incomplete(CruiseProvider):
        key = "incomplete"

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]
