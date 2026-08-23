"""MSC URL parser."""
from __future__ import annotations

import pytest

from app.providers.msc.url_parser import is_msc_url, normalise_date, parse_msc_url


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.msccruises.de/booking?x=1", True),
        ("https://msccruises.de/kreuzfahrt/x", True),
        ("https://book.msccruises.de/x", True),
        ("https://www.msccruises.com/x", True),
        ("https://www.e-hoi.de/x", False),
        ("https://msccruises.de.evil.com/x", False),
        ("nonsense", False),
    ],
)
def test_is_msc_url(url, expected):
    assert is_msc_url(url) is expected


def test_parses_full_query():
    parsed = parse_msc_url(
        "https://www.msccruises.de/booking?cruiseId=EUB26091&ship=euribia"
        "&departureDate=11.09.2026&returnDate=18.09.2026&adults=2&children=1"
        "&cabinType=balcony&cabinCategory=BS&rate=Fantastica&promoCode=SUMMER26"
        "&flight=ja&port=Kiel&currency=EUR"
    )
    assert parsed.provider == "msc"
    assert parsed.external_id == "EUB26091"
    assert parsed.ship == "MSC Euribia"
    assert parsed.departure_date == "2026-09-11"
    assert parsed.return_date == "2026-09-18"
    assert parsed.nights == 7
    assert parsed.adults == 2 and parsed.children == 1
    assert parsed.passenger_count == 3
    assert parsed.cabin_type == "Balkonkabine"
    assert parsed.cabin_category == "BS"
    assert parsed.rate_code == "Fantastica"
    assert parsed.price_code == "SUMMER26"
    assert parsed.flight_included is True
    assert parsed.origin == "Kiel"
    assert parsed.currency == "EUR"


def test_derives_return_date_from_nights():
    parsed = parse_msc_url("https://www.msccruises.de/booking?departureDate=2026-09-11&nights=7")
    assert parsed.return_date == "2026-09-18"


def test_path_heuristics():
    parsed = parse_msc_url("https://www.msccruises.de/kreuzfahrt/nordeuropa/msc-euribia/2026-09-11/EUB26091")
    assert parsed.ship == "MSC Euribia"
    assert parsed.departure_date == "2026-09-11"
    assert parsed.destination == "Nordeuropa"
    assert parsed.external_id == "EUB26091"


def test_unknown_values_stay_none():
    parsed = parse_msc_url("https://www.msccruises.de/booking?foo=bar")
    assert parsed.ship is None
    assert parsed.departure_date is None
    assert parsed.adults is None
    assert parsed.passenger_count is None
    assert parsed.flight_included is None
    assert parsed.raw_params == {"foo": "bar"}


def test_implausible_values_are_rejected():
    parsed = parse_msc_url("https://www.msccruises.de/booking?adults=99&nights=999&departureDate=99.99.9999")
    assert parsed.adults is None
    assert parsed.nights is None
    assert parsed.departure_date is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-09-11", "2026-09-11"),
        ("11.09.2026", "2026-09-11"),
        ("20260911", "2026-09-11"),
        ("2026-09-11T10:00:00", "2026-09-11"),
        ("kaputt", None),
        ("", None),
        (None, None),
    ],
)
def test_normalise_date(value, expected):
    assert normalise_date(value) == expected


def test_flight_flag_variants():
    assert parse_msc_url("https://www.msccruises.de/b?flight=nein").flight_included is False
    assert parse_msc_url("https://www.msccruises.de/b?withFlight=1").flight_included is True
    assert parse_msc_url("https://www.msccruises.de/b?packageType=cruiseonly").flight_included is False
