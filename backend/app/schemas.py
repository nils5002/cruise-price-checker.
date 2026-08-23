"""Pydantic schemas (API contract)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="after")
    @classmethod
    def _mark_naive_datetimes_as_utc(cls, value: Any) -> Any:
        """Zeitstempel immer mit Zeitzone ausliefern.

        Intern wird durchgehend UTC gespeichert. SQLite gibt die Werte jedoch
        ohne Zeitzone zurueck; ohne Kennzeichnung interpretiert der Browser sie
        als Ortszeit und zeigt sie um den UTC-Offset verschoben an.
        """
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


# --- requests --------------------------------------------------------------
class ScanOptions(BaseModel):
    profiles: Optional[List[str]] = None
    cookie_modes: Optional[List[str]] = Field(default=None, description="necessary | all | none")
    referrers: Optional[List[str]] = Field(default=None, description="direct | google | bing")
    proxies: Optional[List[str]] = Field(default=None, description="Proxy-Labels (nie Zugangsdaten)")
    rounds: int = Field(default=1, ge=1, le=5)

    @field_validator("profiles", "cookie_modes", "referrers", "proxies")
    @classmethod
    def _limit(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        cleaned = [str(item)[:64] for item in value if str(item).strip()]
        return cleaned[:12] or None


class CruiseCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    start_scan: bool = True
    schedule_interval: str = Field(default="manual", pattern="^(manual|6h|12h|daily)$")
    options: ScanOptions = Field(default_factory=ScanOptions)


class CruiseUpdate(BaseModel):
    monitoring_enabled: Optional[bool] = None
    schedule_interval: Optional[str] = Field(default=None, pattern="^(manual|6h|12h|daily)$")
    title: Optional[str] = Field(default=None, max_length=300)
    notes: Optional[str] = Field(default=None, max_length=2000)


class UrlPreviewRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class AlertCreate(BaseModel):
    channel: str = Field(pattern="^(email|telegram|discord|homeassistant)$")
    target: Optional[str] = Field(default=None, max_length=300)
    threshold_total: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    drop_percent: Optional[float] = Field(default=None, ge=0.1, le=90)
    enabled: bool = True


# --- responses -------------------------------------------------------------
class ParsedUrlOut(BaseModel):
    provider: str
    url: str
    external_id: Optional[str] = None
    ship: Optional[str] = None
    departure_date: Optional[str] = None
    return_date: Optional[str] = None
    nights: Optional[int] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    cabin_type: Optional[str] = None
    cabin_category: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    passenger_count: Optional[int] = None
    rate_code: Optional[str] = None
    price_code: Optional[str] = None
    flight_included: Optional[bool] = None
    currency: Optional[str] = None
    raw_params: Dict[str, Any] = Field(default_factory=dict)


class CruiseOut(ORMModel):
    id: int
    provider: str
    url: str
    title: Optional[str] = None
    external_id: Optional[str] = None
    ship: Optional[str] = None
    departure_date: Optional[str] = None
    return_date: Optional[str] = None
    nights: Optional[int] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    route: Optional[str] = None
    cabin_type: Optional[str] = None
    cabin_category: Optional[str] = None
    rate_code: Optional[str] = None
    price_code: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    passenger_count: Optional[int] = None
    flight_included: Optional[bool] = None
    currency: str = "EUR"
    monitoring_enabled: bool = True
    schedule_interval: str = "manual"
    last_checked_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    parsed_params: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class CruiseOverviewOut(ORMModel):
    id: int
    provider: str
    title: Optional[str] = None
    url: str
    ship: Optional[str] = None
    departure_date: Optional[str] = None
    return_date: Optional[str] = None
    nights: Optional[int] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    cabin_type: Optional[str] = None
    cabin_category: Optional[str] = None
    passenger_count: Optional[int] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    flight_included: Optional[bool] = None
    currency: str = "EUR"
    monitoring_enabled: bool = True
    schedule_interval: str = "manual"
    best_price_ever: Optional[float] = None
    current_price: Optional[float] = None
    highest_price: Optional[float] = None
    change_since_previous: Optional[float] = None
    last_checked_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = None
    last_scan_id: Optional[int] = None
    last_scan_status: Optional[str] = None
    last_verdict: Optional[str] = None
    history_points: int = 0


class ScanResultOut(ORMModel):
    id: int
    round: int
    profile: str
    profile_label: str
    device: str
    browser: str
    platform: Optional[str] = None
    cookie_mode: str
    cookie_mode_applied: Optional[str] = None
    referrer: Optional[str] = None
    proxy_name: Optional[str] = None
    session_type: str
    starting_price: Optional[float] = None
    price_per_person: Optional[float] = None
    cabin_price: Optional[float] = None
    total_price: Optional[float] = None
    service_fee: Optional[float] = None
    flight_price: Optional[float] = None
    transfer_price: Optional[float] = None
    drinks_package_price: Optional[float] = None
    extras_price: Optional[float] = None
    discount: Optional[float] = None
    final_price: Optional[float] = None
    promo_code: Optional[str] = None
    currency: Optional[str] = None
    tariff: Optional[str] = None
    cabin_category: Optional[str] = None
    cabin_type: Optional[str] = None
    offer_name: Optional[str] = None
    price_code: Optional[str] = None
    identity: Optional[Dict[str, Any]] = None
    price_details: Optional[Dict[str, Any]] = None
    conditions: Optional[Dict[str, Any]] = None
    final_url: Optional[str] = None
    page_type: Optional[str] = None
    deepest_step: Optional[str] = None
    screenshot_path: Optional[str] = None
    artifacts: Optional[List[Dict[str, Any]]] = None
    status: str
    error: Optional[str] = None
    attempts: int = 1
    duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None


class ScanOut(ORMModel):
    id: int
    cruise_id: int
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    status: str
    trigger: str
    rounds_planned: int = 1
    rounds_completed: int = 0
    profiles_requested: Optional[List[str]] = None
    conditions: Optional[Dict[str, Any]] = None
    analysis: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ScanDetailOut(ScanOut):
    results: List[ScanResultOut] = Field(default_factory=list)


class ScanLogOut(ORMModel):
    id: int
    profile: Optional[str] = None
    round: int = 1
    level: str
    step: Optional[str] = None
    message: str
    url: Optional[str] = None
    page_type: Optional[str] = None
    screenshot_path: Optional[str] = None
    created_at: Optional[datetime] = None


class PriceHistoryOut(ORMModel):
    id: int
    timestamp: datetime
    lowest_price: Optional[float] = None
    highest_price: Optional[float] = None
    currency: str = "EUR"
    lowest_profile: Optional[str] = None
    highest_profile: Optional[str] = None
    results_with_price: int = 0
    scan_id: Optional[int] = None


class AlertOut(ORMModel):
    id: int
    cruise_id: int
    enabled: bool
    channel: str
    target: Optional[str] = None
    threshold_total: Optional[float] = None
    drop_percent: Optional[float] = None
    last_triggered_at: Optional[datetime] = None
    last_notified_price: Optional[float] = None


class HealthOut(BaseModel):
    status: str = "ok"


class MetaOut(BaseModel):
    app_name: str
    version: str
    environment: str
    headless: bool
    profiles: List[Dict[str, Any]]
    cookie_modes: List[Dict[str, str]]
    referrers: List[str]
    unified_conditions: Dict[str, Any]
    providers: List[Dict[str, Any]]
    proxy_labels: List[str]
    schedule_intervals: List[str]
    notification_channels: List[Dict[str, Any]]
    flights: Dict[str, Any]
    limits: Dict[str, Any]
    allowed_domains: List[str]
    api_key_required: bool
