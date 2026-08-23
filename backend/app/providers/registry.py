"""Provider registry.

Adding a vendor = implementing :class:`CruiseProvider` and registering it here.
Nothing else in the codebase needs to change.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.config import settings
from app.providers.base import CruiseProvider
from app.providers.mock.adapter import MockProvider
from app.providers.msc.adapter import MscProvider

# Planned vendors -- surfaced in the admin UI so the roadmap is visible.
PLANNED_PROVIDERS = [
    {"key": "ehoi", "label": "e-hoi", "status": "geplant"},
    {"key": "kreuzfahrtberater", "label": "Kreuzfahrtberater", "status": "geplant"},
    {"key": "dreamlines", "label": "Dreamlines", "status": "geplant"},
    {"key": "logitravel", "label": "Logitravel", "status": "geplant"},
    {"key": "holidaycheck", "label": "HolidayCheck", "status": "geplant"},
    {"key": "check24", "label": "CHECK24", "status": "geplant"},
]

_REGISTRY: Dict[str, CruiseProvider] = {}


def register(provider: CruiseProvider) -> None:
    _REGISTRY[provider.key] = provider


register(MscProvider())
if settings.enable_mock_provider:
    register(MockProvider())


def all_providers() -> List[CruiseProvider]:
    return list(_REGISTRY.values())


def get_provider(key: str) -> CruiseProvider:
    if key not in _REGISTRY:
        raise KeyError(f"Unbekannter Provider: {key}")
    return _REGISTRY[key]


def provider_for_url(url: str) -> Optional[CruiseProvider]:
    for provider in _REGISTRY.values():
        try:
            if provider.can_handle_url(url):
                return provider
        except Exception:  # pragma: no cover - a broken adapter must not break others
            continue
    return None


def provider_info() -> List[Dict[str, object]]:
    active = [
        {
            "key": provider.key,
            "label": provider.label,
            "status": "aktiv",
            "requires_browser": provider.requires_browser,
            "allowed_hosts": list(provider.allowed_hosts),
        }
        for provider in _REGISTRY.values()
    ]
    return active + [dict(item, requires_browser=True, allowed_hosts=[]) for item in PLANNED_PROVIDERS]
