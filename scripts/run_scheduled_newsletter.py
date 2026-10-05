#!/usr/bin/env python3
r"""
OPS-38 (#212): the scheduled newsletter entry point.

`task=newsletter` had no scheduled job, so `digests/` held two hand-run files.
This runs it once a day for the previous full day, then reports in Telegram
what the digest is: its path, articles, clusters and how many summaries are
real (SYS-68), or that it FAILED, was DEGRADED or EMPTY.

    python scripts/run_scheduled_newsletter.py                  # yesterday
    python scripts/run_scheduled_newsletter.py --date 2026-10-03
    python scripts/run_scheduled_newsletter.py --dry-run        # print the plan only

Why "yesterday": the digest of a day is built from that day's `sitemaps.posted_at`.
A run over today's date would be a partial day, which is how a stray 2026-10-04
row appeared (SDE note 2026-10-04).

When to run it: after the morning crawl has finished, not before. The 19:00 crawl
ends well before midnight, so everything published after about 19:00 is only
fetched by the 07:00 crawl (up to 4 h, Task Scheduler's limit); a digest built at
06:30 would miss those hours for good. 12:00 clears the longest allowed morning
run. The run lock (OPS-26) is checked first: a crawl in progress holds the FAISS
indexes in memory, the run exits 2 without opening the database, and Task
Scheduler's "Last Run Result" shows it.

Exit codes: 0 digest written (a degraded one still exits 0 and says so in the
message), 1 failed or empty, 2 refused by the run lock.

Windows Task Scheduler registration (see OPERATIONS.md; the two battery settings
matter for the same reason as in OPS-01 and OPS-19):

    schtasks /Create /TN "NewsAggregator Newsletter" /SC DAILY /ST 12:00 ^
        /TR "<repo>\venv\Scripts\python.exe <repo>\scripts\run_scheduled_newsletter.py" /RU "<user>"
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
            -MultipleInstances IgnoreNew
    Set-ScheduledTask -TaskName "NewsAggregator Newsletter" -Settings $s
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from dotenv import load_dotenv

load_dotenv(os.path.join(REPO_ROOT, ".env"))

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("run_scheduled_newsletter")
logger.setLevel(logging.INFO)

LOG_DIR = os.getenv("SCHEDULE_LOG_DIR", os.path.join(REPO_ROOT, "logs"))
LOG_KEEP = int(os.getenv("SCHEDULE_NEWSLETTER_LOG_KEEP", "28"))


def default_date(today=None) -> date:
    """The previous full day."""
    return (today or date.today()) - timedelta(days=1)


def digest_row(session, target_date):
    """The newsletter_digests row for the date (None when there is none)."""
    from sqlalchemy import text
    return session.execute(text(
        "SELECT file_path, article_count, cluster_count, categories FROM newsletter_digests "
        "WHERE digest_date = :d"), {"d": target_date}).fetchone()


def summary_line(target_date, path, row, note=None) -> str:
    """The Telegram line. `row` is the newsletter_digests row; None is reported, not hidden."""
    if row is None:
        return "%s: digest file %s written but no newsletter_digests row found" % (target_date, path)
    if not row.article_count:
        return "EMPTY %s: no articles for the day -- did the crawls run? (%s)" % (target_date, path)
    categories = row.categories if isinstance(row.categories, dict) else {}
    counts = categories.get("_summaries") or {}
    parts = ["%s: %d articles, %d clusters" % (target_date, row.article_count, row.cluster_count)]
    if counts:
        parts.append("%s/%s summaries" % (counts.get("summarized", "?"), counts.get("total", "?")))
    if note:
        parts.insert(0, "DEGRADED")
        parts.append(note)
    parts.append(str(path))
    return " · ".join(parts)


def open_run_log(log_dir, now=None, keep=None):
    """A file handler for this run; the newest `keep` run logs stay. A log that
    cannot be opened must not stop the run."""
    import glob
    path = os.path.join(log_dir, "scheduled_newsletter_%s.log" % (now or datetime.now()).strftime("%Y-%m-%d_%H%M"))
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as e:
        logger.warning("run log %s could not be opened (%s); logging to stderr only", path, e)
        return None, None
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    keep = LOG_KEEP if keep is None else keep
    for old in (sorted(glob.glob(os.path.join(log_dir, "scheduled_newsletter_*.log")))[:-keep] if keep > 0 else []):
        if os.path.abspath(old) != os.path.abspath(path):
            try:
                os.remove(old)
            except OSError:
                pass
    return path, handler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD, the articles' publication day (default: yesterday)")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan and exit; build nothing")
    args = ap.parse_args(argv)
    try:
        target_date = date.fromisoformat(args.date) if args.date else default_date()
    except ValueError:
        logger.error("--date must be YYYY-MM-DD, not %r", args.date)
        return 1
    if target_date >= date.today():
        logger.error("refusing %s: the digest is for a finished day (today is %s)", target_date, date.today())
        return 1
    if args.dry_run:
        logger.info("[dry-run] would digest %s", target_date)
        return 0

    # OPS-26: a scheduled crawl holds FAISS in memory; do nothing, say so, exit 2.
    from newscrawler.tools.run_lock import refused_by_run_lock
    if refused_by_run_lock(logger):
        return 2

    log_path, handler = open_run_log(LOG_DIR)
    try:
        return _run(target_date, log_path)
    except Exception as e:  # noqa: BLE001 -- a digest that could not be built must say so
        logger.exception("scheduled newsletter failed")
        _notify("FAILED %s: %s: %s%s" % (target_date, type(e).__name__, str(e)[:300],
                                         " · log %s" % log_path if log_path else ""))
        return 1
    finally:
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            handler.close()


def _run(target_date, log_path) -> int:
    from newscrawler.application.api.lambda_function.lambda_handler import init_crawler
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    logger.info("scheduled newsletter for %s", target_date)
    # The service brackets the run in crawl_log (OPS-11) and re-raises a failure.
    path = init_crawler().crawler_service.generate_newsletter(target_date)
    with SQLAlchemyClient().get_session() as session:
        row = digest_row(session, target_date)
    line = summary_line(target_date, path, row, getattr(path, "note", None))
    logger.info("SUMMARY: %s", line)
    _notify(line + (" · log %s" % log_path if log_path else ""))
    if row is not None and row.article_count:
        _send_pdf(target_date, str(path))
    return 1 if row is not None and not row.article_count else 0


def _send_pdf(target_date, markdown_path) -> bool:
    """OPS-40 (#235): the digest as a PDF in Telegram. The digest was built, so a
    PDF that cannot be rendered or sent is a WARNING and a Telegram line, never a
    different exit code."""
    try:
        from newscrawler.core.newsletter_pdf import render_digest_pdf
        pdf_path = render_digest_pdf(markdown_path)
    except Exception as e:  # noqa: BLE001
        logger.exception("newsletter PDF could not be rendered")
        _notify("PDF %s not made: %s: %s" % (target_date, type(e).__name__, str(e)[:200]))
        return False
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from notify_telegram import send_document
        ok = send_document(pdf_path, "Rangkuman Berita %s" % target_date)
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram document failed: %s: %s", type(e).__name__, e)
        ok = False
    if ok:
        logger.info("PDF sent: %s", pdf_path)
    else:
        logger.warning("PDF %s built but not delivered", pdf_path)
        _notify("PDF %s built but not delivered to Telegram: %s" % (target_date, pdf_path))
    return ok


def _notify(message: str) -> None:
    """Telegram, via the OPS-01 notifier. A notification failure must not change
    the exit code: the digest either was built or it was not."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from notify_telegram import redact, send
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram notifier unavailable (%s); summary logged only", e)
        return
    try:
        send("Newsletter %s" % message)
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram notification failed: %s: %s", type(e).__name__, redact(e))


if __name__ == "__main__":
    sys.exit(main())
