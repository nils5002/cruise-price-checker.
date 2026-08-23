"""Input validation, SSRF protection and safe filesystem paths."""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from typing import List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from fastapi import Header, HTTPException, status

from app.config import settings

# Only official provider domains may ever be opened by Playwright.
ALLOWED_DOMAIN_SUFFIXES: Tuple[str, ...] = (
    "msccruises.de",
    "msccruises.com",
    "msccruises.at",
    "msccruises.ch",
)

# Extra hosts that MSC pages legitimately redirect to for booking flows.
ALLOWED_EXACT_HOSTS: Tuple[str, ...] = (
    "www.msccruises.de",
    "msccruises.de",
    "book.msccruises.de",
    "booking.msccruises.de",
)

_BLOCKED_SCHEMES = {"file", "ftp", "data", "javascript", "about", "blob", "chrome"}
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


class UrlValidationError(ValueError):
    """Raised when a URL is not acceptable for automation."""


def host_is_allowed(host: str) -> bool:
    host = (host or "").lower().strip().rstrip(".")
    if not host:
        return False
    if host in ALLOWED_EXACT_HOSTS:
        return True
    return any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_DOMAIN_SUFFIXES)


def _resolves_to_private_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # Cannot resolve -> treat as unsafe.
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return True
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def validate_target_url(raw_url: str, *, allow_mock: Optional[bool] = None, resolve_dns: bool = True) -> str:
    """Validate a user supplied booking URL.

    Returns the normalised URL or raises :class:`UrlValidationError`.
    """
    if allow_mock is None:
        allow_mock = settings.enable_mock_provider

    url = (raw_url or "").strip()
    if not url:
        raise UrlValidationError("URL fehlt.")
    if len(url) > 2048:
        raise UrlValidationError("URL ist zu lang (max. 2048 Zeichen).")
    if any(ch in url for ch in ("\n", "\r", "\t", " ")):
        raise UrlValidationError("URL enthält ungültige Zeichen.")

    if url.startswith("mock://"):
        if not allow_mock:
            raise UrlValidationError("Mock-Provider ist deaktiviert.")
        return url

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme in _BLOCKED_SCHEMES or scheme not in {"http", "https"}:
        raise UrlValidationError("Nur https-URLs offizieller Anbieter-Domains sind erlaubt.")
    if scheme == "http":
        parsed = parsed._replace(scheme="https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UrlValidationError("URL enthält keinen Hostnamen.")
    if parsed.username or parsed.password:
        raise UrlValidationError("URLs mit Zugangsdaten sind nicht erlaubt.")
    if parsed.port and parsed.port not in (80, 443):
        raise UrlValidationError("Nur die Standard-Ports 80/443 sind erlaubt.")
    if not host_is_allowed(host):
        raise UrlValidationError(
            "Diese Domain ist nicht freigegeben. Erlaubt sind derzeit nur offizielle "
            "MSC-Domains (z. B. www.msccruises.de)."
        )
    try:
        ipaddress.ip_address(host)
        raise UrlValidationError("Direkte IP-Adressen sind nicht erlaubt.")
    except ValueError:
        pass
    if resolve_dns and _resolves_to_private_ip(host):
        raise UrlValidationError("Host zeigt auf eine interne Adresse und wird blockiert.")

    normalised = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )
    return normalised


def safe_relpath(*segments: str) -> str:
    """Join user-influenced path segments without ever escaping the data dir."""
    clean: List[str] = []
    for segment in segments:
        token = re.sub(r"[^A-Za-z0-9._-]+", "-", str(segment)).strip("-.") or "x"
        if not _SAFE_SEGMENT.match(token):  # pragma: no cover - defensive
            raise ValueError("unsicheres Pfadsegment")
        clean.append(token[:80])
    return os.path.join(*clean)


def resolve_within(base_dir: str, relative: str) -> str:
    """Resolve ``relative`` inside ``base_dir``; raise if it escapes."""
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, relative.lstrip("/")))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError("Pfad liegt ausserhalb des Datenverzeichnisses")
    return target


async def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Dependency that protects mutating and admin endpoints."""
    expected = settings.api_key
    if not expected:
        return
    if not x_api_key or x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder fehlender API-Key.",
        )
