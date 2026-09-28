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

OPS-33 (#194): the Bot API carries the token in the URL path (/bot<token>/...),
and requests/urllib3 exception messages include that path. Everything this
module logs goes through redact() first.

OPS-32 (#193): a message that cannot be sent now is retried, then queued in
logs/telegram_outbox.jsonl and delivered, marked as delayed, before the next
message anyone sends.
"""
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

import requests
from filelock import FileLock

from newscrawler.core.constants import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# OPS-32: seconds between the attempts of one send; the outbox covers longer outages.
RETRY_DELAYS = (5, 20)
OUTBOX_PATH = os.getenv("TELEGRAM_OUTBOX",
                        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "logs", "telegram_outbox.jsonl"))
# The newest alerts are kept; after a week offline the oldest matter least.
OUTBOX_MAX = 20
OUTBOX_LOCK_TIMEOUT_S = 120

# A bot token is <bot id>:<secret>; the API path is /bot<token>/<method>.
_TOKEN_IN_TEXT = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
REDACTED = "bot<redacted>"


def redact(text) -> str:
    """`text` with the bot token removed: the configured one wherever it
    appears, and anything shaped like /bot<id>:<secret>."""
    text = str(text)
    if TELEGRAM_BOT_TOKEN:
        text = text.replace("bot" + TELEGRAM_BOT_TOKEN, REDACTED).replace(TELEGRAM_BOT_TOKEN, "<redacted>")
    return _TOKEN_IN_TEXT.sub(REDACTED, text)


def _post(text: str):
    """One attempt. (ok, retryable, reason); never raises. A network error, a
    429 or a 5xx may pass on retry; any other refusal (400 bad request, 401
    bad token) will not."""
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception as e:  # noqa: BLE001
        return False, True, f"{type(e).__name__}: {redact(e)}"
    if response.status_code == 200:
        return True, False, ""
    retryable = response.status_code == 429 or response.status_code >= 500
    return False, retryable, f"Telegram API returned {response.status_code}: {redact(response.text[:500])}"


def _deliver(text: str):
    """_post, retried after each of RETRY_DELAYS while the failure is retryable."""
    ok, retryable, reason = _post(text)
    for delay in RETRY_DELAYS:
        if ok or not retryable:
            break
        time.sleep(delay)
        ok, retryable, reason = _post(text)
    return ok, retryable, reason


def _read_outbox():
    try:
        with open(OUTBOX_PATH, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        logger.error(f"Telegram outbox {OUTBOX_PATH} unreadable ({type(e).__name__}); starting a new one")
        return []


def _write_outbox(items) -> None:
    if not items:
        if os.path.exists(OUTBOX_PATH):
            os.remove(OUTBOX_PATH)
        return
    os.makedirs(os.path.dirname(OUTBOX_PATH) or ".", exist_ok=True)
    tmp = OUTBOX_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for item in items[-OUTBOX_MAX:]:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    os.replace(tmp, OUTBOX_PATH)


def _flush_outbox() -> list:
    """Deliver queued alerts, oldest first, until one still cannot be sent.
    One that can never be sent (a 4xx) is dropped, with its text in the log.
    Returns what is still queued."""
    pending = _read_outbox()
    while pending:
        item = pending[0]
        ok, retryable, reason = _deliver("[delayed; queued %s] %s" % (item.get("queued_at", "?"), item["text"]))
        if not ok and retryable:
            break
        if ok:
            logger.info(f"delivered a Telegram alert queued at {item.get('queued_at')}")
        else:
            logger.error(f"dropping a queued Telegram alert that cannot be sent ({reason}): {item['text'][:300]}")
        pending.pop(0)
    return pending


def send(message: str, queue_on_failure: bool = True) -> bool:
    """Sends message to TELEGRAM_CHAT_ID. Returns True on success, False on any
    failure (missing config, network error, non-200 response) -- never raises.

    OPS-32 (#193): on 2026-09-27 the 07:00 run's summary, the only message that
    said 27 sources had failed, hit the same DNS outage and was only logged. A
    failure that may pass (network, 429, 5xx) is retried after RETRY_DELAYS, and
    if it still fails the message is queued in OUTBOX_PATH. Every send first
    delivers what is queued, oldest first, so the next run's send (or the
    health check's) brings the missed alert in."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set -- skipping notification")
        return False
    try:
        with FileLock(OUTBOX_PATH + ".lock", timeout=OUTBOX_LOCK_TIMEOUT_S):
            pending = _flush_outbox()
            if pending:
                ok, retryable, reason = False, True, "%d earlier alert(s) still queued" % len(pending)
            else:
                ok, retryable, reason = _deliver(message)
            if not ok and retryable and queue_on_failure:
                pending.append({"queued_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "text": message})
            _write_outbox(pending)
    except Exception as e:  # noqa: BLE001 -- the outbox must never cost the alert itself
        logger.error(f"Telegram outbox {OUTBOX_PATH} unusable ({type(e).__name__}: {redact(e)}); sending directly")
        ok, retryable, reason = _deliver(message)
        pending = None
    if not ok:
        note = ""
        if pending and queue_on_failure and retryable:
            note = " -- queued for the next send (%d waiting)" % len(pending)
        logger.error(f"Failed to send Telegram notification: {reason}{note}")
    return ok


def main(argv=None) -> int:
    """The command-line test (OPERATIONS.md, step 5). The operator is checking
    the setup now, so a failure is reported now and never queued: delivered
    hours later as [delayed], it would only mislead."""
    argv = sys.argv[1:] if argv is None else argv
    text = argv[0] if argv else "Test notification from notify_telegram.py"
    ok = send(text, queue_on_failure=False)
    print("Sent." if ok else "Failed to send -- check TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID and the log above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
