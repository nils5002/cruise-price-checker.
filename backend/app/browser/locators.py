"""Robust locator helpers.

Preference order is deliberately *semantic*: ARIA role + accessible name, then
visible text, then test ids, then -- only as a last resort -- CSS.  A locator
spec is a small dict so provider adapters stay declarative:

    {"role": "button", "name": "Alle akzeptieren"}
    {"text": "Zur Kabinenauswahl"}
    {"testid": "cabin-card"}
    {"css": "#onetrust-accept-btn-handler"}
    {"label": "Erwachsene"}
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.core.logging_setup import get_logger

logger = get_logger(__name__)

LocatorSpec = Dict[str, Any]


def describe(spec: LocatorSpec) -> str:
    for key in ("role", "text", "testid", "label", "placeholder", "css"):
        if key in spec:
            name = spec.get("name")
            return f"{key}={spec[key]}" + (f"[{name}]" if name else "")
    return str(spec)


def build(page: Any, spec: LocatorSpec) -> Any:
    """Turn a spec into a Playwright locator."""
    scope = spec.get("scope")
    root = page.locator(scope) if scope else page
    if "role" in spec:
        kwargs: Dict[str, Any] = {}
        if spec.get("name"):
            kwargs["name"] = re.compile(spec["name"], re.IGNORECASE) if spec.get("regex") else spec["name"]
            kwargs["exact"] = bool(spec.get("exact", False))
        if spec.get("level"):
            kwargs["level"] = int(spec["level"])
        return root.get_by_role(spec["role"], **kwargs)
    if "text" in spec:
        value = re.compile(spec["text"], re.IGNORECASE) if spec.get("regex") else spec["text"]
        return root.get_by_text(value, exact=bool(spec.get("exact", False)))
    if "testid" in spec:
        return root.locator(f'[data-testid="{spec["testid"]}"], [data-test="{spec["testid"]}"], [data-qa="{spec["testid"]}"]')
    if "label" in spec:
        value = re.compile(spec["label"], re.IGNORECASE) if spec.get("regex") else spec["label"]
        return root.get_by_label(value)
    if "placeholder" in spec:
        return root.get_by_placeholder(spec["placeholder"])
    if "css" in spec:
        return root.locator(spec["css"])
    raise ValueError(f"Ungültiger Locator-Spec: {spec}")


def first_visible(
    page: Any,
    specs: Sequence[LocatorSpec],
    *,
    timeout_ms: int = 3_000,
    index: int = 0,
) -> Optional[Any]:
    """Return the first visible locator from ``specs`` (or ``None``)."""
    for spec in specs:
        try:
            locator = build(page, spec)
            count = locator.count()
            if count == 0:
                continue
            candidate = locator.nth(min(index, count - 1))
            candidate.wait_for(state="visible", timeout=timeout_ms)
            if candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


def visible_count(page: Any, specs: Sequence[LocatorSpec]) -> int:
    total = 0
    for spec in specs:
        try:
            total += build(page, spec).count()
        except Exception:
            continue
    return total


def text_of(locator: Any, limit: int = 4000) -> Optional[str]:
    if locator is None:
        return None
    try:
        text = locator.inner_text(timeout=4_000)
    except Exception:
        try:
            text = locator.text_content(timeout=4_000)
        except Exception:
            return None
    if not text:
        return None
    return " ".join(str(text).split())[:limit]


def collect_texts(page: Any, specs: Sequence[LocatorSpec], *, limit: int = 12) -> List[str]:
    """Inner texts of up to ``limit`` matching elements across all specs."""
    out: List[str] = []
    for spec in specs:
        try:
            locator = build(page, spec)
            count = min(locator.count(), limit)
        except Exception:
            continue
        for i in range(count):
            try:
                raw = locator.nth(i).inner_text(timeout=2_500)
            except Exception:
                continue
            if raw and raw.strip():
                out.append(raw)
            if len(out) >= limit:
                return out
    return out


def page_lines(page: Any, *, max_lines: int = 900) -> List[str]:
    """Visible text of the page as trimmed lines (used for text-driven parsing)."""
    try:
        raw = page.inner_text("body", timeout=8_000)
    except Exception:
        try:
            raw = page.content()
        except Exception:
            return []
        raw = re.sub(r"<[^>]+>", " ", raw)
    lines: List[str] = []
    for line in str(raw).splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            lines.append(cleaned)
        if len(lines) >= max_lines:
            break
    return lines


def merge_label_value_lines(lines: List[str]) -> List[str]:
    """Join a label line with the amount on the following line.

    Booking summaries frequently render ``Gesamtpreis`` and ``2.876,00 €`` as
    two separate nodes.
    """
    money = re.compile(r"(?:€|EUR|CHF)")
    digits = re.compile(r"\d")
    out: List[str] = list(lines)
    for index, line in enumerate(lines[:-1]):
        following = lines[index + 1]
        if money.search(line) and digits.search(line):
            continue
        if money.search(following) and digits.search(following) and len(following) <= 30:
            out.append(f"{line} {following}")
    return out
