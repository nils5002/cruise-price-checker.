"""URL allowlist / SSRF protection, safe paths, log redaction."""
from __future__ import annotations

import pytest

from app.core.logging_setup import redact
from app.core.security import (
    UrlValidationError,
    host_is_allowed,
    resolve_within,
    safe_relpath,
    validate_target_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data",
        "https://evil.com/booking",
        "https://msccruises.de.evil.com/",
        "https://127.0.0.1/",
        "https://localhost/",
        "javascript:alert(1)",
        "https://user:pass@www.msccruises.de/",
        "https://www.msccruises.de:8080/",
        "",
        "https://www.msccruises.de/\nSet-Cookie: x",
    ],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(UrlValidationError):
        validate_target_url(url, allow_mock=False, resolve_dns=False)


def test_accepts_official_domains():
    assert validate_target_url(
        "https://www.msccruises.de/booking?x=1", resolve_dns=False
    ).startswith("https://www.msccruises.de/booking")
    # http is upgraded to https
    assert validate_target_url("http://www.msccruises.de/x", resolve_dns=False).startswith("https://")


def test_mock_scheme_is_gated():
    assert validate_target_url("mock://cruise/1", allow_mock=True) == "mock://cruise/1"
    with pytest.raises(UrlValidationError):
        validate_target_url("mock://cruise/1", allow_mock=False)


def test_host_allowlist():
    assert host_is_allowed("www.msccruises.de")
    assert host_is_allowed("book.msccruises.de")
    assert not host_is_allowed("msccruises.de.attacker.net")
    assert not host_is_allowed("")


def test_safe_paths():
    assert safe_relpath("scan-1", "clean_iphone-r1") == "scan-1/clean_iphone-r1"
    assert ".." not in safe_relpath("../../etc", "passwd")
    with pytest.raises(ValueError):
        resolve_within("/tmp/base", "../../etc/passwd")


def test_redaction_of_secrets():
    text = redact("cookie: abc123; proxy=http://user:pw@1.2.3.4:8080 password=hunter2 4111111111111111")
    assert "abc123" not in text
    assert "hunter2" not in text
    assert "4111111111111111" not in text
    assert "user:pw" not in text


def test_redaction_keeps_numeric_log_arguments():
    """Zahlen duerfen nicht zu Strings werden -- sonst brechen %d/%.0f-Formate."""
    import logging

    from app.core.logging_setup import RedactionFilter

    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Wartezeit %.0fs, Versuch %d, Ziel %s",
        args=(3.0, 2, "http://user:pw@host/x"),
        exc_info=None,
    )
    assert RedactionFilter(["geheim"]).filter(record) is True
    formatted = record.getMessage()          # wuerde bei String-Args crashen
    assert formatted.startswith("Wartezeit 3s, Versuch 2")
    assert "user:pw" not in formatted


def test_redaction_scrubs_string_arguments():
    import logging

    from app.core.logging_setup import RedactionFilter

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Wert: %s",
        args=("mein-geheimes-token",),
        exc_info=None,
    )
    RedactionFilter(["mein-geheimes-token"]).filter(record)
    assert "mein-geheimes-token" not in record.getMessage()
