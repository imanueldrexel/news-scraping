"""
Telegram Notifier - Shared notification service for all microservices.

Sends messages to Telegram using the Bot API.
Gracefully handles failures without crashing the calling service.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Async Telegram notifier using the Bot API.
    
    Usage:
        notifier = TelegramNotifier(bot_token="...", chat_id="...")
        await notifier.send_message("Hello from ingestion!")
    """

    TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: float = 10.0,
    ):
        """
        Initialize the Telegram notifier.

        Args:
            bot_token: Telegram Bot API token. If empty, notifications are disabled.
            chat_id: Chat/group ID to send messages to.
            timeout: HTTP request timeout in seconds.
        """
        self.bot_token = bot_token or ""
        self.chat_id = chat_id or ""
        self.timeout = timeout
        self._enabled = bool(self.bot_token and self.chat_id)

        if self._enabled:
            logger.info("TelegramNotifier initialized and enabled")
        else:
            logger.info("TelegramNotifier disabled (missing token or chat_id)")

    @property
    def enabled(self) -> bool:
        """Check if notifications are enabled."""
        return self._enabled

    async def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """
        Send a message to the configured Telegram chat.

        Args:
            text: Message text (supports HTML formatting).
            parse_mode: Parse mode for formatting (HTML or Markdown).
            disable_notification: If True, send silently.

        Returns:
            True if message was sent successfully, False otherwise.
        """
        if not self._enabled:
            logger.debug("Telegram notification skipped (disabled)")
            return False

        url = self.TELEGRAM_API_URL.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                logger.debug("Telegram message sent successfully")
                return True

        except httpx.TimeoutException:
            logger.warning("Telegram notification timed out")
            return False
        except httpx.HTTPStatusError as e:
            logger.warning(f"Telegram API error: {e.response.status_code}")
            return False
        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")
            return False

    async def send_cycle_summary(
        self,
        service_name: str,
        stats: dict,
        duration_seconds: float,
        extra_info: Optional[str] = None,
    ) -> bool:
        """
        Send a formatted cycle summary message.

        Args:
            service_name: Name of the service (e.g., "Ingestion").
            stats: Statistics dictionary from the cycle.
            duration_seconds: How long the cycle took.
            extra_info: Optional additional information to include.

        Returns:
            True if message was sent successfully, False otherwise.
        """
        # Build message with emoji indicators
        lines = [
            f"<b>📊 {service_name} Cycle Complete</b>",
            f"⏱ Duration: {duration_seconds:.1f}s",
            "",
        ]

        # Add stats
        for key, value in stats.items():
            # Convert snake_case to Title Case
            label = key.replace("_", " ").title()
            lines.append(f"• {label}: <b>{value}</b>")

        if extra_info:
            lines.append("")
            lines.append(extra_info)

        message = "\n".join(lines)
        return await self.send_message(message)
