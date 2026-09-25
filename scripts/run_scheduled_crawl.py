#!/usr/bin/env python3
r"""
OPS-19 (#132): the scheduled crawl entry point.

Until now only the health check was scheduled (OPS-01). The crawl itself was a set
of manual runs, which is why six HEALTHY sources had never produced a single
`sitemaps` row and nine had not been crawled since 2026-06-02 -- and why
`MAX_WORKER`, the 1,000-row queue, the cooldown, OPS-15/OPS-16's source-wide guard
and SYS-09's fetch-failure cap were all designed for a recurring run that never
started. SRC-34 (#124), SYS-39 (#125) and SYS-41 (#127) each say "measure after a
week of real volume"; there is no real volume without this.

What it does, in this order (OPS-19 proposal 2):

  Phase 1  task=sitemap for every scheduled source
  Phase 2  task=full_text for SCHEDULE_FULL_TEXT_WEBSITES

Listing first, for every source, so a slow source's fetch phase cannot delay
another source's listing -- the listing is cheap and is what keeps the queue fed.

One process, one model load. `init_crawler()` builds the sentence-transformers
models and both FAISS indexes (~2 min, ~4 GB RSS), so the sources are looped
inside a single crawler rather than one subprocess each.

Per-source timeout: each source runs in a worker thread and the wrapper stops
waiting after SCHEDULE_SOURCE_TIMEOUT. Python cannot kill a thread, so a timed-out
source keeps running in the background -- the same trade `check_crawlers.py`
makes. It is recorded as a timeout and the wrapper moves on, which is the point:
one hung outlet must not eat the window.

Windows Task Scheduler registration (see OPERATIONS.md; mirrors OPS-01's, and the
two battery settings matter for the same reason they do there -- this machine is a
laptop, and Task Scheduler's defaults silently skip a battery run without marking
it "missed", so -StartWhenAvailable never queues a catch-up):

    schtasks /Create /TN "NewsAggregator Scheduled Crawl (morning)" /SC DAILY /ST 07:00 ^
        /TR "<repo>\venv\Scripts\python.exe <repo>\scripts\run_scheduled_crawl.py" /RU "<user>"
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 4)
    Set-ScheduledTask -TaskName "NewsAggregator Scheduled Crawl (morning)" -Settings $s

07:00 and 19:00 WIB, chosen to stay clear of the 05:30 health check.

Exit code: 0 when every scheduled source completed, 1 when any failed or timed
out -- so Task Scheduler's own "Last Run Result" reflects it independently of the
Telegram notification.

    python scripts/run_scheduled_crawl.py                 # both phases
    python scripts/run_scheduled_crawl.py --dry-run       # print the plan, crawl nothing
    python scripts/run_scheduled_crawl.py --phase sitemap
    python scripts/run_scheduled_crawl.py --website KOMPAS,CNBC
"""
import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_scheduled_crawl")

# The sources the schedule drives, and the ones it must not.
#
# VIVA is excluded by a standing hard rule, not by preference: SRC-33 (#119) is
# open, its `_get_branches` still keeps all 53 branches (29 of them keyed by URL),
# and one sitemap crawl would add ~53k rows onto a 39k backlog that is 97.8%
# non-finance. Remove it from here when SRC-33 lands, not before.
DEFAULT_EXCLUDED = {"VIVA": "SRC-33 (#119) open -- 53 branches, ~53k rows per run onto a 39k backlog"}

SOURCE_TIMEOUT = int(os.getenv("SCHEDULE_SOURCE_TIMEOUT", "900"))
# OPS-19 proposal 5: a source that lists rows but saves nothing for this many
# consecutive full_text runs is the new "needs attention".
ZERO_SAVE_RUNS_BEFORE_ALERT = int(os.getenv("SCHEDULE_ZERO_SAVE_RUNS", "3"))
# ... and only counting runs from the last this-many days. Without the window the
# check fires on history: WARTAEKONOMI's last three full_text runs were 2026-06-01,
# all zero, while it actually holds 2,695 articles -- an alert that says "needs
# attention now" must not be answerable from four-month-old rows.
ZERO_SAVE_WITHIN_DAYS = int(os.getenv("SCHEDULE_ZERO_SAVE_WITHIN_DAYS", "7"))


