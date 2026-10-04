#!/usr/bin/env python3
r"""
SYS-39 (#125) / OPS-20 (#136): the scheduled knowledge-extraction entry point.

`task=extract_knowledge` had no schedule, which is how 84,606 articles ended with
`knowledge_extracted = 0` and a knowledge base of 54 entities. This runs it once a
night, off-peak, and reports in Telegram what it did: articles extracted, tokens, the
dollars they cost at the provider's price, what is still pending, and why it stopped.

    python scripts/run_scheduled_extraction.py                       # run it
    python scripts/run_scheduled_extraction.py --wait-for-crawl 90   # let a running crawl finish first
    python scripts/run_scheduled_extraction.py --dry-run             # print the plan, call nothing

Why 21:00: the 19:00 crawl normally ends by 20:00 (its limit is 4 h), and the provider's
peak window (UTC weekdays 01:00-04:00 and 06:00-10:00 = 08:00-11:00 and 13:00-17:00 WIB)
does not open until 08:00 WIB. A run is bounded by KNOWLEDGE_MAX_PER_RUN, the day's
KNOWLEDGE_DAILY_COST_LIMIT_USD and the peak guard, and Task Scheduler's 8 h limit ends it
before the 07:00 crawl. Every article is its own transaction, so a killed run loses nothing.

The run lock (OPS-26) is honoured because the crawl and this job both load the whole
pipeline (~4 GB) and a crawl in progress is the wrong moment to start another; with
--wait-for-crawl N it polls for up to N minutes, otherwise it exits 2 at once.

Exit codes: 0 ran (stopped at the budget, the peak window or an empty queue is normal),
1 failed (an exception, every call failed, the provider's quota or an outage stopped it),
2 refused by the run lock.

Windows Task Scheduler (registered 2026-10-04 as "NewsAggregator Knowledge Extraction"):
    New-ScheduledTaskAction -Execute <repo>\venv\Scripts\python.exe `
        -Argument '"<repo>\scripts\run_scheduled_extraction.py" --wait-for-crawl 90' -WorkingDirectory <repo>
    daily 21:00, battery/wake/StartWhenAvailable as the crawl jobs, ExecutionTimeLimit 8 h, IgnoreNew
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from dotenv import load_dotenv

load_dotenv(os.path.join(REPO_ROOT, ".env"))

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("run_scheduled_extraction")
logger.setLevel(logging.INFO)

LOG_DIR = os.getenv("SCHEDULE_LOG_DIR", os.path.join(REPO_ROOT, "logs"))
LOG_KEEP = int(os.getenv("SCHEDULE_EXTRACTION_LOG_KEEP", "28"))
LOCK_POLL_S = 60

# A stop that means the provider (not the budget or the clock) ended the run.
FAILURE_STOPS = ("failed calls in a row", "quota exhausted")


def pending_count(session) -> int:
    """Articles the extractor will still select (the SYS-19 attempt cap applies)."""
    from sqlalchemy import text
    from newscrawler.core.constants import KNOWLEDGE_EXTRACT_MAX_ATTEMPTS
    return session.execute(text(
        "SELECT COUNT(*) FROM articles WHERE knowledge_extracted = 0 AND knowledge_extract_attempts < :n"),
        {"n": KNOWLEDGE_EXTRACT_MAX_ATTEMPTS}).scalar()


def summary_line(result, pending_before, pending_after) -> str:
    """The Telegram line. Numbers first; STOPPED/FAILED only when the provider ended the run."""
    parts = ["%d/%d extracted" % (result.processed, result.attempted)]
    if result.input_tokens or result.output_tokens:
        parts.append("%d in / %d out tokens, $%.2f" % (result.input_tokens, result.output_tokens, result.cost_usd))
    if pending_after is not None:
        parts.append("%d pending" % pending_after if pending_before is None
                     else "pending %d -> %d" % (pending_before, pending_after))
    if result.stopped:
        parts.append(("STOPPED: " if is_failure(result) else "stopped: ") + result.stopped)
    if result.all_calls_failed:
        parts.insert(0, "FAILED")
    return " · ".join(parts)


def is_failure(result) -> bool:
    """Every call failed, or the provider's quota or an outage ended the run."""
    return bool(result.all_calls_failed or (result.stopped and any(s in result.stopped for s in FAILURE_STOPS)))


