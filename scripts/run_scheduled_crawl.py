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

One model load in the normal case. `init_crawler()` builds the sentence-transformers
models and both FAISS indexes (~2 min, ~4 GB RSS). It runs once, in a child
process (`newscrawler/tools/source_worker.py`), and the sources run one after
another inside it. This process only dispatches, counts and reports.

Per-source timeout (OPS-22, #161): a source that exceeds SCHEDULE_SOURCE_TIMEOUT
has its child process **killed**, and the kill finishes before the next source
starts. That source's `crawl_log` row is closed as `failed`, and the next source
gets a fresh child (one more model load). This used to be a worker thread, which
Python cannot kill. Its timeout never freed the caller (the executor's context
exit waited for it), and freeing it would have left the abandoned source writing
the same service state and FAISS stores as the next one. `check_crawlers.py` can
make the thread trade only because it writes nothing. Why a kill is safe for the
stores is in source_worker's docstring.

Run budget: no source is started once the elapsed time plus one per-source
timeout would pass SCHEDULE_RUN_BUDGET (default 3 h 30 min). The remaining
sources are reported as skipped, so the summary always goes out before Task
Scheduler's 4 h `ExecutionTimeLimit` kills the process. A killed process sends
nothing.

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
import time
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
# Hours since the last crawl before the run says so. OPS-01 was reopened twice
# because "a missed window produces no alert, no exit code, no crawl_log row --
# indistinguishable from a healthy run"; this is the crawl's version of its 36 h
# gap check. It only helps when a later run DOES fire, which is its limit.
GAP_ALERT_HOURS = int(os.getenv("SCHEDULE_GAP_ALERT_HOURS", "36"))
# OPS-22: seconds the whole run may take. It must stay below the Task Scheduler
# ExecutionTimeLimit (4 h) by at least one SOURCE_TIMEOUT plus the reporting time.
RUN_BUDGET = int(os.getenv("SCHEDULE_RUN_BUDGET", str(3 * 3600 + 1800)))
# How long the child may take to build the crawler before the start counts as failed.
INIT_TIMEOUT = int(os.getenv("SCHEDULE_INIT_TIMEOUT", "1200"))


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


def hours_since_last_crawl(session):
    """Hours since the newest `sitemap`/`full_text` crawl_log row, or None when
    there has never been one. Pure enough to test with a stub session."""
    from sqlalchemy import text
    newest = session.execute(text(
        "SELECT MAX(started_at) FROM crawl_log WHERE task IN ('sitemap', 'full_text')"
    )).scalar()
    if newest is None:
        return None
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - newest).total_seconds() / 3600.0


def run_one(worker, website, task, timeout=SOURCE_TIMEOUT):
    """(status, detail). Never raises -- one source must not end the run. On
    timeout the worker has already killed the source's process when this returns."""
    try:
        return worker.run(website, task, timeout)
    except Exception as e:  # noqa: BLE001 -- the next source must still run
        return "failed", "%s: %s" % (type(e).__name__, str(e)[:200])


def db_now(session):
    """The database's clock. crawl_log.started_at is stamped by the DB's NOW(), so
    a window compared against it has to come from the same clock."""
    from sqlalchemy import text
    return session.execute(text("SELECT NOW()::timestamp")).scalar()


def _close_abandoned_log_rows(session, website, task, since, reason):
    """A killed source never writes its crawl_log completion, so its row would
    stay 'started' forever and read as "still running". Close every row the
    killed source opened (started at or after `since`) as failed, with the reason.
    Returns how many were closed."""
    from sqlalchemy import text
    result = session.execute(text(
        "UPDATE crawl_log SET status = 'failed', finished_at = NOW(), error_msg = :msg "
        "WHERE website = :website AND task = :task AND status = 'started' AND started_at >= :since"
    ), {"msg": ("killed by run_scheduled_crawl: " + reason)[:1000], "website": website,
        "task": task, "since": since})
    session.commit()
    return result.rowcount


def over_budget(elapsed, timeout, budget=None):
    """Whether starting one more source could run past the budget."""
    return elapsed + timeout > (RUN_BUDGET if budget is None else budget)


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
    try:
        return _run(args)
    except Exception as e:  # noqa: BLE001 -- see below
        # The most likely catastrophic failure is init_crawler(): a missing probe
        # artifact, a corrupt FAISS index, or OOM loading e5-large. That happens
        # BEFORE any source runs, so without this the operator gets no Telegram
        # message at all -- only a non-zero exit buried in Task Scheduler history,
        # which is the exact hole OPS-01 was reopened twice for. A crawl that
        # could not start has to say so.
        logger.exception("scheduled crawl failed before it could report")
        if not args.dry_run:
            _notify("FAILED to start or complete: %s: %s" % (type(e).__name__, str(e)[:300]))
        return 1


def _run(args) -> int:
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
        gap_hours = hours_since_last_crawl(session)
    if gap_hours is None:
        logger.warning("no previous sitemap/full_text crawl_log row -- this is the first recorded crawl")
    elif gap_hours > GAP_ALERT_HOURS:
        msg = ("last recorded crawl was %.1f h ago (expected ~every 12 h) -- the schedule may not be firing"
               % gap_hours)
        logger.warning(msg)
        _notify("Scheduled crawl gap: " + msg)

    logger.info("building the crawler in its worker process (models + FAISS; this is the slow part)...")
    worker = _make_worker()
    worker.start()  # a crawler that cannot start at all is main()'s "FAILED to start"
    run_started = time.monotonic()

    phase_results = {}
    try:
        for phase, phase_sources in (("sitemap", sm_sources), ("full_text", ft_sources)):
            if not phase_sources:
                continue
            results = {}
            for i, website in enumerate(phase_sources, 1):
                if over_budget(time.monotonic() - run_started, args.timeout):
                    skipped["%s/%s" % (website, phase)] = "run budget %ds reached -- not started" % RUN_BUDGET
                    continue
                with client.get_session() as session:
                    since = db_now(session)
                started = time.monotonic()
                status, detail = run_one(worker, website, phase, timeout=args.timeout)
                if status != "ok" and not worker.alive:
                    # The source's process is gone (killed on timeout, or died), so
                    # its crawl_log row will never be completed by the pipeline.
                    with client.get_session() as session:
                        closed = _close_abandoned_log_rows(session, website, phase, since, detail)
                    logger.warning("%s/%s: closed %d abandoned crawl_log row(s)", website, phase, closed)
                results[website] = (status, detail)
                logger.info("[%s %d/%d] %s -> %s%s (%.0fs)", phase, i, len(phase_sources), website, status,
                            " (%s)" % detail if detail else "", time.monotonic() - started)
            phase_results[phase] = results
    finally:
        worker.close()
    if worker.spawned > 1:
        logger.warning("the crawler was rebuilt %d time(s) after a killed or dead source", worker.spawned - 1)

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


def _make_worker():
    """Seam for the tests: the production worker builds the real crawler in its child."""
    from newscrawler.tools.source_worker import SourceWorker
    return SourceWorker(init_timeout=INIT_TIMEOUT)


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
