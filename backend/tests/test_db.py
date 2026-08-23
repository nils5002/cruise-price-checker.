"""Database model behaviour."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Cruise, PriceAlert, PriceHistory, ResultStatus, Scan, ScanLog, ScanResult, ScanStatus
from app.services import url_hash


def _cruise(db, suffix="db"):
    cruise = Cruise(
        provider="mock",
        url=f"mock://cruise/{suffix}",
        url_hash=url_hash(f"mock://cruise/{suffix}"),
        ship="MSC Euribia",
        departure_date="2026-09-11",
        return_date="2026-09-18",
        nights=7,
        adults=2,
        children=0,
        passenger_count=2,
    )
    db.add(cruise)
    db.commit()
    db.refresh(cruise)
    return cruise


def test_create_and_read(db):
    cruise = _cruise(db, "create")
    assert cruise.id is not None
    assert cruise.currency == "EUR"
    assert cruise.monitoring_enabled is True
    assert cruise.schedule_interval == "manual"


def test_scan_with_results_and_cascade(db):
    cruise = _cruise(db, "cascade")
    scan = Scan(cruise_id=cruise.id, status=ScanStatus.DONE.value)
    db.add(scan)
    db.commit()
    db.add_all(
        [
            ScanResult(
                scan_id=scan.id,
                profile="clean_win_chrome",
                profile_label="Clean Windows",
                final_price=2876.0,
                currency="EUR",
                status=ResultStatus.OK.value,
            ),
            ScanLog(scan_id=scan.id, message="test", step="open_offer"),
            PriceHistory(cruise_id=cruise.id, scan_id=scan.id, lowest_price=2876.0, highest_price=3056.0),
        ]
    )
    db.commit()

    scan_id = scan.id
    db.delete(cruise)
    db.commit()
    assert db.get(Scan, scan_id) is None
    assert db.scalars(select(ScanResult).where(ScanResult.scan_id == scan_id)).all() == []
    assert db.scalars(select(ScanLog).where(ScanLog.scan_id == scan_id)).all() == []


def test_null_prices_stay_null(db):
    cruise = _cruise(db, "nulls")
    scan = Scan(cruise_id=cruise.id)
    db.add(scan)
    db.commit()
    result = ScanResult(
        scan_id=scan.id,
        profile="clean_iphone",
        profile_label="iPhone",
        status=ResultStatus.PRICE_NOT_FOUND.value,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    assert result.final_price is None
    assert result.total_price is None
    assert result.comparable_price is None


def test_comparable_price_falls_back(db):
    result = ScanResult(scan_id=1, profile="p", profile_label="p", total_price=1500.0)
    assert result.comparable_price == 1500.0
    result.final_price = 1400.0
    assert result.comparable_price == 1400.0


def test_alert_roundtrip(db):
    cruise = _cruise(db, "alert")
    alert = PriceAlert(cruise_id=cruise.id, channel="telegram", threshold_total=2800.0, target="123")
    db.add(alert)
    db.commit()
    db.refresh(alert)
    assert alert.enabled is True
    assert alert.last_triggered_at is None
    alert.last_triggered_at = datetime.now(timezone.utc)
    db.commit()
    assert db.get(PriceAlert, alert.id).last_triggered_at is not None