def scheduled_sources(website_override=None, excluded=None):
    """(sources to crawl, {source: why it was skipped}) -- pure, for the tests."""
    from __main__ import HEALTHY  # noqa: F401  -- not importable under the scheduler
    return _scheduled_sources(HEALTHY, website_override, excluded)


def _scheduled_sources(healthy, website_override=None, excluded=None):
    excluded = DEFAULT_EXCLUDED if excluded is None else excluded
    if website_override:
        wanted = [w.strip().upper() for w in website_override.split(",") if w.strip()]
    else:
        wanted = list(healthy)
    skipped = {w: excluded[w] for w in wanted if w in excluded}
    return [w for w in wanted if w not in excluded], skipped


def full_text_sources(sources):
    """OPS-19 proposal 3: `SCHEDULE_FULL_TEXT_WEBSITES` limits which sources get
    their articles fetched. It existed as the gate for "no full_text until SYS-37"
    -- SYS-37 landed 2026-09-22, so unset now means *all* scheduled sources, and
    the variable remains the way to stage a source in listing-only for a while."""
    override = os.getenv("SCHEDULE_FULL_TEXT_WEBSITES")
    if not override:
        return list(sources)
    wanted = {w.strip().upper() for w in override.split(",") if w.strip()}
    return [s for s in sources if s in wanted]


def _counts(session):
    from sqlalchemy import text
    rows = session.execute(text(
        "SELECT s.sources, COUNT(*) AS sitemaps, COUNT(a.sitemap_id) AS articles "
        "FROM sitemaps s LEFT JOIN articles a USING (sitemap_id) GROUP BY 1"
    )).fetchall()
    return {r.sources: {"sitemaps": r.sitemaps, "articles": r.articles} for r in rows}


def zero_save_sources(session, runs=ZERO_SAVE_RUNS_BEFORE_ALERT, within_days=ZERO_SAVE_WITHIN_DAYS):
    """Sources whose last `runs` full_text crawl_log rows *within `within_days`*
    all saved 0 articles.

    `crawl_log` is the only place this is answerable, which is why OPS-11 (#67)
    and OPS-16 (#87) had to make it truthful first: before them a source-wide
    fetch failure and "fetched everything, filtered it all out" were the same row.

    The time window is not decoration. Without it the first live run of this
    wrapper flagged EMITENNEWS and WARTAEKONOMI on `full_text` rows from
    2026-06-02 -- and WARTAEKONOMI holds 2,695 articles. A daily alert has to
    describe the last few days, not the last few rows.
    """
    from sqlalchemy import text
    rows = session.execute(text(
        """
        SELECT website, article_count FROM (
          SELECT website, article_count,
                 ROW_NUMBER() OVER (PARTITION BY website ORDER BY started_at DESC) AS rn,
                 COUNT(*) OVER (PARTITION BY website) AS total
          FROM crawl_log
          WHERE task = 'full_text' AND status = 'completed'
            AND started_at >= NOW() - make_interval(days => :within_days)
        ) t WHERE rn <= :runs AND total >= :runs
        """), {"runs": runs, "within_days": within_days}).fetchall()
    by_site = {}
    for r in rows:
        by_site.setdefault(r.website, []).append(r.article_count or 0)
    return sorted(w for w, counts in by_site.items() if len(counts) >= runs and not any(counts))


