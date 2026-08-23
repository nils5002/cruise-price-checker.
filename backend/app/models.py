"""SQLAlchemy models.

Money is stored as ``Numeric``/float EUR values; ``None`` explicitly means "not
reliably detected" -- the application never invents a number.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScanStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ResultStatus(str, enum.Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"              # page reached, but no reliable price
    PRICE_NOT_FOUND = "PRICE_NOT_FOUND"
    BLOCKED_CAPTCHA = "BLOCKED_CAPTCHA"
    BOT_PROTECTION = "BOT_PROTECTION"
    TIMEOUT = "TIMEOUT"
    UNREACHABLE = "UNREACHABLE"
    SOLD_OUT = "SOLD_OUT"
    CABIN_SOLD_OUT = "CABIN_SOLD_OUT"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    PRICE_CHANGED_DURING_FLOW = "PRICE_CHANGED_DURING_FLOW"
    SELECTOR_CHANGED = "SELECTOR_CHANGED"
    COOKIE_BANNER_CHANGED = "COOKIE_BANNER_CHANGED"
    SITE_ERROR = "SITE_ERROR"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


TERMINAL_BLOCKED = {ResultStatus.BLOCKED_CAPTCHA, ResultStatus.BOT_PROTECTION}


class Cruise(Base):
    __tablename__ = "cruises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    title: Mapped[Optional[str]] = mapped_column(String(300), default=None)
    external_id: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    ship: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    departure_date: Mapped[Optional[str]] = mapped_column(String(10), default=None)  # ISO date
    return_date: Mapped[Optional[str]] = mapped_column(String(10), default=None)
    nights: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    origin: Mapped[Optional[str]] = mapped_column(String(160), default=None)
    destination: Mapped[Optional[str]] = mapped_column(String(160), default=None)
    route: Mapped[Optional[str]] = mapped_column(Text, default=None)
    cabin_type: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    cabin_category: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    rate_code: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    price_code: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    adults: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    children: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    passenger_count: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    flight_included: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    locale: Mapped[str] = mapped_column(String(16), default="de-DE")

    parsed_params: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    notes: Mapped[Optional[str]] = mapped_column(Text, default=None)

    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule_interval: Mapped[str] = mapped_column(String(24), default="manual")  # manual|6h|12h|daily
    next_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    scans: Mapped[List[Scan]] = relationship(
        back_populates="cruise", cascade="all, delete-orphan", order_by="Scan.id.desc()"
    )
    history: Mapped[List[PriceHistory]] = relationship(
        back_populates="cruise", cascade="all, delete-orphan", order_by="PriceHistory.timestamp"
    )
    alerts: Mapped[List[PriceAlert]] = relationship(
        back_populates="cruise", cascade="all, delete-orphan"
    )


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cruise_id: Mapped[int] = mapped_column(ForeignKey("cruises.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[str] = mapped_column(String(24), default=ScanStatus.QUEUED.value, index=True)
    trigger: Mapped[str] = mapped_column(String(24), default="manual")  # manual|schedule|verification
    rounds_planned: Mapped[int] = mapped_column(Integer, default=1)
    rounds_completed: Mapped[int] = mapped_column(Integer, default=0)
    profiles_requested: Mapped[Optional[list]] = mapped_column(JSON, default=None)
    conditions: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    analysis: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    error: Mapped[Optional[str]] = mapped_column(Text, default=None)

    cruise: Mapped[Cruise] = relationship(back_populates="scans")
    results: Mapped[List[ScanResult]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", order_by="ScanResult.id"
    )
    logs: Mapped[List[ScanLog]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", order_by="ScanLog.id"
    )


class ScanResult(Base):
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer, default=1)

    profile: Mapped[str] = mapped_column(String(64))
    profile_label: Mapped[str] = mapped_column(String(120), default="")
    device: Mapped[str] = mapped_column(String(24), default="desktop")
    browser: Mapped[str] = mapped_column(String(24), default="chromium")
    platform: Mapped[Optional[str]] = mapped_column(String(48), default=None)
    cookie_mode: Mapped[str] = mapped_column(String(32), default="necessary")
    cookie_mode_applied: Mapped[Optional[str]] = mapped_column(String(48), default=None)
    referrer: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    proxy_name: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    session_type: Mapped[str] = mapped_column(String(24), default="clean")  # clean|returning

    # prices -- None means "not reliably detected"
    starting_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    price_per_person: Mapped[Optional[float]] = mapped_column(Float, default=None)
    cabin_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    total_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    service_fee: Mapped[Optional[float]] = mapped_column(Float, default=None)
    flight_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    transfer_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    drinks_package_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    extras_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    discount: Mapped[Optional[float]] = mapped_column(Float, default=None)
    final_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    promo_code: Mapped[Optional[str]] = mapped_column(String(80), default=None)

    currency: Mapped[Optional[str]] = mapped_column(String(8), default=None)
    tariff: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    cabin_category: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    cabin_type: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    offer_name: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    price_code: Mapped[Optional[str]] = mapped_column(String(80), default=None)

    identity: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    price_details: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    conditions: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    final_url: Mapped[Optional[str]] = mapped_column(Text, default=None)
    page_type: Mapped[Optional[str]] = mapped_column(String(48), default=None)
    deepest_step: Mapped[Optional[str]] = mapped_column(String(48), default=None)

    screenshot_path: Mapped[Optional[str]] = mapped_column(Text, default=None)
    artifacts: Mapped[Optional[list]] = mapped_column(JSON, default=None)
    steps: Mapped[Optional[list]] = mapped_column(JSON, default=None)

    status: Mapped[str] = mapped_column(String(32), default=ResultStatus.OK.value, index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scan: Mapped[Scan] = relationship(back_populates="results")

    __table_args__ = (Index("ix_scan_results_scan_profile", "scan_id", "profile", "round"),)

    @property
    def comparable_price(self) -> Optional[float]:
        """Price used for comparisons: final price first, cabin/total as fallback."""
        for value in (self.final_price, self.total_price, self.cabin_price):
            if value is not None:
                return value
        return None


class ScanLog(Base):
    """Debug trail per scan (no secrets, no cookies)."""

    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    profile: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    round: Mapped[int] = mapped_column(Integer, default=1)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    step: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    message: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[Optional[str]] = mapped_column(Text, default=None)
    page_type: Mapped[Optional[str]] = mapped_column(String(48), default=None)
    screenshot_path: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scan: Mapped[Scan] = relationship(back_populates="logs")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cruise_id: Mapped[int] = mapped_column(ForeignKey("cruises.id", ondelete="CASCADE"), index=True)
    scan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"), default=None)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    lowest_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    highest_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    lowest_profile: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    highest_profile: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    results_with_price: Mapped[int] = mapped_column(Integer, default=0)

    cruise: Mapped[Cruise] = relationship(back_populates="history")


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cruise_id: Mapped[int] = mapped_column(ForeignKey("cruises.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold_total: Mapped[Optional[float]] = mapped_column(Float, default=None)
    drop_percent: Mapped[Optional[float]] = mapped_column(Float, default=None)
    channel: Mapped[str] = mapped_column(String(32), default="email")  # email|telegram|discord|homeassistant
    target: Mapped[Optional[str]] = mapped_column(String(300), default=None)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    last_notified_price: Mapped[Optional[float]] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cruise: Mapped[Cruise] = relationship(back_populates="alerts")

    __table_args__ = (UniqueConstraint("cruise_id", "channel", "target", name="uq_alert_target"),)
