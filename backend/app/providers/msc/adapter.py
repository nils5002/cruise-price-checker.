"""MSC Cruises provider adapter.

Scope and limits -- deliberately conservative:

* We only ever *read* public offer pages.  No login, no personal data, no
  booking, no payment.  The flow stops at the last page before a binding order.
* No CAPTCHA solving and no bot-protection circumvention.  If a challenge shows
  up the run ends with ``BLOCKED_CAPTCHA`` / ``BOT_PROTECTION``.
* Parsing is text/ARIA driven so a markup change degrades gracefully into
  "price not reliably detected" instead of a wrong number.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.browser import locators as L
from app.browser.session import PlaywrightTimeoutError, human_pause
from app.config import settings
from app.core.logging_setup import get_logger
from app.providers import base
from app.providers.base import (
    BlockedError,
    CruiseProvider,
    FlowResult,
    ParsedUrl,
    PriceBreakdown,
    RunContext,
    SelectorError,
    SoldOutError,
    Status,
    TripDetails,
)
from app.providers.msc import price_parser as PP
from app.providers.msc import selectors as S
from app.providers.msc.url_parser import is_msc_url, normalise_date, parse_msc_url

logger = get_logger(__name__)

_DATE_RE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b")
_NIGHTS_RE = re.compile(r"\b(\d{1,2})\s*(?:n(?:ä|ae)chte|nights|tage)\b", re.IGNORECASE)
_PAX_RE = re.compile(r"\b(\d{1,2})\s*(?:erwachsene|adults|g(?:ä|ae)ste|passagiere)\b", re.IGNORECASE)
_CHILD_RE = re.compile(r"\b(\d{1,2})\s*(?:kinder|kind|children)\b", re.IGNORECASE)
_SHIP_RE = re.compile(r"\bMSC\s+([A-ZÄÖÜ][a-zäöüA-Z]{2,18})\b")
_CANCEL_RE = re.compile(
    r"(kostenlose[rs]? (?:storno|umbuchung|(?:ä|ae)nderung)[^.]{0,60}"
    r"|nicht (?:erstattbar|(?:ä|ae)nderbar|stornierbar)"
    r"|flexible[rs]? (?:tarif|stornobedingung)[^.]{0,40})",
    re.IGNORECASE,
)


def _detect_ship(text: str) -> Optional[str]:
    """Identify the ship by the known fleet; fall back to a guarded pattern.

    The brand header ("MSC Cruises") must never be mistaken for a ship name.
    """
    low = text.lower()
    for ship in S.KNOWN_SHIPS:
        if re.search(r"\bmsc\s+" + re.escape(ship.lower()) + r"\b", low):
            return f"MSC {ship}"
    for match in _SHIP_RE.finditer(text):
        candidate = match.group(1)
        if candidate.lower() not in S.NOT_SHIP_WORDS:
            return f"MSC {candidate}"
    return None


class MscProvider(CruiseProvider):
    key = "msc"
    label = "MSC Cruises"
    allowed_hosts = ("www.msccruises.de", "msccruises.de", "book.msccruises.de")

    # ------------------------------------------------------------------
    # URL handling
    # ------------------------------------------------------------------
    def can_handle_url(self, url: str) -> bool:
        return is_msc_url(url)

    def parse_url(self, url: str) -> ParsedUrl:
        return parse_msc_url(url)

    # ------------------------------------------------------------------
    # Low level helpers
    # ------------------------------------------------------------------
    def _settle(self, ctx: RunContext, *, pause: float = 1.0) -> None:
        page = ctx.page
        for state in ("domcontentloaded", "networkidle"):
            try:
                page.wait_for_load_state(state, timeout=min(settings.navigation_timeout_ms, 20_000))
            except Exception:
                break
        human_pause(pause)

    def _text(self, ctx: RunContext, *, max_chars: int = 20_000) -> str:
        lines = L.page_lines(ctx.page)
        return "\n".join(lines)[:max_chars]

    def _guard_page(self, ctx: RunContext, text: Optional[str] = None) -> None:
        """Abort on CAPTCHAs / bot protection; never try to work around them."""
        body = (text if text is not None else self._text(ctx, max_chars=6_000)).lower()
        marker = PP.detect_block(body)
        if marker:
            title = ""
            try:
                title = (ctx.page.title() or "").lower()
            except Exception:
                pass
            kind = Status.BOT_PROTECTION if marker in ("cloudflare", "access denied", "request blocked") else Status.BLOCKED_CAPTCHA
            raise BlockedError(f"Zugriffsschutz erkannt ({marker}{'; ' + title if title else ''})", kind=kind)

    def _is_forbidden(self, label: Optional[str]) -> bool:
        if not label:
            return False
        text = label.lower()
        return any(re.search(pattern, text) for pattern in S.FORBIDDEN_CLICK_PATTERNS)

    def _guarded_click(self, ctx: RunContext, locator: Any, what: str) -> bool:
        """Click only after making sure this cannot commit a booking."""
        if locator is None:
            return False
        name = L.text_of(locator, limit=200) or ""
        try:
            aria = locator.get_attribute("aria-label") or ""
        except Exception:
            aria = ""
        if self._is_forbidden(name) or self._is_forbidden(aria):
            ctx.log(
                f"Klick auf '{name or aria}' bewusst NICHT ausgeführt "
                f"(Buchungs-/Zahlungsschritt).",
                step=what,
                level="WARNING",
            )
            return False
        try:
            locator.scroll_into_view_if_needed(timeout=4_000)
        except Exception:
            pass
        try:
            locator.click(timeout=settings.browser_timeout_ms)
        except Exception as exc:
            ctx.log(f"Klick fehlgeschlagen ({type(exc).__name__})", step=what, level="WARNING")
            return False
        ctx.log(f"Klick: {name[:80] or what}", step=what)
        self._settle(ctx)
        return True

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------
    def open_offer(self, ctx: RunContext, url: str) -> None:
        from app.browser.profiles import REFERRER_URLS

        referer = REFERRER_URLS.get(ctx.referrer or "direct")
        kwargs: Dict[str, Any] = {"wait_until": "domcontentloaded", "timeout": settings.navigation_timeout_ms}
        if referer:
            kwargs["referer"] = referer
        try:
            response = ctx.page.goto(url, **kwargs)
        except PlaywrightTimeoutError as exc:
            raise TimeoutError(f"Zeitüberschreitung beim Laden der Seite: {exc}") from exc
        except Exception as exc:
            message = str(exc)
            if "net::" in message or "NS_ERROR" in message:
                raise ConnectionError("Website nicht erreichbar") from exc
            raise
        status_code = None
        try:
            status_code = response.status if response else None
        except Exception:
            pass
        ctx.log(
            f"Seite geoeffnet (HTTP {status_code if status_code is not None else 'n/a'})",
            step="open_offer",
            url=url,
        )
        if status_code and status_code >= 500:
            raise base.SiteError(f"Website antwortet mit HTTP {status_code}")
        if status_code in (403, 429):
            detail = ""
            try:
                detail = " ".join((ctx.page.inner_text("body", timeout=3_000) or "").split())[:180]
            except Exception:
                detail = ""
            raise BlockedError(
                f"Zugriff durch die Website eingeschränkt (HTTP {status_code})"
                + (f": {detail}" if detail else ""),
                kind=Status.BOT_PROTECTION,
            )
        self._settle(ctx)
        self._guard_page(ctx)

    def accept_cookies(self, ctx: RunContext, mode: str) -> str:
        """Apply the requested cookie variant and report what really happened."""
        page = ctx.page
        banner = L.first_visible(page, S.COOKIE_BANNER, timeout_ms=6_000)
        if banner is None:
            applied = "kein_banner"
            ctx.log("Kein Cookie-Banner sichtbar.", step="cookies")
            ctx.cookie_mode_applied = applied
            return applied

        if mode == "none":
            applied = "banner_ignoriert"
            # Check whether the page is still usable with the banner open.
            try:
                blocking = page.evaluate(
                    "() => { const b = document.querySelector('.onetrust-pc-dark-filter, [class*=\"overlay\"], [class*=\"backdrop\"]');"
                    " if (!b) return false; const s = getComputedStyle(b);"
                    " return s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity || '1') > 0.1; }"
                )
            except Exception:
                blocking = False
            if blocking:
                applied = "banner_ignoriert_overlay_blockiert"
            ctx.log(f"Cookie-Banner bewusst nicht bestätigt ({applied}).", step="cookies")
            ctx.cookie_mode_applied = applied
            return applied

        if mode == "all":
            button = L.first_visible(page, S.COOKIE_ACCEPT_ALL, timeout_ms=5_000)
            if button is not None and self._guarded_click(ctx, button, "cookies"):
                ctx.cookie_mode_applied = "alle_akzeptiert"
                return "alle_akzeptiert"
        else:  # necessary
            button = L.first_visible(page, S.COOKIE_ONLY_NECESSARY, timeout_ms=5_000)
            if button is not None and self._guarded_click(ctx, button, "cookies"):
                ctx.cookie_mode_applied = "nur_notwendige"
                return "nur_notwendige"
            # Fallback: open the settings dialog and save the default selection.
            settings_button = L.first_visible(page, S.COOKIE_SETTINGS, timeout_ms=4_000)
            if settings_button is not None and self._guarded_click(ctx, settings_button, "cookies"):
                save = L.first_visible(page, S.COOKIE_SAVE_SELECTION, timeout_ms=5_000)
                if save is not None and self._guarded_click(ctx, save, "cookies"):
                    ctx.cookie_mode_applied = "nur_notwendige_ueber_einstellungen"
                    return "nur_notwendige_ueber_einstellungen"

        applied = "banner_erkannt_aber_nicht_bedienbar"
        ctx.log(
            "Cookie-Banner erkannt, aber kein passender Button gefunden - "
            "Banner-Aufbau hat sich möglicherweise geändert.",
            step="cookies",
            level="WARNING",
        )
        ctx.cookie_mode_applied = applied
        return applied

    def detect_page_type(self, ctx: RunContext) -> str:
        text = self._text(ctx, max_chars=12_000).lower()
        url = ""
        try:
            url = (ctx.page.url or "").lower()
        except Exception:
            pass
        # Payment / personal data first -- these are the hard stop markers.
        for page_type in ("payment", "passenger_data", "summary", "extras", "cabin_category", "cabin_type", "rate", "availability", "offer"):
            for marker in S.PAGE_TYPE_MARKERS[page_type]:
                if re.search(marker, text):
                    ctx.page_type = page_type
                    return page_type
        for token, page_type in (("checkout", "summary"), ("cabin", "cabin_category"), ("booking", "availability")):
            if token in url:
                ctx.page_type = page_type
                return page_type
        ctx.page_type = "unknown"
        return "unknown"

    def detect_block(self, ctx: RunContext) -> Optional[str]:
        try:
            self._guard_page(ctx)
        except BlockedError as exc:
            return exc.kind
        return None

    def extract_trip_details(self, ctx: RunContext) -> TripDetails:
        lines = L.page_lines(ctx.page)
        text = "\n".join(lines)
        details = TripDetails(currency="EUR")

        header = L.first_visible(ctx.page, S.TRIP_HEADER, timeout_ms=3_000)
        header_text = L.text_of(header, limit=300)
        if header_text:
            details.offer_name = header_text

        details.ship = _detect_ship(text)

        dates = _DATE_RE.findall(text)
        iso_dates: List[str] = []
        for day, month, year in dates:
            iso = normalise_date(f"{int(day):02d}.{int(month):02d}.{year}")
            if iso and iso not in iso_dates:
                iso_dates.append(iso)
        if iso_dates:
            details.departure_date = iso_dates[0]
            if len(iso_dates) > 1:
                details.return_date = iso_dates[1]

        nights = _NIGHTS_RE.search(text)
        if nights:
            value = int(nights.group(1))
            if 1 <= value <= 60:
                details.nights = value

        pax = _PAX_RE.search(text)
        if pax:
            value = int(pax.group(1))
            if 1 <= value <= 12:
                details.adults = value
        child = _CHILD_RE.search(text)
        if child:
            value = int(child.group(1))
            if 0 <= value <= 8:
                details.children = value
        if details.adults is not None:
            details.passenger_count = details.adults + (details.children or 0)

        low = text.lower()
        for tariff in S.KNOWN_TARIFFS:
            if tariff.lower() in low:
                details.tariff = tariff
                break
        for cabin in S.KNOWN_CABIN_TYPES:
            if cabin.lower() in low:
                details.cabin_type = cabin
                break
        for board in S.BOARD_TERMS:
            if board.lower() in low:
                details.board = board
                break
        if "flug inklusive" in low or "inkl. flug" in low or "mit flug" in low:
            details.flight_included = True
        elif "ohne flug" in low or "nur kreuzfahrt" in low:
            details.flight_included = False
        if "getr" in low and "nkepaket" in low:
            match = re.search(r"(easy[- ]?paket|premium extra|all inclusive|getr(?:ä|ae)nkepaket [\w ]{0,20})", low)
            if match:
                details.drinks_package = match.group(1).strip()[:80]
        cancel = _CANCEL_RE.search(text)
        if cancel:
            details.cancellation_terms = " ".join(cancel.group(1).split())[:160]
        promo = PP.find_promo_code(text)
        if promo:
            details.price_code = promo

        # Route: try the itinerary section, else the ports mentioned in the header.
        route_locator = L.first_visible(
            ctx.page,
            [{"css": "[data-testid*='itinerary']"}, {"css": "[class*='itinerary']"}],
            timeout_ms=2_500,
        )
        route_text = L.text_of(route_locator, limit=600)
        if route_text:
            details.route = route_text[:400]

        parsed = ctx.parsed_url
        if parsed:
            details = details.merge(
                TripDetails(
                    ship=parsed.ship,
                    departure_date=parsed.departure_date,
                    return_date=parsed.return_date,
                    nights=parsed.nights,
                    origin=parsed.origin,
                    destination=parsed.destination,
                    cabin_type=parsed.cabin_type,
                    cabin_category=parsed.cabin_category,
                    adults=parsed.adults,
                    children=parsed.children,
                    passenger_count=parsed.passenger_count,
                    flight_included=parsed.flight_included,
                    price_code=parsed.price_code,
                    currency=parsed.currency,
                )
            )
        ctx.log(
            f"Reisedaten gelesen: Schiff={details.ship or '-'} "
            f"Abfahrt={details.departure_date or '-'} Nächte={details.nights or '-'} "
            f"Tarif={details.tariff or '-'}",
            step="trip_details",
        )
        return details

    # -- price extraction ---------------------------------------------
    def _breakdown_from_page(self, ctx: RunContext) -> PriceBreakdown:
        page = ctx.page
        breakdown = PriceBreakdown(currency="EUR")
        collected: Dict[str, float] = {}
        sources: Dict[str, str] = {}

        # 1) trusted summary containers first
        for text in L.collect_texts(page, S.PRICE_SUMMARY_CONTAINERS, limit=8):
            raw_lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
            lines = L.merge_label_value_lines(raw_lines)
            found = PP.parse_breakdown_lines(lines)
            for field, value in found.items():
                if field not in collected:
                    collected[field] = value
                    sources[field] = "summary-container"

        # 2) whole page as a fallback -- still label driven
        page_lines = L.merge_label_value_lines(L.page_lines(page))
        found = PP.parse_breakdown_lines(page_lines)
        for field, value in found.items():
            if field not in collected:
                collected[field] = value
                sources[field] = "seitentext"

        for field, value in collected.items():
            setattr(breakdown, field, value)
        breakdown.source_labels = sources

        joined = "\n".join(page_lines)
        currency = PP.detect_currency(joined)
        if currency:
            breakdown.currency = currency
        promo = PP.find_promo_code(joined)
        if promo:
            breakdown.promo_code = promo
        return breakdown.stamp()

    def extract_price(self, ctx: RunContext) -> PriceBreakdown:
        breakdown = self._breakdown_from_page(ctx)
        if breakdown.starting_price is None:
            locator = L.first_visible(ctx.page, S.STARTING_PRICE, timeout_ms=2_000)
            text = L.text_of(locator, limit=120)
            amount = PP.parse_amount(text)
            if amount is not None:
                breakdown.starting_price = amount
                breakdown.source_labels["starting_price"] = "ab-preis-element"
        ctx.log(
            "Preise auf dieser Seite: "
            + ", ".join(
                f"{k}={v}"
                for k, v in breakdown.to_dict().items()
                if v is not None and k in base.PRICE_FIELDS
            )
            or "keine",
            step="extract_price",
        )
        return breakdown

    def extract_final_price(self, ctx: RunContext) -> PriceBreakdown:
        breakdown = self._breakdown_from_page(ctx)
        # A summary page must yield a total; otherwise we report "not detected".
        if breakdown.final_price is None and breakdown.total_price is not None:
            breakdown.final_price = breakdown.total_price
            breakdown.source_labels["final_price"] = "aus Gesamtpreis übernommen"
        tariff = None
        text = self._text(ctx, max_chars=12_000)
        low = text.lower()
        for known in S.KNOWN_TARIFFS:
            if known.lower() in low:
                tariff = known
                break
        breakdown.tariff = tariff
        for cabin in S.KNOWN_CABIN_TYPES:
            if cabin.lower() in low:
                breakdown.cabin_category = breakdown.cabin_category or cabin
                break
        ctx.log(
            f"Endpreis-Erfassung: final={breakdown.final_price} total={breakdown.total_price} "
            f"pp={breakdown.price_per_person}",
            step="extract_final_price",
        )
        return breakdown

    # -- selection steps ----------------------------------------------
    def select_cabin(self, ctx: RunContext, preferred: Optional[str] = None) -> Optional[str]:
        page = ctx.page
        text = self._text(ctx, max_chars=8_000)
        if PP.detect_sold_out(text.lower()):
            raise SoldOutError("Reise oder Kabine ist laut Website nicht verfügbar.", kind=Status.SOLD_OUT)

        chosen: Optional[str] = None
        if preferred:
            option = L.first_visible(
                page,
                [{"role": "button", "name": re.escape(preferred), "regex": True},
                 {"role": "radio", "name": re.escape(preferred), "regex": True},
                 {"text": re.escape(preferred), "regex": True}],
                timeout_ms=4_000,
            )
            if option is not None and self._guarded_click(ctx, option, "select_cabin"):
                chosen = preferred
        if chosen is None:
            option = L.first_visible(page, S.CABIN_TYPE_OPTIONS, timeout_ms=4_000)
            if option is not None:
                chosen = L.text_of(option, limit=120)
                if not self._guarded_click(ctx, option, "select_cabin"):
                    chosen = None
        if chosen is None:
            card = L.first_visible(page, S.CABIN_CATEGORY_CARDS, timeout_ms=4_000)
            if card is not None:
                button = L.first_visible(page, S.CABIN_SELECT_BUTTON, timeout_ms=3_000)
                if button is not None and self._guarded_click(ctx, button, "select_cabin"):
                    chosen = L.text_of(card, limit=120)
        if chosen:
            ctx.log(f"Kabine gewählt: {chosen[:80]}", step="select_cabin")
        else:
            ctx.log("Keine Kabinenauswahl möglich (Element nicht gefunden).", step="select_cabin", level="WARNING")
        return chosen

    def select_rate(self, ctx: RunContext, preferred: Optional[str] = None) -> Optional[str]:
        page = ctx.page
        chosen: Optional[str] = None
        if preferred:
            option = L.first_visible(
                page,
                [{"role": "button", "name": re.escape(preferred), "regex": True},
                 {"role": "radio", "name": re.escape(preferred), "regex": True}],
                timeout_ms=4_000,
            )
            if option is not None and self._guarded_click(ctx, option, "select_rate"):
                chosen = preferred
        if chosen is None:
            option = L.first_visible(page, S.RATE_OPTIONS, timeout_ms=4_000)
            if option is not None:
                label = L.text_of(option, limit=140)
                if self._guarded_click(ctx, option, "select_rate"):
                    chosen = label
        if chosen is None:
            button = L.first_visible(page, S.RATE_SELECT_BUTTON, timeout_ms=3_000)
            if button is not None and self._guarded_click(ctx, button, "select_rate"):
                chosen = L.text_of(button, limit=120)
        if chosen:
            ctx.log(f"Tarif gewählt: {chosen[:80]}", step="select_rate")
        else:
            ctx.log("Keine Tarifauswahl gefunden.", step="select_rate", level="INFO")
        return chosen

    def take_snapshot(self, ctx: RunContext, name: str) -> Dict[str, Any]:
        artifact: Dict[str, Any] = {"name": name}
        try:
            artifact["url"] = ctx.page.url
        except Exception:
            artifact["url"] = None
        artifact["page_type"] = ctx.page_type
        artifact["screenshot"] = ctx.save_screenshot(name)
        if settings.enable_html_snapshots:
            artifact["html"] = ctx.save_html(name)
        ctx.artifacts.append(artifact)
        ctx.log(f"Snapshot '{name}' gespeichert.", step="snapshot", screenshot_path=artifact.get("screenshot"))
        return artifact

    # ------------------------------------------------------------------
    # Full flow
    # ------------------------------------------------------------------
    def run_flow(self, ctx: RunContext, url: str) -> FlowResult:
        result = FlowResult()
        prices = PriceBreakdown(currency="EUR")
        try:
            self.open_offer(ctx, url)
            result.cookie_mode_applied = self.accept_cookies(ctx, ctx.cookie_mode)
            self.detect_page_type(ctx)
            self.take_snapshot(ctx, "01-angebot-start")
            result.deepest_step = ctx.deepest_step = "offer_start"

            trip = self.extract_trip_details(ctx)
            prices = prices.merge(self.extract_price(ctx))

            # --- into the booking funnel --------------------------------
            steps = 0
            max_steps = settings.max_steps_per_profile
            seen_summary = False
            snapshots_taken = {"01-angebot-start"}

            while steps < max_steps:
                steps += 1
                page_type = self.detect_page_type(ctx)
                text = self._text(ctx, max_chars=12_000)
                low = text.lower()
                self._guard_page(ctx, text)

                if PP.detect_session_expired(low):
                    result.status = Status.SESSION_EXPIRED
                    result.error = "Sitzung ist laut Website abgelaufen."
                    break
                if PP.detect_price_changed(low):
                    result.status = Status.PRICE_CHANGED_DURING_FLOW
                    ctx.log("Website meldet eine Preisänderung im Buchungsprozess.", step="flow", level="WARNING")
                if PP.detect_sold_out(low) and page_type in ("cabin_category", "cabin_type", "availability"):
                    raise SoldOutError("Kabine/Reise laut Website nicht verfügbar.", kind=Status.CABIN_SOLD_OUT)

                # Hard stop: never enter personal data or payment steps.
                if page_type in ("payment", "passenger_data"):
                    ctx.log(
                        "Letzter Schritt vor der verbindlichen Buchung erreicht - "
                        "Automatisierung wird hier bewusst beendet.",
                        step="stop_before_booking",
                    )
                    result.deepest_step = ctx.deepest_step = "stop_before_booking"
                    break

                if page_type == "summary":
                    if "05-preisuebersicht" not in snapshots_taken:
                        self.take_snapshot(ctx, "05-preisuebersicht")
                        snapshots_taken.add("05-preisuebersicht")
                    prices = prices.merge(self.extract_final_price(ctx))
                    trip = trip.merge(self.extract_trip_details(ctx))
                    seen_summary = True
                    result.deepest_step = ctx.deepest_step = "summary"
                    if prices.final_price is not None or prices.total_price is not None:
                        break

                if page_type in ("offer", "availability", "unknown"):
                    started = self._guarded_click(
                        ctx, L.first_visible(ctx.page, S.START_BOOKING, timeout_ms=4_000), "start_booking"
                    )
                    if started:
                        result.deepest_step = ctx.deepest_step = "availability"
                        if "02-verfügbarkeit" not in snapshots_taken:
                            self.take_snapshot(ctx, "02-verfügbarkeit")
                            snapshots_taken.add("02-verfügbarkeit")
                        prices = prices.merge(self.extract_price(ctx))
                        continue

                if page_type in ("cabin_type", "cabin_category"):
                    preferred = (ctx.parsed_url.cabin_category if ctx.parsed_url else None) or (
                        ctx.parsed_url.cabin_type if ctx.parsed_url else None
                    )
                    chosen = self.select_cabin(ctx, preferred)
                    if "03-kabinenauswahl" not in snapshots_taken:
                        self.take_snapshot(ctx, "03-kabinenauswahl")
                        snapshots_taken.add("03-kabinenauswahl")
                    prices = prices.merge(self.extract_price(ctx))
                    if chosen:
                        prices.cabin_category = prices.cabin_category or chosen[:120]
                        result.deepest_step = ctx.deepest_step = "cabin_selected"
                        continue

                if page_type == "rate":
                    chosen = self.select_rate(ctx, ctx.parsed_url.rate_code if ctx.parsed_url else None)
                    if "04-tarifauswahl" not in snapshots_taken:
                        self.take_snapshot(ctx, "04-tarifauswahl")
                        snapshots_taken.add("04-tarifauswahl")
                    prices = prices.merge(self.extract_price(ctx))
                    if chosen:
                        prices.tariff = prices.tariff or chosen[:120]
                        result.deepest_step = ctx.deepest_step = "rate_selected"
                        continue

                # extras / anything else: continue without adding options
                advanced = self._guarded_click(
                    ctx, L.first_visible(ctx.page, S.CONTINUE_BUTTONS, timeout_ms=3_500), "continue"
                )
                if not advanced:
                    ctx.log(
                        "Kein weiterer Schritt im Buchungsprozess erreichbar - "
                        "Erfassung endet hier.",
                        step="flow",
                    )
                    break

            if seen_summary:
                if "06-zusammenfassung" not in snapshots_taken:
                    self.take_snapshot(ctx, "06-zusammenfassung")
            else:
                self.take_snapshot(ctx, "99-letzter-stand")

            prices = prices.merge(self._breakdown_from_page(ctx))
            trip = trip.merge(self.extract_trip_details(ctx))
            result.trip = trip
            result.prices = prices.stamp()
            result.page_type = ctx.page_type
            try:
                result.final_url = ctx.page.url
            except Exception:
                result.final_url = None

            if result.status == Status.OK:
                if prices.final_price is not None or prices.total_price is not None:
                    result.status = Status.OK if seen_summary else Status.PARTIAL
                elif prices.has_any_price():
                    result.status = Status.PARTIAL
                else:
                    result.status = Status.PRICE_NOT_FOUND
                    result.error = "Preis konnte nicht zuverlässig ermittelt werden."
            return result

        except BlockedError as exc:
            result.status = exc.kind
            result.error = str(exc)
        except SoldOutError as exc:
            result.status = exc.kind
            result.error = str(exc)
        except SelectorError as exc:
            result.status = Status.SELECTOR_CHANGED
            result.error = str(exc)
        except base.SiteError as exc:
            result.status = Status.SITE_ERROR
            result.error = str(exc)
        except TimeoutError as exc:
            result.status = Status.TIMEOUT
            result.error = str(exc)
        except PlaywrightTimeoutError as exc:  # pragma: no cover
            result.status = Status.TIMEOUT
            result.error = str(exc)
        except ConnectionError as exc:
            result.status = Status.UNREACHABLE
            result.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - a single profile must never kill the scan
            result.status = Status.ERROR
            result.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Unerwarteter Fehler im MSC-Flow")

        result.trip = result.trip or TripDetails()
        result.prices = prices
        try:
            result.final_url = ctx.page.url if ctx.page else None
        except Exception:
            result.final_url = None
        result.page_type = ctx.page_type
        try:
            self.take_snapshot(ctx, "98-fehlerzustand")
        except Exception:
            pass
        return result
