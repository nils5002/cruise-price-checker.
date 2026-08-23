"""Browser profile definitions.

Each profile describes one *browser condition* under which the very same offer
is opened.  Everything that must stay identical between profiles (language,
locale, timezone, currency) lives in :data:`UNIFIED_CONDITIONS`; everything that
is deliberately different (device, UA, touch) lives in the profile itself.

No fingerprint spoofing beyond the documented, Playwright-native device
emulation is performed, and no anti-bot mechanism is circumvented.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# Conditions that MUST be identical for every profile so the comparison is
# meaningful.
UNIFIED_CONDITIONS: Dict[str, Any] = {
    "language": "de-DE",
    "locale": "de-DE",
    "accept_language": "de-DE,de;q=0.9,en;q=0.6",
    "timezone": "Europe/Berlin",
    "currency": "EUR",
    "country": "DE",
    "color_scheme": "light",
    "reduced_motion": "no-preference",
}

COOKIE_MODES = ("necessary", "all", "none")
COOKIE_MODE_LABELS = {
    "necessary": "nur notwendige",
    "all": "alle akzeptiert",
    "none": "Banner nicht bestätigt",
}

REFERRER_MODES = ("direct", "google", "bing")
REFERRER_URLS = {
    "direct": None,
    "google": "https://www.google.de/",
    "bing": "https://www.bing.com/",
}


@dataclass
class BrowserProfile:
    key: str
    label: str
    browser: str = "chromium"           # chromium | firefox | webkit
    device: str = "desktop"             # desktop | mobile
    platform: str = "Windows"
    user_agent: Optional[str] = None
    viewport: Dict[str, int] = field(default_factory=lambda: {"width": 1512, "height": 892})
    device_scale_factor: float = 1.0
    is_mobile: bool = False
    has_touch: bool = False
    session_type: str = "clean"          # clean | returning
    persist_state: bool = False
    default_cookie_mode: str = "necessary"
    enabled: bool = True
    description: str = ""

    # ------------------------------------------------------------------
    def resolved_user_agent(self, chrome_major: Optional[str] = None) -> Optional[str]:
        """Fill the ``{chrome}`` placeholder with the real engine version.

        Keeping the advertised Chrome version in sync with the actual bundled
        Chromium avoids an artificial, inconsistent fingerprint.
        """
        if not self.user_agent:
            return None
        if "{chrome}" in self.user_agent:
            return self.user_agent.replace("{chrome}", chrome_major or "138.0.0.0")
        return self.user_agent

    def context_options(self, chrome_major: Optional[str] = None) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "locale": UNIFIED_CONDITIONS["locale"],
            "timezone_id": UNIFIED_CONDITIONS["timezone"],
            "color_scheme": UNIFIED_CONDITIONS["color_scheme"],
            "reduced_motion": UNIFIED_CONDITIONS["reduced_motion"],
            "viewport": dict(self.viewport),
            "device_scale_factor": self.device_scale_factor,
            "extra_http_headers": {"Accept-Language": UNIFIED_CONDITIONS["accept_language"]},
            "ignore_https_errors": False,
            "java_script_enabled": True,
        }
        ua = self.resolved_user_agent(chrome_major)
        if ua:
            opts["user_agent"] = ua
        if self.browser == "firefox":
            # Firefox does not support mobile emulation / device scale factor.
            opts.pop("device_scale_factor", None)
        else:
            opts["is_mobile"] = self.is_mobile
            opts["has_touch"] = self.has_touch
        return opts

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["user_agent"] = self.resolved_user_agent()
        return data


_CHROME_WIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/{chrome} Safari/537.36"
)
_CHROME_MAC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/{chrome} Safari/537.36"
)
_ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/{chrome} Mobile Safari/537.36"
)
# iPhone: Chromium cannot become Safari/WebKit.  We emulate an iPhone viewport
# with the matching mobile UA -- documented as emulation, not as a real device.
_IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
)
_FIREFOX_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0"
)


PROFILES: Dict[str, BrowserProfile] = {
    p.key: p
    for p in [
        BrowserProfile(
            key="clean_win_chrome",
            label="Clean Desktop Chrome Windows",
            browser="chromium",
            device="desktop",
            platform="Windows 10/11",
            user_agent=_CHROME_WIN_UA,
            viewport={"width": 1512, "height": 892},
            description="Frisches Chromium-Profil, Windows-User-Agent, keine Cookies.",
        ),
        BrowserProfile(
            key="clean_mac_chrome",
            label="Clean Desktop Chrome macOS",
            browser="chromium",
            device="desktop",
            platform="macOS",
            user_agent=_CHROME_MAC_UA,
            viewport={"width": 1440, "height": 900},
            description="Frisches Chromium-Profil, macOS-User-Agent, keine Cookies.",
        ),
        BrowserProfile(
            key="clean_iphone",
            label="Clean iPhone",
            browser="chromium",
            device="mobile",
            platform="iOS 18",
            user_agent=_IPHONE_UA,
            viewport={"width": 393, "height": 852},
            device_scale_factor=3.0,
            is_mobile=True,
            has_touch=True,
            description="Mobile Emulation eines aktuellen iPhones (Viewport, Touch, DPR 3).",
        ),
        BrowserProfile(
            key="clean_android",
            label="Clean Android",
            browser="chromium",
            device="mobile",
            platform="Android 15",
            user_agent=_ANDROID_UA,
            viewport={"width": 412, "height": 915},
            device_scale_factor=2.625,
            is_mobile=True,
            has_touch=True,
            description="Mobile Emulation eines aktuellen Android-Smartphones.",
        ),
        BrowserProfile(
            key="clean_firefox",
            label="Clean Desktop Firefox",
            browser="firefox",
            device="desktop",
            platform="Windows 10/11",
            user_agent=_FIREFOX_UA,
            viewport={"width": 1440, "height": 900},
            description="Frisches Firefox-Profil (nur wenn ENABLE_FIREFOX=true).",
        ),
        BrowserProfile(
            key="returning_visitor",
            label="Returning Visitor",
            browser="chromium",
            device="desktop",
            platform="Windows 10/11",
            user_agent=_CHROME_WIN_UA,
            viewport={"width": 1512, "height": 892},
            session_type="returning",
            persist_state=True,
            default_cookie_mode="all",
            description=(
                "Persistentes Profil: Cookies/Storage werden absichtlich behalten, "
                "um wiederholte Aufrufe derselben Reise zu testen. Wird nie mit "
                "Clean-Profilen gemischt."
            ),
        ),
    ]
}

DEFAULT_PROFILE_KEYS: List[str] = [
    "clean_win_chrome",
    "clean_mac_chrome",
    "clean_iphone",
    "clean_android",
    "clean_firefox",
    "returning_visitor",
]


def get_profile(key: str) -> BrowserProfile:
    if key not in PROFILES:
        raise KeyError(f"Unbekanntes Browserprofil: {key}")
    return PROFILES[key]


def available_profiles(enable_firefox: bool = True) -> List[BrowserProfile]:
    out = []
    for key in DEFAULT_PROFILE_KEYS:
        profile = PROFILES[key]
        if profile.browser == "firefox" and not enable_firefox:
            continue
        out.append(profile)
    return out


def clean_profiles() -> List[BrowserProfile]:
    return [p for p in PROFILES.values() if p.session_type == "clean"]


def returning_profiles() -> List[BrowserProfile]:
    return [p for p in PROFILES.values() if p.session_type == "returning"]
