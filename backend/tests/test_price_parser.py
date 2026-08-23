"""Price parsing: correct values or None -- never a guess."""
from __future__ import annotations

import pytest

from app.providers.msc.price_parser import (
    classify_label,
    detect_block,
    detect_price_changed,
    detect_session_expired,
    detect_sold_out,
    find_promo_code,
    parse_amount,
    parse_amounts,
    parse_breakdown_lines,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ab 799 €", 799.0),
        ("2.876,00 €", 2876.0),
        ("2.876 €", 2876.0),
        ("€ 1.234", 1234.0),
        ("1 234,50 EUR", 1234.5),
        ("2876", 2876.0),
        ("Gesamt: 3.056,00 EUR", 3056.0),
        ("2,876.00 USD", 2876.0),
    ],
)
def test_parse_amount_valid(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "kein Preis",
        "ab 799 € statt 899 €",   # ambiguous -> refuse
        "0,99 €",                  # implausible
        "12,50",                   # below plausibility floor
        "999.999.999 €",           # implausible
    ],
)
def test_parse_amount_refuses(text):
    assert parse_amount(text) is None


def test_parse_amounts_lists_all():
    assert parse_amounts("ab 799 € statt 899 €") == [799.0, 899.0]


@pytest.mark.parametrize(
    "label,field",
    [
        ("Gesamtpreis", "total_price"),
        ("Gesamtpreis inkl. Flug", "total_price"),
        ("Gesamtpreis pro Person", "price_per_person"),
        ("Endpreis", "final_price"),
        ("zu zahlender Gesamtbetrag", "final_price"),
        ("Kabinenpreis", "cabin_price"),
        ("Servicegebühr pro Person", "service_fee"),
        ("Hafengebühren und Steuern", "service_fee"),
        ("Flugpreis", "flight_price"),
        ("Transfer", "transfer_price"),
        ("Getränkepaket", "drinks_package_price"),
        ("Ausflugspaket", "extras_price"),
        ("Rabatt", "discount"),
        ("Sie sparen", "discount"),
        ("ab 799 €", "starting_price"),
        ("Irgendwas", None),
    ],
)
def test_classify_label(label, field):
    assert classify_label(label) == field


def test_parse_breakdown_lines():
    lines = [
        "Gesamtpreis 2.876,00 €",
        "Preis pro Person 1.438,00 €",
        "Servicegebühr 98,00 €",
        "Flugpreis 340,00 €",
        "Getränkepaket 210,00 €",
        "Rabatt -150,00 €",
        "Endpreis 3.056,00 €",
        "Werbetext ohne Preis",
    ]
    result = parse_breakdown_lines(lines)
    assert result == {
        "total_price": 2876.0,
        "price_per_person": 1438.0,
        "service_fee": 98.0,
        "flight_price": 340.0,
        "drinks_package_price": 210.0,
        "discount": 150.0,
        "final_price": 3056.0,
    }


def test_promo_code():
    assert find_promo_code("Aktionscode: SUMMER26 gültig bis") == "SUMMER26"
    assert find_promo_code("kein code hier") is None


def test_state_detection():
    assert detect_block("Just a moment... Cloudflare")
    assert detect_block("Bitte bestätigen Sie das CAPTCHA")
    assert detect_sold_out("Diese Kabine ist leider ausverkauft")
    assert detect_session_expired("Ihre Sitzung ist abgelaufen")
    assert detect_price_changed("Der Preis hat sich geändert")
    assert detect_block("Alles normal hier") is None
