"""All MSC specific selectors live here -- and nowhere else.

If MSC changes its markup, this is the only file that needs an update.  Every
entry is a *list of candidates* that is tried in order (semantic first), so a
single markup change does not break the whole flow.
"""
from __future__ import annotations

from typing import Any, Dict, List

Spec = Dict[str, Any]

# --- cookie consent --------------------------------------------------------
COOKIE_BANNER: List[Spec] = [
    {"css": "#onetrust-banner-sdk"},
    {"css": "#onetrust-consent-sdk"},
    {"css": "#usercentrics-root"},
    {"css": "#cmpbox"},
    {"role": "dialog", "name": "Cookie", "regex": True},
    {"css": "[id*='cookie'][class*='banner']"},
    {"css": "[class*='cookie-banner'], [class*='cookieBanner'], [class*='consent']"},
]

COOKIE_ACCEPT_ALL: List[Spec] = [
    {"css": "#onetrust-accept-btn-handler"},
    {"role": "button", "name": r"^(alle[s]? akzeptieren|alle cookies akzeptieren|akzeptieren und weiter)", "regex": True},
    {"role": "button", "name": r"alle akzeptieren", "regex": True},
    {"css": "button#cmpwelcomebtnyes, button[aria-label*='Alle akzeptieren']"},
    {"role": "button", "name": r"^(zustimmen|einverstanden|accept all)", "regex": True},
]

COOKIE_ONLY_NECESSARY: List[Spec] = [
    {"css": "#onetrust-reject-all-handler"},
    {"css": ".ot-pc-refuse-all-handler"},
    {"role": "button", "name": r"(nur (technisch )?notwendige|nur erforderliche|ohne einwilligung|alle ablehnen|ablehnen)", "regex": True},
    {"role": "button", "name": r"(nur essenzielle|essenzielle cookies|weiter ohne zustimmung)", "regex": True},
    {"css": "button[aria-label*='ablehnen'], button[aria-label*='Ablehnen']"},
]

COOKIE_SETTINGS: List[Spec] = [
    {"css": "#onetrust-pc-btn-handler"},
    {"role": "button", "name": r"(cookie[- ]einstellungen|einstellungen anpassen|individuelle einstellungen|mehr optionen|verwalten)", "regex": True},
]

COOKIE_SAVE_SELECTION: List[Spec] = [
    {"css": ".save-preference-btn-handler"},
    {"role": "button", "name": r"(auswahl bestätigen|auswahl speichern|meine auswahl|speichern und schließen|einstellungen speichern)", "regex": True},
]

# --- entering the booking flow --------------------------------------------
START_BOOKING: List[Spec] = [
    {"role": "link", "name": r"(preise (und|&) verf(ü|ue)gbarkeit|verf(ü|ue)gbarkeit (und|&) preise)", "regex": True},
    {"role": "button", "name": r"(preise (und|&) verf(ü|ue)gbarkeit|jetzt buchen|weiter zur buchung|reise buchen)", "regex": True},
    {"role": "link", "name": r"(jetzt buchen|zur buchung|angebot ansehen|preise ansehen)", "regex": True},
    {"role": "button", "name": r"(auswählen|ausw(ä|ae)hlen|weiter)", "regex": True},
]

# --- cabin type / experience ---------------------------------------------
CABIN_TYPE_OPTIONS: List[Spec] = [
    {"css": "[data-testid*='cabin-type'], [data-test*='cabinType']"},
    {"role": "radio", "name": r"(innen|au(ß|ss)en|balkon|suite)", "regex": True},
    {"role": "button", "name": r"(innenkabine|au(ß|ss)enkabine|balkonkabine|suite)", "regex": True},
    {"css": "[class*='cabin-type'] button, [class*='cabinType'] button"},
]

CABIN_CATEGORY_CARDS: List[Spec] = [
    {"css": "[data-testid*='cabin-category'], [data-testid*='category-card']"},
    {"css": "[class*='cabin-category'], [class*='categoryCard'], [class*='cabin-card']"},
    {"role": "listitem"},
]

CABIN_SELECT_BUTTON: List[Spec] = [
    {"role": "button", "name": r"^(ausw(ä|ae)hlen|kabine ausw(ä|ae)hlen|diese kabine|w(ä|ae)hlen)", "regex": True},
    {"role": "link", "name": r"^(ausw(ä|ae)hlen|kabine ausw(ä|ae)hlen)", "regex": True},
    {"css": "button[data-testid*='select']"},
]

# --- rate / tariff (Bella, Fantastica, Aurea, Yacht Club) ----------------
RATE_OPTIONS: List[Spec] = [
    {"css": "[data-testid*='rate'], [data-testid*='experience'], [data-testid*='fare']"},
    {"role": "radio", "name": r"(bella|fantastica|aurea|yacht club|super family|flex)", "regex": True},
    {"role": "button", "name": r"(bella|fantastica|aurea|yacht club|super family|flex)", "regex": True},
    {"css": "[class*='experience'] button, [class*='rate-card'], [class*='fare']"},
]

RATE_SELECT_BUTTON: List[Spec] = [
    {"role": "button", "name": r"^(ausw(ä|ae)hlen|tarif ausw(ä|ae)hlen|w(ä|ae)hlen|weiter)", "regex": True},
]

# --- passengers -----------------------------------------------------------
PASSENGER_SUMMARY: List[Spec] = [
    {"css": "[data-testid*='passenger'], [data-testid*='guest'], [class*='passenger-summary']"},
    {"text": r"\d+\s+(erwachsene|g(ä|ae)ste|passagiere)", "regex": True},
]

