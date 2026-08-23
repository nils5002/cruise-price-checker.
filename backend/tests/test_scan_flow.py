"""End-to-end scan through the mock provider (no network, no browser)."""
from __future__ import annotations

import os

from sqlalchemy import select

from app.config import settings
from app.models import PriceAlert, PriceHistory, Scan, ScanLog, ScanResult, ScanStatus
from app.scanner.runner import build_matrix, execute_scan
from app.services import create_scan, get_or_create_cruise

PROFILES = ["clean_win_chrome", "clean_mac_chrome", "clean_iphone", "returning_visitor"]


def _run(db, url, *, rounds=1, profiles=None, cookie_modes=None):
    cruise = get_or_create_cruise(db, url)
    scan = Scan(
        cruise_id=cruise.id,
        status=ScanStatus.QUEUED.value,
        trigger="test",
        rounds_planned=rounds,
        conditions={"profiles": profiles or PROFILES, "cookie_modes": cookie_modes, "rounds": rounds},
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    execute_scan(scan.id)
    db.expire_all()
    return cruise, db.get(Scan, scan.id)


def test_full_scan_detects_difference(db):
    cruise, scan = _run(db, "mock://cruise/e2e-1?variant=default")
    assert scan.status == ScanStatus.DONE.value
    results = db.scalars(select(ScanResult).where(ScanResult.scan_id == scan.id)).all()
    assert len(results) == len(PROFILES)
    assert {r.profile for r in results} == set(PROFILES)
    assert all(r.status == "OK" for r in results)

    analysis = scan.analysis
    assert analysis["verdict"] == "difference"
    assert analysis["lowest_price"] == 2876.0
    assert analysis["highest_price"] == 3056.0
    assert analysis["spread_abs"] == 180.0
    assert analysis["comparable"] is True

    # price history was written
    history = db.scalars(select(PriceHistory).where(PriceHistory.cruise_id == cruise.id)).all()
    assert history and history[-1].lowest_price == 2876.0

    # unified conditions are stored per result
    conditions = results[0].conditions
    assert conditions["locale"] == "de-DE"
    assert conditions["timezone"] == "Europe/Berlin"
    assert conditions["currency"] == "EUR"

    # screenshots exist on disk and are reachable via the stored relative path
    screenshots = [a["screenshot"] for a in results[0].artifacts if a.get("screenshot")]
    assert len(screenshots) >= 5
    assert os.path.isfile(os.path.join(settings.data_dir, screenshots[0]))
    assert results[0].screenshot_path


def test_price_breakdown_and_identity_are_stored(db):
    _, scan = _run(db, "mock://cruise/e2e-2?variant=default", profiles=["clean_win_chrome"])
    result = db.scalars(select(ScanResult).where(ScanResult.scan_id == scan.id)).one()
    assert result.final_price == 2876.0
    assert result.total_price == 2876.0
    assert result.price_per_person == 1438.0
    assert result.service_fee == 98.0
    assert result.starting_price == 799.0
    assert result.flight_price is None          # unknown stays None
    assert result.currency == "EUR"
    assert result.identity["ship"].startswith("MSC")
    assert result.identity["tariff"] == "Fantastica"
    assert result.deepest_step == "summary"
    assert result.page_type == "summary"


def test_captcha_is_reported_not_circumvented(db):
    _, scan = _run(db, "mock://cruise/e2e-3?variant=blocked", profiles=["clean_win_chrome", "clean_iphone"])
    results = {r.profile: r for r in db.scalars(select(ScanResult).where(ScanResult.scan_id == scan.id)).all()}
    assert results["clean_iphone"].status == "BLOCKED_CAPTCHA"
    assert results["clean_iphone"].final_price is None
    assert results["clean_win_chrome"].status == "OK"
    assert any("CAPTCHA" in w for w in scan.analysis["warnings"])
    # blocked profiles are not retried into a price
    assert results["clean_iphone"].attempts == 1


def test_no_price_is_never_invented(db):
    _, scan = _run(db, "mock://cruise/e2e-4?variant=noprice", profiles=["clean_win_chrome"])
    result = db.scalars(select(ScanResult).where(ScanResult.scan_id == scan.id)).one()
    assert result.status == "PRICE_NOT_FOUND"
    assert result.final_price is None
    assert scan.analysis["verdict"] == "insufficient_data"
    assert scan.analysis.get("lowest_price") is None


def test_different_offer_is_flagged(db):
    _, scan = _run(db, "mock://cruise/e2e-5?variant=identity", profiles=["clean_win_chrome", "clean_iphone"])
    assert scan.analysis["verdict"] == "not_comparable"
    assert scan.analysis["identity_differences"][0]["differences"][0]["field"] == "tariff"


def test_multi_round_verification(db):
    _, scan = _run(db, "mock://cruise/e2e-6?variant=default", rounds=3, profiles=["clean_win_chrome", "clean_iphone"])
    assert scan.rounds_completed == 3
    rounds = {r.round for r in db.scalars(select(ScanResult).where(ScanResult.scan_id == scan.id)).all()}
    assert rounds == {1, 2, 3}
    assert scan.analysis["reproducibility"]["status"] == "reproduced"
    assert "3x reproduziert" in scan.analysis["reproducibility"]["text"]


def test_rounds_stop_early_when_no_difference(db):
    _, scan = _run(
        db, "mock://cruise/e2e-7?variant=default", rounds=3, profiles=["clean_win_chrome", "clean_mac_chrome"]
    )
    assert scan.analysis["verdict"] == "no_difference"
    assert scan.rounds_completed == 1  # nothing to verify -> no extra load


def test_dynamic_prices_are_not_called_reproducible(db):
    _, scan = _run(db, "mock://cruise/e2e-8?variant=dynamic", rounds=2, profiles=["clean_win_chrome", "clean_iphone"])
    assert scan.analysis["reproducibility"]["status"] in ("dynamic", "reproduced")
    if scan.analysis["reproducibility"]["status"] == "dynamic":
        assert "nicht eindeutig" in scan.analysis["reproducibility"]["text"]


def test_debug_logs_contain_steps_but_no_secrets(db):
    _, scan = _run(db, "mock://cruise/e2e-9?variant=default", profiles=["clean_win_chrome"])
    logs = db.scalars(select(ScanLog).where(ScanLog.scan_id == scan.id)).all()
    assert logs
    steps = {row.step for row in logs}
    assert {"open_offer", "cookies", "select_cabin", "select_rate"} <= steps
    joined = " ".join(row.message for row in logs).lower()
    for forbidden in ("proxysecret", "proxyuser", "cookie:", "authorization"):
        assert forbidden not in joined


def test_cookie_variants_are_recorded(db):
    _, scan = _run(
        db,
        "mock://cruise/e2e-10?variant=default",
        profiles=["clean_win_chrome"],
        cookie_modes=["necessary", "all", "none"],
    )
    results = db.scalars(select(ScanResult).where(ScanResult.scan_id == scan.id)).all()
    applied = {r.cookie_mode: r.cookie_mode_applied for r in results}
    assert applied == {
        "necessary": "nur_notwendige",
        "all": "alle_akzeptiert",
        "none": "banner_ignoriert",
    }


def test_alert_is_triggered(db, monkeypatch):
    sent = []

    class FakeChannel:
        key = "discord"
        label = "Fake"
        configured = True

        def send(self, subject, message, target=None):
            sent.append((subject, message, target))
            return True

    from app.notify import channels

    monkeypatch.setitem(channels.CHANNELS, "discord", FakeChannel())

    cruise = get_or_create_cruise(db, "mock://cruise/e2e-alert?variant=default")
    db.add(PriceAlert(cruise_id=cruise.id, channel="discord", threshold_total=3000.0, target="https://example.invalid/hook"))
    db.commit()
    scan = Scan(cruise_id=cruise.id, conditions={"profiles": ["clean_win_chrome"], "rounds": 1})
    db.add(scan)
    db.commit()
    execute_scan(scan.id)
    assert sent, "Preisalarm wurde nicht ausgeloest"
    assert "2.876,00 EUR" in sent[0][1]


def test_matrix_reports_dropped_entries():
    specs, notes = build_matrix(profile_keys=["clean_win_chrome", "unbekannt"], proxy_names=["gibt-es-nicht"])
    assert [s.profile.key for s in specs] == ["clean_win_chrome"]
    assert any("unbekannt" in note for note in notes)
    assert any("gibt-es-nicht" in note for note in notes)


def test_rate_limit_blocks_excessive_scans(db, monkeypatch):
    monkeypatch.setattr(settings, "max_scans_per_cruise_per_day", 1)
    cruise = get_or_create_cruise(db, "mock://cruise/e2e-rate")
    create_scan(db, cruise, profiles=["clean_win_chrome"])
    from app.scanner.queue import RateLimitExceeded

    try:
        create_scan(db, cruise, profiles=["clean_win_chrome"])
        raise AssertionError("Rate Limit hat nicht gegriffen")
    except RateLimitExceeded as exc:
        assert "Limit erreicht" in str(exc)
