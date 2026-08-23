"""MSC adapter: text-driven extraction, page classification, booking guard.

A minimal fake page stands in for Playwright so these tests never touch the
network.  They cover exactly the parts that must stay correct when MSC changes
its markup: the text-driven price/trip extraction and the safety guards.
"""
from __future__ import annotations

import pytest

from app.providers.base import RunContext, Status
from app.providers.msc.adapter import MscProvider

SUMMARY_PAGE = """MSC Cruises
Buchungsübersicht
MSC Euribia
11.09.2026 - 18.09.2026
7 Nächte
Kiel - Kopenhagen - Tallinn - Stockholm - Kiel
Balkonkabine
Kabinenkategorie BS
Fantastica
Vollpension
2 Erwachsene
Preis pro Person
1.438,00 €
Kabinenpreis
2.876,00 €
Servicegebühr
98,00 €
Getränkepaket
0,00 €
Gesamtpreis
2.974,00 €
Aktionscode: SUMMER26
Kostenlose Umbuchung bis 30 Tage vor Abreise
Weiter zu den Reisedaten
"""

CABIN_PAGE = """Kabinenkategorie wählen
Innenkabine ab 799 €
Balkonkabine ab 1.099 €
Deckplan ansehen
"""

BLOCKED_PAGE = """Attention Required! Cloudflare
Just a moment...
Bitte bestätigen Sie, dass Sie ein Mensch sind.
"""


class FakeLocator:
    def count(self):
        return 0


class FakePage:
    """Just enough of the Playwright Page API for text-driven extraction."""

    def __init__(self, text: str, url: str = "https://www.msccruises.de/booking/summary"):
        self._text = text
        self.url = url

    def inner_text(self, _selector="body", **_kwargs):
        return self._text

    def content(self):
        return f"<html><body>{self._text}</body></html>"

    def title(self):
        return "MSC Cruises"

    def locator(self, *_args, **_kwargs):
        return FakeLocator()

    def get_by_role(self, *_args, **_kwargs):
        return FakeLocator()

    def get_by_text(self, *_args, **_kwargs):
        return FakeLocator()

    def get_by_label(self, *_args, **_kwargs):
        return FakeLocator()

    def get_by_placeholder(self, *_args, **_kwargs):
        return FakeLocator()

    def evaluate(self, *_args, **_kwargs):
        return False


def make_ctx(page, profile="clean_win_chrome"):
    return RunContext(
        scan_id=1,
        profile_key=profile,
        profile_label=profile,
        device="desktop",
        browser="chromium",
        cookie_mode="necessary",
        referrer="direct",
        proxy_name=None,
        session_type="clean",
        round=1,
        page=page,
    )


@pytest.fixture()
def provider():
    return MscProvider()


def test_prices_are_read_from_summary_text(provider):
    ctx = make_ctx(FakePage(SUMMARY_PAGE))
    prices = provider.extract_final_price(ctx)
    assert prices.total_price == 2974.0
    assert prices.final_price == 2974.0        # taken over from the total
    assert prices.price_per_person == 1438.0
    assert prices.cabin_price == 2876.0
    assert prices.service_fee == 98.0
    assert prices.promo_code == "SUMMER26"
    assert prices.currency == "EUR"
    assert prices.tariff == "Fantastica"
    # values that are not on the page must stay None
    assert prices.flight_price is None
    assert prices.transfer_price is None
    assert prices.discount is None


def test_trip_details_are_read_from_page(provider):
    details = provider.extract_trip_details(make_ctx(FakePage(SUMMARY_PAGE)))
    assert details.ship == "MSC Euribia"
    assert details.departure_date == "2026-09-11"
    assert details.return_date == "2026-09-18"
    assert details.nights == 7
    assert details.adults == 2
    assert details.tariff == "Fantastica"
    assert details.cabin_type == "Balkonkabine"
    assert details.board == "Vollpension"
    assert details.cancellation_terms is not None
    assert details.price_code == "SUMMER26"