# --- generic navigation ---------------------------------------------------
CONTINUE_BUTTONS: List[Spec] = [
    {"role": "button", "name": r"^(weiter|weiter zur (kabinenauswahl|auswahl|übersicht|zusammenfassung)|fortfahren|n(ä|ae)chster schritt)", "regex": True},
    {"role": "link", "name": r"^(weiter|fortfahren|n(ä|ae)chster schritt)", "regex": True},
    {"role": "button", "name": r"^(überspringen|ohne (zusatz|extras)|nein, danke|kein paket)", "regex": True},
]

# --- price areas ----------------------------------------------------------
PRICE_SUMMARY_CONTAINERS: List[Spec] = [
    {"css": "[data-testid*='summary'], [data-testid*='total'], [data-testid*='price']"},
    {"css": "[class*='price-summary'], [class*='priceSummary'], [class*='booking-summary'], [class*='cart']"},
    {"css": "aside, [role='complementary']"},
    {"css": "[class*='total'], [class*='summary']"},
]

STARTING_PRICE: List[Spec] = [
    {"css": "[data-testid*='from-price'], [class*='from-price'], [class*='price-from']"},
    {"text": r"^\s*ab\s+[\d.,]+\s*(€|EUR)", "regex": True},
]

TRIP_HEADER: List[Spec] = [
    {"role": "heading", "level": 1},
    {"css": "[data-testid*='itinerary'], [class*='itinerary-header'], [class*='cruise-header']"},
    {"role": "heading", "level": 2},
]

# --- error / state markers ----------------------------------------------
ERROR_BANNERS: List[Spec] = [
    {"role": "alert"},
    {"css": "[class*='error'], [class*='alert-danger'], [class*='notification--error']"},
]

# --- hard safety guard ---------------------------------------------------
#: Controls whose accessible name matches any of these must NEVER be clicked.
FORBIDDEN_CLICK_PATTERNS: List[str] = [
    r"zahlungspflichtig",
    r"jetzt bezahlen",
    r"bezahlen",
    r"zur kasse",
    r"buchung abschlie(ß|ss)en",
    r"verbindlich (buchen|bestellen)",
    r"jetzt buchen und bezahlen",
    r"kaufen",
    r"bestellung abschlie(ß|ss)en",
    r"kreditkarte",
    r"payment",
    r"pay now",
    r"complete booking",
    r"anzahlung leisten",
    r"unterschreiben",
    r"vertrag",
]

#: Page markers that mean "we are at (or past) the booking commitment".
BOOKING_COMMIT_MARKERS: List[str] = [
    "zahlungsart",
    "zahlungsmittel",
    "kreditkartennummer",
    "kartennummer",
    r"\biban\b",
    "rechnungsadresse",
    "zahlungsdaten",
    "zahlungsinformationen",
    r"\bsepa\b",
    r"\bcvc\b",
    r"\bcvv\b",
    "zahlungspflichtig bestellen",
]

#: Markers of the passenger-data step -- we stop there (no personal data).
PERSONAL_DATA_MARKERS: List[str] = [
    "vorname",
    "nachname",
    "geburtsdatum",
    "passnummer",
    "ausweisnummer",
    "staatsangeh",
    "telefonnummer",
    "e-mail-adresse eingeben",
    "reisepass",
]

PAGE_TYPE_MARKERS = {
    "offer": ["reiseverlauf", "itinerar", "kreuzfahrt", "reise-highlights", "an bord"],
    "availability": ["preise und verf", "verf(ü|ue)gbarkeit", "abfahrtsdaten", "termin w"],
    "cabin_type": ["kabinenart", "kabinentyp", "innenkabine", "balkonkabine"],
    "cabin_category": ["kabinenkategorie", "kategorie", "deckplan", "kabine ausw"],
    "rate": ["bella", "fantastica", "aurea", "yacht club", "tarif", "experience"],
    "extras": ["getr(ä|ae)nkepaket", "ausflugspaket", "zusatzleistungen", "pakete hinzuf"],
    "summary": ["zusammenfassung", "ihre buchung", "warenkorb", "buchungs(ü|ue)bersicht", "preis(ü|ue)bersicht"],
    "passenger_data": PERSONAL_DATA_MARKERS,
    "payment": BOOKING_COMMIT_MARKERS,
}

#: MSC fleet -- longest names first so "World Europa" wins over "World".
KNOWN_SHIPS = [
    "World America", "World Europa", "World Asia",
    "Armonia", "Bellissima", "Divina", "Euribia", "Fantasia", "Grandiosa", "Lirica",
    "Magnifica", "Meraviglia", "Musica", "Opera", "Orchestra", "Poesia", "Preziosa",
    "Seascape", "Seashore", "Seaside", "Seaview", "Sinfonia", "Splendida", "Virtuosa",
]

#: Words that follow "MSC" but are not ship names.
NOT_SHIP_WORDS = {
    "cruises", "cruise", "kreuzfahrten", "kreuzfahrt", "yacht", "club", "foundation",
    "voyagers", "starlight", "book", "bella", "fantastica", "aurea", "explora",
    "grand", "for", "me", "shop", "reisen", "flotte", "schiffe",
}

#: Tariff names MSC uses -- helps identify the offer.
KNOWN_TARIFFS = ["Bella", "Fantastica", "Aurea", "MSC Yacht Club", "Super Family", "Flex", "Smart"]
KNOWN_CABIN_TYPES = ["Innenkabine", "Aussenkabine", "Außenkabine", "Balkonkabine", "Suite", "Deluxe"]
BOARD_TERMS = ["Vollpension", "All Inclusive", "Halbpension", "Frühstück", "Getränkepaket inklusive"]