def open_run_log(log_dir, now=None, keep=None):
    """A file handler for this run; the newest `keep` run logs stay. A log that cannot be
    opened must not stop the run."""
    import glob
    path = os.path.join(log_dir, "scheduled_extraction_%s.log" % (now or datetime.now()).strftime("%Y-%m-%d_%H%M"))
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as e:
        logger.warning("run log %s could not be opened (%s); logging to stderr only", path, e)
        return None, None
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    keep = LOG_KEEP if keep is None else keep
    for old in (sorted(glob.glob(os.path.join(log_dir, "scheduled_extraction_*.log")))[:-keep] if keep > 0 else []):
        if os.path.abspath(old) != os.path.abspath(path):
            try:
                os.remove(old)
            except OSError:
                pass
    return path, handler


def wait_for_lock(refused, minutes, sleep=time.sleep, poll_s=LOCK_POLL_S) -> bool:
    """True when the run lock is free, polling for up to `minutes` minutes. `refused` is
    refused_by_run_lock bound to the logger (True = a crawl holds the lock)."""
    waited = 0.0
    while refused():
        if waited >= minutes * 60:
            return False
        sleep(poll_s)
        waited += poll_s
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wait-for-crawl", type=int, default=0, metavar="MINUTES",
                    help="Poll the run lock for up to this long instead of exiting 2 at once")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan and exit; call nothing")
    args = ap.parse_args(argv)

    if args.dry_run:
        return _dry_run()

    # OPS-26: a scheduled crawl holds the pipeline; do nothing, say so, exit 2.
    from newscrawler.tools.run_lock import refused_by_run_lock
    if not wait_for_lock(lambda: refused_by_run_lock(logger), args.wait_for_crawl, sleep=lambda s: time.sleep(s)):
        return 2

    log_path, handler = open_run_log(LOG_DIR)
    try:
        return _run(log_path)
    except Exception as e:  # noqa: BLE001 -- a run that could not happen must say so
        logger.exception("scheduled extraction failed")
        _notify("FAILED: %s: %s%s" % (type(e).__name__, str(e)[:300], " · log %s" % log_path if log_path else ""))
        return 1
    finally:
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            handler.close()


def _dry_run() -> int:
    from newscrawler.core.constants import (
        KNOWLEDGE_DAILY_COST_LIMIT_USD, KNOWLEDGE_LLM_PROVIDER, KNOWLEDGE_MAX_PER_RUN, KNOWLEDGE_WORKERS)
    from newscrawler.core.peak_hours import is_peak, next_off_peak
    now = datetime.now(timezone.utc)
    logger.info("[dry-run] provider=%s workers=%d max_per_run=%d daily_cost_limit=$%.2f",
                KNOWLEDGE_LLM_PROVIDER or "gemini", KNOWLEDGE_WORKERS, KNOWLEDGE_MAX_PER_RUN, KNOWLEDGE_DAILY_COST_LIMIT_USD)
    logger.info("[dry-run] peak window now: %s%s", is_peak(now),
                "" if not is_peak(now) else " (off-peak from %s UTC)" % next_off_peak(now).strftime("%Y-%m-%d %H:%M"))
    return 0


def _run(log_path) -> int:
    from newscrawler.application.api.lambda_function.lambda_handler import init_crawler
    from newscrawler.core.knowledge_extractor import ExtractionResult
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    client = SQLAlchemyClient()
    with client.get_session() as session:
        before = pending_count(session)
    logger.info("scheduled extraction: %d article(s) pending", before)
    # The service brackets the run in crawl_log (OPS-11) and re-raises a failure.
    result = init_crawler().crawler_service.extract_knowledge()
    if not isinstance(result, ExtractionResult):          # an older repository returns a bare count
        result = ExtractionResult(int(result))
    with client.get_session() as session:
        after = pending_count(session)
    line = summary_line(result, before, after)
    logger.info("SUMMARY: %s", line)
    _notify(line + (" · log %s" % log_path if log_path else ""))
    return 1 if is_failure(result) else 0


def _notify(message: str) -> None:
    """Telegram, via the OPS-01 notifier. A notification failure must not change the exit
    code: the run either happened or it did not."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from notify_telegram import redact, send
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram notifier unavailable (%s); summary logged only", e)
        return
    try:
        send("Extraction %s" % message)
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram notification failed: %s: %s", type(e).__name__, redact(e))


if __name__ == "__main__":
    sys.exit(main())
