"""Provider abstraction.

Every cruise vendor gets its own adapter.  Nothing vendor specific may leak
outside ``app/providers/<vendor>/`` -- selectors, cookie banners and price
parsing all live inside the adapter package.
"""
from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

PRICE_FIELDS = (
    "starting_price",
    "price_per_person",
    "cabin_price",
    "total_price",
    "service_fee",
    "flight_price",
    "transfer_price",
    "drinks_package_price",
    "extras_price",
    "discount",
    "final_price",
)


@dataclass
class ParsedUrl:
    """Everything we could read straight out of the booking link."""

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
    rate_code: Optional[str] = None
    price_code: Optional[str] = None
    flight_included: Optional[bool] = None
    currency: Optional[str] = None
    raw_params: Dict[str, Any] = field(default_factory=dict)

    @property
    def passenger_count(self) -> Optional[int]:
        if self.adults is None and self.children is None:
            return None
        return (self.adults or 0) + (self.children or 0)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["passenger_count"] = self.passenger_count
        return data


@dataclass
class TripDetails:
    """Facts read off the page -- used for the offer identity check."""

    ship: Optional[str] = None
    departure_date: Optional[str] = None
    return_date: Optional[str] = None
    nights: Optional[int] = None
    route: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    cabin_type: Optional[str] = None
    cabin_category: Optional[str] = None
    tariff: Optional[str] = None
    board: Optional[str] = None          # Verpflegung
    passenger_count: Optional[int] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    flight_included: Optional[bool] = None
    drinks_package: Optional[str] = None
    cancellation_terms: Optional[str] = None
    promo_terms: Optional[str] = None
    offer_name: Optional[str] = None
    price_code: Optional[str] = None
    currency: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dict(asdict(self))

    def merge(self, other: TripDetails) -> TripDetails:
        """Fill blanks from ``other`` without overwriting known values."""
        merged = TripDetails(**self.to_dict())
        for key, value in other.to_dict().items():
            if getattr(merged, key) in (None, "") and value not in (None, ""):
                setattr(merged, key, value)
        return merged


@dataclass
class PriceBreakdown:
    """All prices we managed to read.  ``None`` == not reliably detected."""

    currency: Optional[str] = None
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
    tariff: Optional[str] = None
    cabin_category: Optional[str] = None
    offer_name: Optional[str] = None
    price_code: Optional[str] = None
    source_labels: Dict[str, str] = field(default_factory=dict)
    captured_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def merge(self, other: PriceBreakdown) -> PriceBreakdown:
        merged = PriceBreakdown(**dict(self.to_dict()))
        for key, value in other.to_dict().items():
            if key == "source_labels":
                merged.source_labels = {**(self.source_labels or {}), **(value or {})}
                continue
            if getattr(merged, key) in (None, "") and value not in (None, ""):
                setattr(merged, key, value)
        return merged

    def has_any_price(self) -> bool:
        return any(getattr(self, name) is not None for name in PRICE_FIELDS)

    def stamp(self) -> PriceBreakdown:
        self.captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return self


class BlockedError(RuntimeError):
    """Bot protection / CAPTCHA detected -- we stop immediately and never try
    to circumvent it."""

    def __init__(self, message: str, kind: str = "BLOCKED_CAPTCHA") -> None:
        super().__init__(message)
        self.kind = kind


class SoldOutError(RuntimeError):
    def __init__(self, message: str, kind: str = "SOLD_OUT") -> None:
        super().__init__(message)
        self.kind = kind


class SelectorError(RuntimeError):
    """A required element could not be located -- the site probably changed."""

    def __init__(self, message: str, kind: str = "SELECTOR_CHANGED") -> None:
        super().__init__(message)
        self.kind = kind


class SiteError(RuntimeError):
    def __init__(self, message: str, kind: str = "SITE_ERROR") -> None:
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------------------
# Run context
# ---------------------------------------------------------------------------

StepRecorder = Callable[..., None]


@dataclass
class RunContext:
    """Everything an adapter needs for one profile run."""

    scan_id: int
    profile_key: str
    profile_label: str
    device: str
    browser: str
    cookie_mode: str
    referrer: Optional[str]
    proxy_name: Optional[str]
    session_type: str
    round: int
    locale: str = "de-DE"
    timezone: str = "Europe/Berlin"
    currency: str = "EUR"
    page: Any = None               # playwright Page (or a stub in tests)
    record_step: StepRecorder = lambda *a, **k: None
    save_screenshot: Callable[[str], Optional[str]] = lambda name: None
    save_html: Callable[[str], Optional[str]] = lambda name: None
    parsed_url: Optional[ParsedUrl] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    cookie_mode_applied: Optional[str] = None
    page_type: Optional[str] = None
    deepest_step: Optional[str] = None
    dry_run: bool = False

    def log(self, message: str, *, step: Optional[str] = None, level: str = "INFO", **extra: Any) -> None:
        self.record_step(message=message, step=step, level=level, **extra)


