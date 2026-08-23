"""Price text parsing for MSC (German locale).

Rules:

* Only values that parse unambiguously and land inside a plausible range are
  returned; everything else becomes ``None``.
* ``None`` always means "not reliably detected" -- never a fallback guess.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

CURRENCY_SYMBOLS = {"€": "EUR", "EUR": "EUR", "CHF": "CHF", "$": "USD", "USD": "USD", "£": "GBP"}

# Plausibility guards (EUR).  A cruise total below 30 EUR or above 250k is not
# a price we are willing to report.
MIN_PLAUSIBLE = 20.0
MAX_PLAUSIBLE = 250_000.0

_NUMBER_RE = re.compile(
    r"""
    (?<![\d.,])                 # not in the middle of a number
    (\d{1,3}(?:[.\s ]\d{3})+(?:,\d{1,2})?   # 1.234 / 1.234,56 / 1 234
     |\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?           # 1,234 / 1,234.56 (en)
     |\d+(?:[.,]\d{1,2})?)                       # 799 / 799,00 / 799.00
    (?![\d])
    """,
    re.VERBOSE,
)

# --- label classification --------------------------------------------------
# Priority rules (see :func:`classify_label`):
#   1. an explicit total/final label wins over any line item mentioned in it
#      ("Gesamtpreis inkl. Flug" is a total, not a flight price),
#   2. specific line items (fees, flight, transfer, drinks, extras, discount),
#   3. a per-person qualifier,
#   4. cabin price / entry price.
PER_PERSON_RE = r"pro person|pro erwachsene|p\.\s?p\.|\bpp\b|je person|per person|pro passagier"
TOTALISH_RE = (
    r"gesamtpreis|gesamtsumme|gesamtbetrag|endpreis|endbetrag|zu zahlender|zu zahlen"
    r"|gesamt zu zahlen|reisepreis gesamt|total|summe gesamt"
)
FINALISH_RE = r"endpreis|endbetrag|zu zahlender|zu zahlen|gesamt zu zahlen"

ITEM_MAP: List[Tuple[str, str]] = [
    (r"servicegeb(?:\u00fc|ue)hr|serviceentgelt|service charge|trinkgeld|hafengeb(?:\u00fc|ue)hr"
     r"|hafentaxen|steuern und geb(?:\u00fc|ue)hren|geb(?:\u00fc|ue)hren und steuern"
     r"|obligatorische service", "service_fee"),
    (r"flugpreis|flugpaket|fluganteil|flugzuschlag|^flug\b|\bflug\b.*(?:preis|paket|anteil)"
     r"|air fare|flight", "flight_price"),
    (r"\btransfer\b|transferleistung|bustransfer|shuttle", "transfer_price"),
    (r"getr(?:\u00e4|ae)nkepaket|getr(?:\u00e4|ae)nke|drinks package|easy paket|premium extra"
     r"|all inclusive paket", "drinks_package_price"),
    (r"zusatzleistung|zusatzoption|\bextras?\b|ausflugspaket|versicherung|wlan|internetpaket"
     r"|spa[- ]paket|parken", "extras_price"),
    (r"rabatt|erm(?:\u00e4|ae)\u00dfigung|ermaessigung|nachlass|discount|gutschrift|preisvorteil"
     r"|ersparnis|sie sparen", "discount"),
]

CABIN_RE = r"kabinenpreis|preis (?:der|f(?:\u00fc|ue)r die) kabine|kabine gesamt|preis pro kabine"
STARTING_RE = (
    r"^ab\s|\bab\b\s*$|\bab\s+[\d.,]+|einstiegspreis|startpreis|preis ab|ab preis|schon ab"
)

# Kept for backwards compatible introspection/tests.
LABEL_MAP: List[Tuple[str, str]] = ITEM_MAP + [
    (TOTALISH_RE, "total_price"),
    (PER_PERSON_RE, "price_per_person"),
    (CABIN_RE, "cabin_price"),
    (STARTING_RE, "starting_price"),
]

_PROMO_RE = re.compile(
    r"(?:aktionscode|promocode|promo[- ]?code|gutscheincode|preiscode|angebotscode)\s*[:\-]?\s*"
    r"([A-Z0-9][A-Z0-9_\-]{2,24})",
    re.IGNORECASE,
)

SOLD_OUT_MARKERS = (
    "ausverkauft", "nicht mehr verf", "keine verf", "leider nicht verf", "sold out",
    "nicht buchbar", "keine kabinen", "kontingent ersch",
)
BLOCK_MARKERS = (
    "captcha", "recaptcha", "hcaptcha", "cf-challenge", "cloudflare",
    "sind sie ein mensch", "are you human", "access denied", "zugriff verweigert",
    "unusual traffic", "ungew", "bot detection", "request blocked", "attention required",
    "verify you are human", "just a moment",
)
SESSION_EXPIRED_MARKERS = (
    "sitzung abgelaufen", "session expired", "sitzung ist abgelaufen", "erneut anmelden",
    "zeit(?:ü|ue)berschreitung der sitzung", "warenkorb abgelaufen",
)
PRICE_CHANGED_MARKERS = (
    "preis hat sich ge", "preis wurde ge", "preis(?:ä|ae)nderung", "neuer preis",
    "price has changed", "aktualisierter preis",
)


def detect_currency(text: str) -> Optional[str]:
    if not text:
        return None
    upper = text.upper()
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text or symbol in upper:
            return code
    return None


def parse_amount(text: Optional[str], *, allow_small: bool = False) -> Optional[float]:
    """Parse a single monetary amount out of ``text``.

    Returns ``None`` when the text contains no unambiguous amount, several
    conflicting amounts, or an implausible value.
    """
    if not text:
        return None
    cleaned = str(text).replace(" ", " ").strip()
    if not cleaned:
        return None
    matches = _NUMBER_RE.findall(cleaned)
    if not matches:
        return None
    values = []
    for raw in matches:
        value = _to_float(raw)
        if value is None:
            continue
        low = 0.0 if allow_small else MIN_PLAUSIBLE
        if low <= value <= MAX_PLAUSIBLE:
            values.append(value)
    if not values:
        return None
    # Several different amounts in one string -> ambiguous, refuse to guess.
    if len({round(v, 2) for v in values}) > 1:
        return None
    return values[0]


def parse_amounts(text: Optional[str]) -> List[float]:
    """All plausible amounts contained in ``text`` (ordered as they appear)."""
    if not text:
        return []
    out: List[float] = []
    for raw in _NUMBER_RE.findall(str(text).replace(" ", " ")):
        value = _to_float(raw)
        if value is not None and MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE:
            out.append(value)
    return out


def _to_float(raw: str) -> Optional[float]:
    token = raw.strip().replace(" ", "").replace(" ", "")
    if not token:
        return None
    has_dot = "." in token
    has_comma = "," in token
    try:
        if has_dot and has_comma:
            # The right-most separator is the decimal separator.
            if token.rfind(",") > token.rfind("."):
                token = token.replace(".", "").replace(",", ".")
            else:
                token = token.replace(",", "")
        elif has_comma:
            parts = token.split(",")
            if len(parts) == 2 and len(parts[1]) in (1, 2):
                token = token.replace(",", ".")
            else:  # 1,234 -> thousands separator
                token = token.replace(",", "")
        elif has_dot:
            parts = token.split(".")
            if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:
                # 1.234 -> German thousands separator
                token = token.replace(".", "")
            elif len(parts) > 2:
                token = token.replace(".", "")
        return round(float(token), 2)
    except ValueError:
        return None


def classify_label(label: Optional[str]) -> Optional[str]:
    """Map a German price label onto a breakdown field (see priority rules)."""
    if not label:
        return None
    text = " ".join(str(label).lower().split())
    if not text:
        return None
    has_pp = bool(re.search(PER_PERSON_RE, text))
    if re.search(TOTALISH_RE, text):
        if has_pp:
            return "price_per_person"
        return "final_price" if re.search(FINALISH_RE, text) else "total_price"
    for pattern, field in ITEM_MAP:
        if re.search(pattern, text):
            return field
    if has_pp:
        return "price_per_person"
    if re.search(CABIN_RE, text):
        return "cabin_price"
    if re.search(STARTING_RE, text):
        return "starting_price"
    return None


def parse_breakdown_lines(lines: List[str]) -> Dict[str, float]:
    """Turn ``["Gesamtpreis 2.876,00 €", ...]`` into a field->value mapping.

    A field is only filled once (first, most specific occurrence wins) and only
    when the amount is unambiguous.
    """
    out: Dict[str, float] = {}
    for line in lines:
        if not line:
            continue
        text = " ".join(str(line).split())
        if len(text) > 240:
            continue
        field = classify_label(text)
        if not field:
            continue
        amount = parse_amount(text, allow_small=field in {"service_fee", "transfer_price", "extras_price"})
        if amount is None:
            continue
        if field == "discount":
            amount = abs(amount)
        out.setdefault(field, amount)
    return out


def find_promo_code(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    match = _PROMO_RE.search(str(text))
    if not match:
        return None
    code = match.group(1).strip()
    return code if 3 <= len(code) <= 24 else None


def _contains(text: str, markers) -> Optional[str]:
    low = (text or "").lower()
    for marker in markers:
        if re.search(marker, low):
            return marker
    return None


def detect_sold_out(text: str) -> Optional[str]:
    return _contains(text, SOLD_OUT_MARKERS)


def detect_block(text: str) -> Optional[str]:
    return _contains(text, BLOCK_MARKERS)


def detect_session_expired(text: str) -> Optional[str]:
    return _contains(text, SESSION_EXPIRED_MARKERS)


def detect_price_changed(text: str) -> Optional[str]:
    return _contains(text, PRICE_CHANGED_MARKERS)
