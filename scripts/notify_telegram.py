#!/usr/bin/env python3
"""
OPS-01: send a Telegram message via the Bot API. Used by
scripts/run_scheduled_health_check.py to alert on a broken crawler, but callable
standalone for a quick test:

    python scripts/notify_telegram.py "test message"

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env (see OPERATIONS.md for how
to create a bot via @BotFather and find your chat id). If either is unset, send()
returns False instead of raising -- a missing notification config must never
crash the health check it's attached to. OPS-34 (#202): it logs an ERROR and
queues the message in the outbox, so the first send after the config is
restored delivers the gap; alerts are this deployment's only failure signal,
and "not configured" must not look like "all quiet".

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


def _queue_unconfigured(message: str, queue_on_failure: bool) -> bool:
    """OPS-34 (#202): the token or chat id is missing. Nothing can be sent,
    but the alert is kept (bounded by OUTBOX_MAX) for the first send after the
    config is back, and the gap is an ERROR. The command-line test
    (queue_on_failure=False) is told now and queues nothing."""
    missing = " and ".join(name for name, value in (("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
                                                   ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)) if not value)
    if not queue_on_failure:
        logger.error(f"{missing} not set -- notification not sent")
        return False
    try:
        with FileLock(OUTBOX_PATH + ".lock", timeout=OUTBOX_LOCK_TIMEOUT_S):
            pending = _read_outbox()
            pending.append({"queued_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "text": message})
            _write_outbox(pending)
    except Exception as e:  # noqa: BLE001 -- must never raise into the caller
        logger.error(f"{missing} not set and the Telegram outbox {OUTBOX_PATH} is unusable "
                     f"({type(e).__name__}: {redact(e)}); alert LOST: {redact(message[:300])}")
        return False
    logger.error(f"{missing} not set -- alert NOT sent, queued for the first send after it is set "
                 f"({min(len(pending), OUTBOX_MAX)} waiting): {redact(message[:300])}")
    return False


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
        return _queue_unconfigured(message, queue_on_failure)
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


# Telegram refuses a bot upload above 50 MB; a digest PDF is a few hundred KB.
DOCUMENT_MAX_BYTES = 50 * 1024 * 1024
DOCUMENT_TIMEOUT_S = 60


def _post_document(path: str, caption: str):
    """One upload attempt. (ok, retryable, reason); never raises."""
    try:
        with open(path, "rb") as f:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1000]},
                files={"document": (os.path.basename(path), f)},
                timeout=DOCUMENT_TIMEOUT_S,
            )
    except Exception as e:  # noqa: BLE001
        return False, True, f"{type(e).__name__}: {redact(e)}"
    if response.status_code == 200:
        return True, False, ""
    retryable = response.status_code == 429 or response.status_code >= 500
    return False, retryable, f"Telegram API returned {response.status_code}: {redact(response.text[:500])}"


def send_document(path: str, caption: str = "") -> bool:
    """OPS-40 (#235): sends the file at `path` to TELEGRAM_CHAT_ID. True on success,
    False on any failure (missing config or file, too large, network, non-200) --
    never raises. A failure that may pass is retried after RETRY_DELAYS. Unlike
    `send`, a file is not queued in the outbox: the caller keeps the file and can
    send it again, and a delayed copy of yesterday's PDF would only confuse."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set -- document %s not sent", path)
        return False
    try:
        size = os.path.getsize(path)
    except OSError as e:
        logger.error(f"document {path} cannot be read ({type(e).__name__}): not sent")
        return False
    if size > DOCUMENT_MAX_BYTES:
        logger.error(f"document {path} is {size} bytes, over Telegram's {DOCUMENT_MAX_BYTES}-byte limit: not sent")
        return False
    ok, retryable, reason = _post_document(path, caption)
    for delay in RETRY_DELAYS:
        if ok or not retryable:
            break
        time.sleep(delay)
        ok, retryable, reason = _post_document(path, caption)
    if not ok:
        logger.error(f"Failed to send Telegram document: {reason}")
    return ok


# Telegram refuses a message longer than this (characters, after entity parsing).
MESSAGE_MAX_CHARS = 4096


def _post_html(text: str):
    """One sendMessage attempt in HTML parse mode. (ok, retryable, reason); never raises."""
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception as e:  # noqa: BLE001
        return False, True, f"{type(e).__name__}: {redact(e)}"
    if response.status_code == 200:
        return True, False, ""
    retryable = response.status_code == 429 or response.status_code >= 500
    return False, retryable, f"Telegram API returned {response.status_code}: {redact(response.text[:500])}"


def send_html(text: str) -> bool:
    """OPS-43 (#243): a reader's message (the newsletter's 60-second block),
    `text` already in Telegram HTML with its content escaped. True on success,
    False on any failure -- never raises. Retried like a document and, like a
    document, never queued in the outbox: yesterday's briefing delivered late,
    before some other alert, would only confuse."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set -- message not sent")
        return False
    if len(text) > MESSAGE_MAX_CHARS:
        logger.error(f"message is {len(text)} characters, over Telegram's {MESSAGE_MAX_CHARS}: not sent")
        return False
    ok, retryable, reason = _post_html(text)
    for delay in RETRY_DELAYS:
        if ok or not retryable:
            break
        time.sleep(delay)
        ok, retryable, reason = _post_html(text)
    if not ok:
        logger.error(f"Failed to send Telegram message: {reason}")
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
