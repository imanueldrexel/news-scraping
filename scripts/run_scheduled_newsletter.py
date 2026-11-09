#!/usr/bin/env python3
r"""
OPS-38 (#212): the scheduled newsletter entry point.

`task=newsletter` had no scheduled job, so `digests/` held two hand-run files.
This runs it once a day for the previous full day, then reports in Telegram
what the digest is: its path, articles, clusters and how many summaries are
real (SYS-68), or that it FAILED, was DEGRADED or EMPTY. Then the reader's
delivery (OPS-43): a message with the 5-minute edition's 60-second block and
the edition as a phone PDF; the full digest stays in digests/ as the archive.

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
MESSAGE_MAX_CHARS = 4096   # Telegram's limit for one message


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
    arcs = (categories.get("_edition") or {}).get("arcs")       # SYS-149: only when NEWSLETTER_ARCS is on
    if arcs:
        line = "arcs %s/%s" % (arcs.get("built", "?"), arcs.get("built", 0) + arcs.get("fallback", 0))
        parts.append(line + (" (%s)" % arcs["stopped"] if arcs.get("stopped") else ""))
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
    from newscrawler.application.newsletter_app import build_newsletter_service
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    logger.info("scheduled newsletter for %s", target_date)
    # DBT-74 (#346): the newsletter's own composition root (Postgres, MiniLM, NEWS_L1 read-only,
    # the summarizer) -- not init_crawler(), which loaded NEWS_L2 and e5-large for nothing.
    # The service brackets the run in crawl_log (OPS-11) and re-raises a failure.
    path = build_newsletter_service().generate_newsletter(target_date)
    with SQLAlchemyClient().get_session() as session:
        row = digest_row(session, target_date)
    line = summary_line(target_date, path, row, getattr(path, "note", None))
    logger.info("SUMMARY: %s", line)
    _notify(line + (" · log %s" % log_path if log_path else ""))
    if row is not None and row.article_count:
        _deliver(target_date, str(path), getattr(path, "edition", None), row)
    return 1 if row is not None and not row.article_count else 0


def _deliver(target_date, digest_path, edition_path, row) -> None:
    """OPS-43 (#243): what the reader gets. Normally a message with the edition's
    60-second block, then the edition's phone PDF; the full digest stays in
    digests/ (the archive) and is not sent. Without an edition: a message that
    says so (and why some stories have no summary, when that is the reason) and
    the full digest's PDF, as before OPS-43. Each step's failure is reported
    and never stops the next one or changes the exit code.

    OPS-44 (#248): a message that promised a PDF ("Buka PDF ...", "terlampir
    edisi lengkapnya") is followed by "PDF tidak tersedia hari ini." when that
    PDF is then not delivered -- its upload failed, or the digest's could not
    be rendered after the message went out."""
    from html import escape

    from newscrawler.core import newsletter_copy as copy
    if edition_path:
        pdf_path = _render_pdf(target_date, edition_path, edition=True)
        try:
            from newscrawler.core.newsletter_edition import briefing
            with open(edition_path, encoding="utf-8") as f:
                sentences, top = briefing(f.read())
        except Exception as e:  # noqa: BLE001
            logger.warning("edition %s unreadable for the message: %s: %s", edition_path, type(e).__name__, e)
            sentences, top = [], 0
        promised = pdf_path is not None              # else the message itself says there is no PDF
        _send_message(edition_message(target_date, sentences, top, pdf_ok=promised))
    else:
        _send_message(no_edition_message(target_date, row))
        promised = True
        pdf_path = _render_pdf(target_date, digest_path, edition=False)
    delivered = pdf_path is not None and _send_pdf_file(target_date, pdf_path)
    if promised and not delivered:
        _send_message(escape(copy.MESSAGE_NO_PDF))


def edition_message(target_date, sentences, top_count, pdf_ok=True) -> str:
    """The reader's Telegram message (HTML, content escaped): header, the 60-second
    sentences as bullets, and where the rest is. Kept under Telegram's 4,096
    characters by dropping sentences from the end (5 sentences of <= 18 words
    never come near it)."""
    from html import escape

    from newscrawler.core import newsletter_copy as copy
    header = copy.MESSAGE_HEADER.format(title="<b>%s</b>" % escape(copy.TITLE),
                                        tanggal=escape(copy.tanggal_pendek(target_date)))
    last = copy.MESSAGE_OPEN_PDF.format(n=top_count) if pdf_ok else copy.MESSAGE_NO_PDF
    sentences = list(sentences)
    while True:
        text = "\n".join([header, ""] + ["• %s" % escape(s, quote=False) for s in sentences] + ["", escape(last)])
        if len(text) <= MESSAGE_MAX_CHARS or not sentences:
            return text
        sentences.pop()


def no_edition_message(target_date, row) -> str:
    """The message when the 5-minute edition was not built: it says so, plus
    SYS-84's notice when some stories have no summary; the full digest's PDF follows."""
    from html import escape

    from newscrawler.core import newsletter_copy as copy
    header = copy.CAPTION.format(title="<b>%s</b>" % escape(copy.TITLE),
                                 tanggal=escape(copy.tanggal_pendek(target_date)))
    lines = [header, "", escape(copy.MESSAGE_NO_EDITION)]
    categories = row.categories if isinstance(getattr(row, "categories", None), dict) else {}
    counts = categories.get("_summaries") or {}
    missing = (counts.get("total") or 0) - (counts.get("summarized") or 0)
    if missing > 0:
        lines.append(escape(copy.degraded(missing)))
    return "\n".join(lines)


def _render_pdf(target_date, markdown_path, edition):
    """The PDF's path -- the phone layout for the edition (OPS-42), A4 for the
    full digest (OPS-40) -- or None after reporting why it could not be made."""
    try:
        from newscrawler.core import newsletter_pdf
        render = newsletter_pdf.render_edition_pdf if edition else newsletter_pdf.render_digest_pdf
        return render(markdown_path)
    except Exception as e:  # noqa: BLE001
        logger.exception("newsletter PDF could not be rendered")
        _notify("PDF %s not made: %s: %s" % (target_date, type(e).__name__, str(e)[:200]))
        return None


def _send_message(text) -> bool:
    """The reader's message; a failure is reported to the operator, never raised."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from notify_telegram import send_html
        ok = send_html(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram message failed: %s: %s", type(e).__name__, e)
        ok = False
    if ok:
        logger.info("Reader message sent")
    else:
        logger.warning("Reader message not delivered")
        _notify("reader message not delivered to Telegram")
    return ok


def _send_pdf_file(target_date, pdf_path) -> bool:
    """OPS-40 (#235): the PDF in Telegram, captioned with the date in Indonesian
    (SYS-81). The newsletter was built, so a PDF that cannot be sent is a
    WARNING and a Telegram line, never a different exit code."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from notify_telegram import send_document

        from newscrawler.core.newsletter_copy import caption
        ok = send_document(pdf_path, caption(target_date))
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
