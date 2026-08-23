"""Offer identity comparison."""
from __future__ import annotations

from app.comparison.identity import compare_identity, describe_group_differences, group_identical

BASE = {
    "ship": "MSC Euribia",
    "departure_date": "2026-09-11",
    "return_date": "2026-09-18",
    "nights": 7,
    "route": "Kiel - Kopenhagen - Tallinn - Stockholm - Kiel",
    "cabin_type": "Balkonkabine",
    "cabin_category": "BS",
    "tariff": "Fantastica",
    "board": "Vollpension",
    "passenger_count": 2,
    "flight_included": False,
    "drinks_package": None,
}


def test_identical_offers():
    comparison = compare_identity(BASE, dict(BASE))
    assert comparison.identical
    assert comparison.differences == []
    assert "ship" in comparison.compared_fields


def test_different_tariff_is_critical():
    comparison = compare_identity(BASE, dict(BASE, tariff="Bella"))
    assert not comparison.identical
    assert [d.field for d in comparison.differences] == ["tariff"]
    assert comparison.critical_differences
    assert "Tarif" in comparison.summary()


def test_missing_value_is_not_a_difference():
    comparison = compare_identity(BASE, dict(BASE, cabin_category=None))
    assert comparison.identical
    assert "cabin_category" in comparison.not_comparable_fields


def test_case_and_whitespace_insensitive():
    assert compare_identity(BASE, dict(BASE, ship="  msc euribia ")).identical


def test_flight_flag_difference():
    comparison = compare_identity(BASE, dict(BASE, flight_included=True))
    assert not comparison.identical
    assert comparison.differences[0].field == "flight_included"


def test_route_fuzzy_match():
    other = dict(BASE, route="Kiel - Kopenhagen - Tallinn - Stockholm - Kiel ")
    assert compare_identity(BASE, other).identical


def test_grouping_and_description():
    groups = group_identical(
        [
            ("win", BASE),
            ("mac", dict(BASE)),
            ("iphone", dict(BASE, tariff="Bella")),
        ]
    )
    assert len(groups) == 2
    assert set(groups[0]["members"]) == {"win", "mac"}
    described = describe_group_differences(groups)
    assert described and described[0]["differences"][0]["field"] == "tariff"
