"""Neutral scan evaluation."""
from __future__ import annotations

from types import SimpleNamespace

from app.comparison.analysis import build_analysis

IDENTITY = {
    "ship": "MSC Euribia",
    "departure_date": "2026-09-11",
    "nights": 7,
    "tariff": "Fantastica",
    "cabin_category": "BS",
    "passenger_count": 2,
    "flight_included": False,
}


def make(profile, price, *, device="desktop", round_no=1, tariff="Fantastica", session="clean", status="OK"):
    return SimpleNamespace(
        id=hash((profile, price, round_no)) % 10_000,
        profile=profile,
        profile_label=profile,
        device=device,
        browser="chromium",
        platform="Windows",
        cookie_mode="necessary",
        cookie_mode_applied="nur_notwendige",
        referrer=None,
        proxy_name=None,
        session_type=session,
        round=round_no,
        final_price=price,
        total_price=price,
        cabin_price=None,
        currency="EUR",
        tariff=tariff,
        cabin_category="BS",
        screenshot_path="screenshots/x.png",
        status=status,
        error=None,
        identity=dict(IDENTITY, tariff=tariff),
    )


def test_no_difference_wording():
    analysis = build_analysis([make("clean_win_chrome", 2876.0), make("clean_mac_chrome", 2876.0)])
    assert analysis["verdict"] == "no_difference"
    assert analysis["spread_abs"] == 0.0
    assert "kein Preisunterschied festgestellt" in analysis["interpretation"][0]


def test_difference_is_reported_with_savings():
    analysis = build_analysis(
        [
            make("clean_win_chrome", 2876.0),
            make("clean_iphone", 2998.0, device="mobile"),
            make("returning_visitor", 3056.0, session="returning"),
        ]
    )
    assert analysis["verdict"] == "difference"
    assert analysis["spread_abs"] == 180.0
    assert analysis["spread_pct"] == 5.89
    assert analysis["cheapest"]["profile"] == "clean_win_chrome"
    assert analysis["most_expensive"]["profile"] == "returning_visitor"
    assert "180,00" in analysis["savings_text"]
    cheapest_row = [r for r in analysis["rows"] if r["is_cheapest"]]
    assert len(cheapest_row) == 1
    assert [r["diff_to_cheapest"] for r in analysis["rows"]] == [0.0, 122.0, 180.0]


def test_no_premature_conclusion_but_hypotheses():
    analysis = build_analysis(
        [make("clean_win_chrome", 2876.0), make("clean_iphone", 2998.0, device="mobile")]
    )
    joined = " ".join(analysis["interpretation"]).lower()
    assert "device pricing" not in joined
    assert "nicht bewiesen" in joined
    causes = analysis["cause_hypotheses"][0]["possible_causes"]
    assert any("Device-Effekt" in cause for cause in causes)
    assert analysis["cause_hypotheses"][0]["confidence"].startswith("Hypothese")


def test_reproduced_three_times():
    results = []
    for round_no in (1, 2, 3):
        results.append(make("clean_win_chrome", 2876.0, round_no=round_no))
        results.append(make("clean_iphone", 2998.0, device="mobile", round_no=round_no))
    analysis = build_analysis(results, rounds_planned=3)
    assert analysis["reproducibility"]["status"] == "reproduced"
    assert analysis["reproducibility"]["text"] == "Preisunterschied 3x reproduziert."


def test_dynamic_prices_are_flagged():
    results = [
        make("clean_win_chrome", 2876.0, round_no=1),
        make("clean_win_chrome", 2911.0, round_no=2),
        make("clean_iphone", 2998.0, device="mobile", round_no=1),
        make("clean_iphone", 2998.0, device="mobile", round_no=2),
    ]
    analysis = build_analysis(results, rounds_planned=2)
    assert analysis["reproducibility"]["status"] == "dynamic"
    assert analysis["reproducibility"]["text"] == "Preis dynamisch / Ergebnis nicht eindeutig."


def test_different_offers_are_not_compared():
    analysis = build_analysis(
        [make("clean_win_chrome", 2876.0), make("clean_iphone", 2666.0, device="mobile", tariff="Bella")]
    )
    assert analysis["verdict"] == "not_comparable"
    assert analysis["headline"] == "Angebote unterscheiden sich"
    assert "nicht direkt verglichen" in analysis["interpretation"][0]
    assert analysis["identity_differences"][0]["differences"][0]["field"] == "tariff"


def test_missing_prices_do_not_become_numbers():
    analysis = build_analysis(
        [
            make("clean_win_chrome", None, status="PRICE_NOT_FOUND"),
            make("clean_iphone", None, device="mobile", status="BLOCKED_CAPTCHA"),
        ]
    )
    assert analysis["verdict"] == "insufficient_data"
    assert analysis.get("lowest_price") is None
    assert any("blockiert" in warning for warning in analysis["warnings"])
    assert all(row["price"] is None for row in analysis["rows"])


def test_blocked_profiles_are_excluded_but_reported():
    analysis = build_analysis(
        [
            make("clean_win_chrome", 2876.0),
            make("clean_mac_chrome", 2876.0),
            make("clean_iphone", None, device="mobile", status="BLOCKED_CAPTCHA"),
        ]
    )
    assert analysis["verdict"] == "no_difference"
    assert analysis["profiles_with_price"] == 2
    assert any("CAPTCHA" in warning for warning in analysis["warnings"])


def test_empty_input():
    analysis = build_analysis([])
    assert analysis["verdict"] == "insufficient_data"
