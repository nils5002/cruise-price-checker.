"""Browser profile configuration."""
from __future__ import annotations

from app.browser.profiles import (
    COOKIE_MODES,
    DEFAULT_PROFILE_KEYS,
    PROFILES,
    REFERRER_URLS,
    UNIFIED_CONDITIONS,
    available_profiles,
    clean_profiles,
    returning_profiles,
)
from app.browser.session import proxy_config


def test_all_required_profiles_exist():
    for key in (
        "clean_win_chrome",
        "clean_mac_chrome",
        "clean_iphone",
        "clean_android",
        "clean_firefox",
        "returning_visitor",
    ):
        assert key in PROFILES
    assert DEFAULT_PROFILE_KEYS[0] == "clean_win_chrome"


def test_conditions_are_identical_across_profiles():
    for profile in PROFILES.values():
        options = profile.context_options("140.0.0.0")
        assert options["locale"] == UNIFIED_CONDITIONS["locale"] == "de-DE"
        assert options["timezone_id"] == "Europe/Berlin"
        assert options["extra_http_headers"]["Accept-Language"].startswith("de-DE")


def test_mobile_profiles_emulate_devices():
    iphone = PROFILES["clean_iphone"].context_options()
    assert iphone["is_mobile"] is True and iphone["has_touch"] is True
    assert iphone["device_scale_factor"] == 3.0
    assert iphone["viewport"]["width"] < 500
    android = PROFILES["clean_android"].context_options()
    assert android["is_mobile"] is True
    assert "Android" in android["user_agent"]


def test_firefox_profile_has_no_mobile_flags():
    options = PROFILES["clean_firefox"].context_options()
    assert "is_mobile" not in options
    assert "device_scale_factor" not in options


def test_user_agent_placeholder_is_filled():
    ua = PROFILES["clean_win_chrome"].resolved_user_agent("141.0.0.0")
    assert "Chrome/141.0.0.0" in ua
    assert "{chrome}" not in PROFILES["clean_win_chrome"].resolved_user_agent()


def test_clean_and_returning_profiles_are_separated():
    clean_keys = {p.key for p in clean_profiles()}
    returning_keys = {p.key for p in returning_profiles()}
    assert not clean_keys & returning_keys
    assert all(p.persist_state is False for p in clean_profiles())
    assert PROFILES["returning_visitor"].persist_state is True


def test_firefox_can_be_disabled():
    keys = {p.key for p in available_profiles(enable_firefox=False)}
    assert "clean_firefox" not in keys


def test_cookie_modes_and_referrers():
    assert set(COOKIE_MODES) == {"necessary", "all", "none"}
    assert REFERRER_URLS["direct"] is None
    assert "google" in REFERRER_URLS and REFERRER_URLS["google"].startswith("https://")


def test_proxy_credentials_are_resolved_from_label_only():
    config = proxy_config("DE Testanschluss")
    assert config["server"] == "http://203.0.113.10:3128"
    assert config["username"] == "proxyuser"
    assert proxy_config("gibt-es-nicht") is None
    assert proxy_config(None) is None