def test_starting_price_only_page(provider):
    prices = provider.extract_price(make_ctx(FakePage(CABIN_PAGE)))
    assert prices.starting_price == 799.0
    assert prices.final_price is None
    assert prices.total_price is None


def test_page_type_detection(provider):
    assert provider.detect_page_type(make_ctx(FakePage(SUMMARY_PAGE))) == "summary"
    assert provider.detect_page_type(make_ctx(FakePage(CABIN_PAGE))) == "cabin_category"
    assert provider.detect_page_type(make_ctx(FakePage("Zahlungsart Kreditkartennummer IBAN"))) == "payment"
    assert provider.detect_page_type(make_ctx(FakePage("Vorname Nachname Geburtsdatum Reisepass"))) == "passenger_data"


def test_block_detection_is_reported_not_bypassed(provider):
    ctx = make_ctx(FakePage(BLOCKED_PAGE))
    kind = provider.detect_block(ctx)
    assert kind in (Status.BLOCKED_CAPTCHA, Status.BOT_PROTECTION)


@pytest.mark.parametrize(
    "label",
    [
        "Jetzt zahlungspflichtig buchen",
        "Buchung abschließen",
        "Verbindlich buchen",
        "Jetzt bezahlen",
        "Zur Kasse",
        "Mit Kreditkarte bezahlen",
        "Pay now",
        "Complete booking",
    ],
)
def test_booking_buttons_are_never_clicked(provider, label):
    assert provider._is_forbidden(label) is True


@pytest.mark.parametrize(
    "label",
    ["Weiter zur Kabinenauswahl", "Preise und Verfügbarkeit", "Alle akzeptieren", "Auswählen", "Weiter"],
)
def test_navigation_buttons_are_allowed(provider, label):
    assert provider._is_forbidden(label) is False


def test_guarded_click_refuses_booking_button(provider):
    class Locator:
        def __init__(self):
            self.clicked = False

        def inner_text(self, **_kwargs):
            return "Jetzt zahlungspflichtig buchen"

        def get_attribute(self, _name):
            return None

        def scroll_into_view_if_needed(self, **_kwargs):
            return None

        def click(self, **_kwargs):
            self.clicked = True

    locator = Locator()
    messages = []
    ctx = make_ctx(FakePage(SUMMARY_PAGE))
    ctx.record_step = lambda message="", step=None, level="INFO", **kw: messages.append(message)
    assert provider._guarded_click(ctx, locator, "continue") is False
    assert locator.clicked is False
    assert any("NICHT ausgeführt" in m for m in messages)


def test_cookie_modes_report_what_happened(provider):
    ctx = make_ctx(FakePage(SUMMARY_PAGE))
    # no banner in the fake page -> honest report instead of a false claim
    assert provider.accept_cookies(ctx, "necessary") == "kein_banner"
    assert ctx.cookie_mode_applied == "kein_banner"


def test_provider_declares_msc_hosts(provider):
    assert provider.can_handle_url("https://www.msccruises.de/booking?x=1")
    assert not provider.can_handle_url("https://www.dreamlines.de/x")
    assert provider.requires_browser is True


@pytest.mark.parametrize(
    "text,expected",
    [
        ("MSC Cruises Startseite", None),                      # brand header, not a ship
        ("Ihre Reise mit MSC Euribia ab Kiel", "MSC Euribia"),
        ("MSC World Europa, 7 Nächte", "MSC World Europa"),
        ("MSC Cruises\nMSC Grandiosa\nBella", "MSC Grandiosa"),
        ("MSC Yacht Club Suite", None),
        ("Kein Schiff genannt", None),
    ],
)
def test_ship_detection(text, expected):
    from app.providers.msc.adapter import _detect_ship

    assert _detect_ship(text) == expected


def test_payment_marker_does_not_match_reisepass(provider):
    """'sepa' must not match inside 'Reisepass'."""
    assert provider.detect_page_type(make_ctx(FakePage("Reisepass Vorname"))) == "passenger_data"
    assert provider.detect_page_type(make_ctx(FakePage("Zahlung per SEPA-Lastschrift"))) == "payment"
