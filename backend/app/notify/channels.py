"""Notification channels.

Every channel is optional and self-contained: if it is not configured it simply
reports ``configured = False`` and is skipped.  Credentials come from the
environment and are never logged.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Optional

import httpx

from app.config import settings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)

TIMEOUT = 15.0


class Channel:
    key = "base"
    label = "Base"

    @property
    def configured(self) -> bool:
        return False

    def send(self, subject: str, message: str, target: Optional[str] = None) -> bool:
        raise NotImplementedError


class EmailChannel(Channel):
    key = "email"
    label = "E-Mail (SMTP)"

    @property
    def configured(self) -> bool:
        return bool(settings.smtp_host and settings.smtp_from)

    def send(self, subject: str, message: str, target: Optional[str] = None) -> bool:
        host = settings.smtp_host
        if not self.configured or not target or not host:
            return False
        mail = EmailMessage()
        mail["Subject"] = subject
        mail["From"] = settings.smtp_from
        mail["To"] = target
        mail.set_content(message)
        try:
            with smtplib.SMTP(host, settings.smtp_port, timeout=TIMEOUT) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls()
                if settings.smtp_user and settings.smtp_password:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(mail)
            logger.info("Preisalarm per E-Mail versendet an %s", target.split("@")[-1])
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("E-Mail-Versand fehlgeschlagen: %s", type(exc).__name__)
            return False


class TelegramChannel(Channel):
    key = "telegram"
    label = "Telegram"

    @property
    def configured(self) -> bool:
        return bool(settings.telegram_bot_token)

    def send(self, subject: str, message: str, target: Optional[str] = None) -> bool:
        if not self.configured:
            return False
        chat_id = target or settings.telegram_chat_id
        if not chat_id:
            return False
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            response = httpx.post(
                url,
                json={"chat_id": chat_id, "text": f"{subject}\n\n{message}", "disable_web_page_preview": True},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            logger.info("Preisalarm per Telegram versendet.")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram-Versand fehlgeschlagen: %s", type(exc).__name__)
            return False


class WebhookChannel(Channel):
    """Shared implementation for Discord / Home Assistant webhooks."""

    payload_key = "content"

    def _url(self, target: Optional[str]) -> Optional[str]:
        return target or None

    def send(self, subject: str, message: str, target: Optional[str] = None) -> bool:
        url = self._url(target)
        if not url:
            return False
        try:
            response = httpx.post(url, json={self.payload_key: f"**{subject}**\n{message}"}, timeout=TIMEOUT)
            response.raise_for_status()
            logger.info("Preisalarm per %s versendet.", self.label)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s-Versand fehlgeschlagen: %s", self.label, type(exc).__name__)
            return False


class DiscordChannel(WebhookChannel):
    key = "discord"
    label = "Discord Webhook"
    payload_key = "content"

    @property
    def configured(self) -> bool:
        return bool(settings.discord_webhook_url)

    def _url(self, target: Optional[str]) -> Optional[str]:
        return target or settings.discord_webhook_url


class HomeAssistantChannel(WebhookChannel):
    key = "homeassistant"
    label = "Home Assistant Webhook"
    payload_key = "message"

    @property
    def configured(self) -> bool:
        return bool(settings.homeassistant_webhook_url)

    def _url(self, target: Optional[str]) -> Optional[str]:
        return target or settings.homeassistant_webhook_url

    def send(self, subject: str, message: str, target: Optional[str] = None) -> bool:
        url = self._url(target)
        if not url:
            return False
        try:
            response = httpx.post(url, json={"title": subject, "message": message}, timeout=TIMEOUT)
            response.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Home-Assistant-Versand fehlgeschlagen: %s", type(exc).__name__)
            return False


CHANNELS = {
    channel.key: channel
    for channel in (EmailChannel(), TelegramChannel(), DiscordChannel(), HomeAssistantChannel())
}


def channel_status() -> list:
    return [
        {"key": channel.key, "label": channel.label, "configured": channel.configured}
        for channel in CHANNELS.values()
    ]
