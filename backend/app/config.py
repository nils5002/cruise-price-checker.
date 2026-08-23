"""Application configuration.

All secrets are read from the environment (see ``.env.example``).  Nothing in
here may ever be logged verbatim -- proxy URLs and SMTP credentials are treated
as secrets and are only ever referenced by their *label*.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- general -----------------------------------------------------------
    app_name: str = "Cruise Price Checker"
    environment: str = "production"
    log_level: str = "INFO"
    timezone: str = "Europe/Berlin"

    # Base path when running behind a reverse proxy (e.g. "/cruise").
    root_path: str = ""

    # --- persistence -------------------------------------------------------
    # SQLite by default so the stack boots without Postgres; switch by setting
    # DATABASE_URL=postgresql+psycopg2://user:pass@db:5432/cruise
    database_url: str = "sqlite:////data/cruise.db"
    data_dir: str = "/data"

    # --- api security ------------------------------------------------------
    # When set, mutating endpoints and the admin area require this token via
    # the "X-API-Key" header.
    api_key: Optional[str] = None
    cors_origins: str = "*"

    # --- browser automation ------------------------------------------------
    headless: bool = True
    enable_firefox: bool = True
    browser_timeout_ms: int = 45_000
    navigation_timeout_ms: int = 60_000
    # Conservative, deliberately slow pacing -- this is a price comparison
    # tool, not a scraper.
    min_delay_between_steps_ms: int = 1_200
    max_delay_between_steps_ms: int = 2_600
    delay_between_profiles_s: float = 8.0
    max_concurrent_scans: int = 1
    max_steps_per_profile: int = 14
    max_retries_per_profile: int = 2
    retry_backoff_base_s: float = 5.0
    max_scans_per_cruise_per_day: int = 6
    # Nach wie vielen blockierten Tests der gesamte Scan abgebrochen wird.
    # 1 = beim ersten harten Block aufhoeren (respektiert die Entscheidung der
    # Zielseite und vermeidet unnoetige weitere Anfragen). 0 = nie abbrechen.
    abort_scan_after_blocks: int = 1

    # --- feature switches --------------------------------------------------
    enable_mock_provider: bool = True
    enable_scheduler: bool = True
    enable_referrer_tests: bool = False
    enable_html_snapshots: bool = True
    enable_multi_round_verification: bool = True
    verification_rounds: int = 3
    enable_flight_comparison: bool = False
    preferred_airports: str = "DUS,CGN,DTM,FRA,AMS"

    # --- notifications -----------------------------------------------------
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_starttls: bool = True
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    homeassistant_webhook_url: Optional[str] = None

    # --- proxies (optional, opt-in) ---------------------------------------
    proxy_de_1: Optional[str] = None
    proxy_de_2: Optional[str] = None
    proxy_de_3: Optional[str] = None
    proxy_de_1_label: str = "DE Anschluss 1"
    proxy_de_2_label: str = "DE Anschluss 2"
    proxy_de_3_label: str = "DE Mobilfunk"

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @field_validator("root_path")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    # --- derived helpers ---------------------------------------------------
    @property
    def cors_origin_list(self) -> List[str]:
        raw = (self.cors_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def airport_list(self) -> List[str]:
        return [a.strip().upper() for a in (self.preferred_airports or "").split(",") if a.strip()]

    @property
    def screenshot_dir(self) -> str:
        return os.path.join(self.data_dir, "screenshots")

    @property
    def snapshot_dir(self) -> str:
        return os.path.join(self.data_dir, "snapshots")

    @property
    def profile_state_dir(self) -> str:
        return os.path.join(self.data_dir, "browser-profiles")

    def proxy_map(self) -> Dict[str, str]:
        """Label -> proxy URL.  Never expose the values through the API."""
        pairs = [
            (self.proxy_de_1_label, self.proxy_de_1),
            (self.proxy_de_2_label, self.proxy_de_2),
            (self.proxy_de_3_label, self.proxy_de_3),
        ]
        return {label: url for label, url in pairs if url}

    def proxy_labels(self) -> List[str]:
        return sorted(self.proxy_map().keys())

    def secret_values(self) -> List[str]:
        """Every value that must be scrubbed from logs and API output."""
        candidates = [
            self.api_key,
            self.smtp_password,
            self.smtp_user,
            self.telegram_bot_token,
            self.discord_webhook_url,
            self.homeassistant_webhook_url,
            self.proxy_de_1,
            self.proxy_de_2,
            self.proxy_de_3,
        ]
        out: List[str] = []
        for value in candidates:
            if value and len(str(value)) >= 6:
                out.append(str(value))
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