def run_one(api, website, task, timeout=SOURCE_TIMEOUT):
    """(status, detail). Never raises -- one source must not end the run."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(api.crawl_website, website, task)
        try:
            future.result(timeout=timeout)
            return "ok", ""
        except FutureTimeout:
            # The thread cannot be killed and keeps running; recorded and moved
            # past, so one hung outlet does not eat the window.
            return "timeout", "exceeded %ds" % timeout
        except Exception as e:  # noqa: BLE001 -- the next source must still run
            return "failed", "%s: %s" % (type(e).__name__, str(e)[:200])


def summary_line(phase_results, deltas, zero_savers, skipped):
    """OPS-19 proposal 5: the Telegram line. Numbers first, names only when there
    is something to act on."""
    sources = sorted({s for results in phase_results.values() for s in results})
    failed = sorted(s for results in phase_results.values() for s, (st, _) in results.items() if st != "ok")
    added_sitemaps = sum(d["sitemaps"] for d in deltas.values())
    added_articles = sum(d["articles"] for d in deltas.values())
    zero = sorted(s for s in sources if deltas.get(s, {}).get("articles", 0) == 0)
    parts = ["%d sources, +%d sitemaps, +%d articles, %d with 0 saved"
             % (len(sources), added_sitemaps, added_articles, len(zero))]
    if failed:
        parts.append("FAILED: " + ", ".join(failed))
    if zero_savers:
        parts.append("0 saved for %d runs: %s" % (ZERO_SAVE_RUNS_BEFORE_ALERT, ", ".join(zero_savers)))
    if skipped:
        parts.append("skipped: " + ", ".join("%s (%s)" % (k, v.split(" -- ")[0]) for k, v in skipped.items()))
    return " · ".join(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--website", default=None, help="Comma-separated override of the scheduled list")
    ap.add_argument("--phase", choices=("sitemap", "full_text", "both"), default="both")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan and exit; crawl nothing")
    ap.add_argument("--timeout", type=int, default=SOURCE_TIMEOUT, help="Per-source timeout in seconds")
    args = ap.parse_args(argv)

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    healthy = _healthy_list()
    sources, skipped = _scheduled_sources(healthy, args.website)
    ft_sources = full_text_sources(sources) if args.phase in ("full_text", "both") else []
    sm_sources = sources if args.phase in ("sitemap", "both") else []

    logger.info("scheduled crawl: %d source(s); sitemap=%d full_text=%d; per-source timeout %ds",
                len(sources), len(sm_sources), len(ft_sources), args.timeout)
    for name, why in skipped.items():
        logger.warning("SKIPPED %s: %s", name, why)
    if args.dry_run:
        logger.info("[dry-run] sitemap: %s", ", ".join(sm_sources) or "-")
        logger.info("[dry-run] full_text: %s", ", ".join(ft_sources) or "-")
        return 0
    if not sources:
        logger.error("no sources to crawl")
        return 1

    client = SQLAlchemyClient()
    with client.get_session() as session:
        before = _counts(session)

    from newscrawler.application.api.lambda_function.lambda_handler import init_crawler
    logger.info("building the crawler (models + FAISS; this is the slow part)...")
    api = init_crawler()

    phase_results = {}
    for phase, phase_sources in (("sitemap", sm_sources), ("full_text", ft_sources)):
        if not phase_sources:
            continue
        results = {}
        for i, website in enumerate(phase_sources, 1):
            started = datetime.now(timezone.utc)
            status, detail = run_one(api, website, phase, timeout=args.timeout)
            results[website] = (status, detail)
            logger.info("[%s %d/%d] %s -> %s%s (%.0fs)", phase, i, len(phase_sources), website, status,
                        " (%s)" % detail if detail else "",
                        (datetime.now(timezone.utc) - started).total_seconds())
        phase_results[phase] = results

    with client.get_session() as session:
        after = _counts(session)
        zero_savers = zero_save_sources(session)

    deltas = {
        s: {"sitemaps": after.get(s, {}).get("sitemaps", 0) - before.get(s, {}).get("sitemaps", 0),
            "articles": after.get(s, {}).get("articles", 0) - before.get(s, {}).get("articles", 0)}
        for s in sources
    }
    for s in sources:
        logger.info("  %-15s +%-6d sitemaps  +%-5d articles", s, deltas[s]["sitemaps"], deltas[s]["articles"])

    line = summary_line(phase_results, deltas, zero_savers, skipped)
    logger.info("SUMMARY: %s", line)
    _notify(line)

    failed = [s for results in phase_results.values() for s, (st, _) in results.items() if st != "ok"]
    return 1 if failed else 0


def _healthy_list():
    """`HEALTHY` lives in __main__.py, which is not importable under its own name
    when the scheduler runs this file as __main__. Read it the same way either."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "__main__.py")
    spec = importlib.util.spec_from_file_location("newsaggregator_main", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.HEALTHY)


def _notify(message: str) -> None:
    """Telegram, via the OPS-01 notifier. A notification failure must not change
    the run's exit code -- the crawl either worked or it did not."""
    try:
        # Same import shape OPS-01's wrapper uses (scripts/ is on sys.path there).
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from notify_telegram import send
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram notifier unavailable (%s); summary logged only", e)
        return
    try:
        send("Scheduled crawl %s: %s" % (datetime.now().strftime("%Y-%m-%d %H:%M"), message))
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram notification failed: %s", e)


if __name__ == "__main__":
    sys.exit(main())