class CruiseProvider(abc.ABC):
    """Interface every vendor adapter implements."""

    key: str = "base"
    label: str = "Base"
    allowed_hosts: tuple = ()
    #: Adapters that do not drive a real browser (e.g. the mock provider).
    requires_browser: bool = True
    #: The last step we are allowed to reach.  A booking must NEVER be placed.
    stop_before: str = "verbindliche Buchung"

    # -- URL handling -------------------------------------------------------
    @abc.abstractmethod
    def can_handle_url(self, url: str) -> bool: ...

    @abc.abstractmethod
    def parse_url(self, url: str) -> ParsedUrl: ...

    # -- browsing flow ------------------------------------------------------
    @abc.abstractmethod
    def open_offer(self, ctx: RunContext, url: str) -> None: ...

    @abc.abstractmethod
    def accept_cookies(self, ctx: RunContext, mode: str) -> str: ...

    @abc.abstractmethod
    def extract_trip_details(self, ctx: RunContext) -> TripDetails: ...

    @abc.abstractmethod
    def select_cabin(self, ctx: RunContext, preferred: Optional[str] = None) -> Optional[str]: ...

    @abc.abstractmethod
    def select_rate(self, ctx: RunContext, preferred: Optional[str] = None) -> Optional[str]: ...

    @abc.abstractmethod
    def extract_price(self, ctx: RunContext) -> PriceBreakdown: ...

    @abc.abstractmethod
    def extract_final_price(self, ctx: RunContext) -> PriceBreakdown: ...

    @abc.abstractmethod
    def take_snapshot(self, ctx: RunContext, name: str) -> Dict[str, Any]: ...

    # -- orchestration ------------------------------------------------------
    def run_flow(self, ctx: RunContext, url: str) -> FlowResult:
        """Walk the booking funnel and collect prices.

        The default implementation is a generic sequence built from the methods
        above; vendor adapters override it when the funnel needs vendor specific
        ordering.  It must never complete a booking.
        """
        result = FlowResult()
        try:
            self.open_offer(ctx, url)
            result.cookie_mode_applied = self.accept_cookies(ctx, ctx.cookie_mode)
            blocked = self.detect_block(ctx)
            if blocked:
                result.status = blocked
                result.error = "Zugriffsschutz erkannt - Test wurde beendet."
                return result
            result.page_type = self.detect_page_type(ctx)
            self.take_snapshot(ctx, "01-angebot-start")
            result.trip = self.extract_trip_details(ctx)
            prices = self.extract_price(ctx)
            self.select_cabin(ctx, None)
            self.take_snapshot(ctx, "03-kabinenauswahl")
            self.select_rate(ctx, None)
            self.take_snapshot(ctx, "04-tarifauswahl")
            prices = prices.merge(self.extract_final_price(ctx))
            self.take_snapshot(ctx, "05-preisuebersicht")
            result.prices = prices.stamp()
            result.deepest_step = "summary"
            if prices.final_price is None and prices.total_price is None:
                result.status = Status.PARTIAL if prices.has_any_price() else Status.PRICE_NOT_FOUND
                if result.status == Status.PRICE_NOT_FOUND:
                    result.error = "Preis konnte nicht zuverlässig ermittelt werden."
        except BlockedError as exc:
            result.status = exc.kind
            result.error = str(exc)
        except SoldOutError as exc:
            result.status = exc.kind
            result.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - one profile must never kill a scan
            result.status = Status.ERROR
            result.error = f"{type(exc).__name__}: {exc}"
        return result

    # -- optional hooks -----------------------------------------------------
    def detect_page_type(self, ctx: RunContext) -> str:
        return "unknown"

    def detect_block(self, ctx: RunContext) -> Optional[str]:
        """Return a block kind (CAPTCHA/bot protection) if detected."""
        return None


# ---------------------------------------------------------------------------
# Flow result (status strings mirror app.models.ResultStatus)
# ---------------------------------------------------------------------------


class Status:
    OK = "OK"
    PARTIAL = "PARTIAL"
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


@dataclass
class FlowResult:
    status: str = Status.OK
    trip: TripDetails = field(default_factory=TripDetails)
    prices: PriceBreakdown = field(default_factory=PriceBreakdown)
    page_type: Optional[str] = None
    deepest_step: Optional[str] = None
    final_url: Optional[str] = None
    error: Optional[str] = None
    cookie_mode_applied: Optional[str] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)
