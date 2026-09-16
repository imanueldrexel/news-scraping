#!/usr/bin/env python3
"""
OPS-01: send a Telegram message via the Bot API. Used by
scripts/run_scheduled_health_check.py to alert on a broken crawler, but callable
standalone for a quick test:

    python scripts/notify_telegram.py "test message"

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env (see OPERATIONS.md for how
to create a bot via @BotFather and find your chat id). If either is unset, send()
logs a warning and returns False instead of raising -- a missing notification
config must never crash the health check it's attached to.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

import requests

from newscrawler.core.constants import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def send(message: str) -> bool:
    """Sends message to TELEGRAM_CHAT_ID. Returns True on success, False on any
    failure (missing config, network error, non-200 response) -- never raises."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set -- skipping notification")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
        if response.status_code != 200:
            logger.error(f"Telegram API returned {response.status_code}: {response.text[:500]}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "Test notification from notify_telegram.py"
    ok = send(text)
    print("Sent." if ok else "Failed to send -- check TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID and the log above.")
    sys.exit(0 if ok else 1)
