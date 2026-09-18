#!/usr/bin/env python3
"""
Crawler health checker -- sample-crawls every outlet in CRAWLER_DICT and reports which
crawlers are broken (sitemap listing parse OR article-body extraction).

Per outlet it runs the REAL production code paths on a tiny sample:
  Stage A (listing): get_soup(website_url) -> _get_branches -> _scrape(first branch)
  Stage B (article): batch_crawling_sitemap -> batch_crawling_details, check extracted_text

Status:
  OK       listing returned links AND >=1 sample article's text came from the site's
           own selector (meta_data["extractor"] == "site")
  FALLBACK listing OK, samples produced text, but EVERY sample was rescued by
           trafilatura/newspaper -- the site selector is dead; needs attention but
           not fatal (OPS-02)
  PARTIAL  listing OK but 0 sample articles produced text (body extraction broken)
  BROKEN   sitemap fetch/parse/listing failed
  ERROR    unexpected exception (message captured)

Usage:
    python scripts/check_crawlers.py
    python scripts/check_crawlers.py --website KOMPAS,DETIK --sample-size 2
    python scripts/check_crawlers.py --json
    python scripts/check_crawlers.py --quiet --log-db
    python scripts/check_crawlers.py --website KOMPAS --diff-db --report-dir /tmp/x

--diff-db (OPS-13) compares each outlet with its most recent prior task='health_check'
crawl_log row -- per outlet, not per batch, so a manual --website X run doesn't
disturb the other 31 baselines -- and leads the summary with what changed
(NEW / CHANGED / RECOVERED) instead of the same wall of known-broken names every
day. --log-db implies it: the baseline is read before this run's rows are written.

Exit code: 0 = all healthy, 1 = one or more outlets BROKEN/PARTIAL/ERROR.
(FALLBACK and the --diff-db delta never affect the exit code.)

Daily cron (Linux):
    0 6 * * * cd /path/to/news-scraping && venv/bin/python scripts/check_crawlers.py >> crawler_health/cron.log 2>&1
Windows Task Scheduler: daily trigger; action = <repo>\\venv\\Scripts\\python.exe scripts\\check_crawlers.py ; start-in = repo root.
"""
import argparse
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
# Silence the chatty per-branch crawler logs during checking.
logging.getLogger("newscrawler.infrastructure.datasource.scrapers.crawler").setLevel(logging.ERROR)
logger = logging.getLogger("check_crawlers")

from newscrawler.core.crawler_dict_list import CRAWLER_DICT

STATUS_OK = "OK"
STATUS_FALLBACK = "FALLBACK"
STATUS_PARTIAL = "PARTIAL"
STATUS_BROKEN = "BROKEN"
STATUS_ERROR = "ERROR"
# Severity order: drives the table sort and the "(10 BROKEN, 1 ERROR, 6 FALLBACK)" breakdowns.
STATUSES = (STATUS_BROKEN, STATUS_ERROR, STATUS_PARTIAL, STATUS_FALLBACK, STATUS_OK)
# UNHEALTHY drives the exit code -- FALLBACK is deliberately excluded (OPS-02:
# "needs attention but non-fatal", since articles are still being produced).
UNHEALTHY = {STATUS_PARTIAL, STATUS_BROKEN, STATUS_ERROR}
NEEDS_ATTENTION = UNHEALTHY | {STATUS_FALLBACK}

# OPS-13: how an outlet moved relative to its previous crawl_log row.
CHANGE_NEW = "new"                # was OK, now needs attention -- the line the operator must read
CHANGE_CHANGED = "changed"        # needed attention before and now, but the status moved (BROKEN -> FALLBACK)
CHANGE_RECOVERED = "recovered"    # needed attention before, OK now
CHANGE_UNCHANGED = "unchanged"
CHANGE_BASELINE = "baseline"      # no prior health_check row for this outlet (first run / new crawler)
CHANGE_KINDS = (CHANGE_NEW, CHANGE_CHANGED, CHANGE_RECOVERED, CHANGE_UNCHANGED, CHANGE_BASELINE)


def _utcnow() -> datetime:
    """Timezone-aware UTC. crawl_log's started_at/finished_at are `timestamp without
    time zone` columns that the pipeline fills with NOW(); Postgres converts an
    *aware* bind value through the same session-TZ conversion NOW() gets, so the
    health_check rows stay comparable with the pipeline's rows and with the 36 h
    gap check in run_scheduled_health_check.py. A naive datetime.now() would land
    as WIB wall clock in a UTC column, seven hours off (OPS-12)."""
    return datetime.now(timezone.utc)


def _extracted_len(detail) -> int:
    txt = getattr(detail, "extracted_text", None)
    if not txt:
        return 0
    if isinstance(txt, list):
        return sum(len(str(p)) for p in txt)
    return len(str(txt))


# OPS-03: sample the branch the pipeline actually cares about, not just whichever one
# a site's sitemap index happens to list first ("Bobo" for GRIDID, "AksaraJabar" for
# PIKIRANRAKYAT, "suara-pembaca" for DETIK, "www" for TEMPO) -- those are often a
# different HTML template than the finance/economy section, so a health check that
# only ever samples them isn't actually checking what matters to this pipeline.
FINANCE_BRANCH_PATTERN = re.compile(r"ekonomi|bisnis|market|finance|keuangan|money|uang", re.IGNORECASE)


def pick_branch(branches: dict):
    """Pure: the first branch (dict insertion order) whose name matches
    FINANCE_BRANCH_PATTERN, or the first branch overall if none matches."""
    for name, link in branches.items():
        if FINANCE_BRANCH_PATTERN.search(name):
            return name, link
    return next(iter(branches.items()))


def classify(sitemap_links: int, detail_ok: int, extractors: list = None, error: bool = False) -> str:
    """Pure classification from sample-crawl counts. `extractors` is the
    meta_data["extractor"] value (see crawler.py's _get_news_details) for each
    sample that produced text -- OPS-02: if none of them is "site", the site's own
    selector is dead and trafilatura/newspaper are quietly doing all the work."""
    if error:
        return STATUS_ERROR
    if sitemap_links <= 0:
        return STATUS_BROKEN
    if detail_ok <= 0:
        return STATUS_PARTIAL
    if extractors and "site" not in extractors:
        return STATUS_FALLBACK
    return STATUS_OK


def _blank_result(name: str, started_at: datetime = None) -> dict:
    return {
        "website": name, "branch": "", "sitemap_links": 0, "dto_count": 0,
        "detail_total": 0, "detail_ok": 0, "avg_chars": 0,
        "status": STATUS_BROKEN, "note": "", "extractors": [],
        # OPS-12: the outlet's own check window, not the logging transaction's NOW().
        "started_at": started_at or _utcnow(), "finished_at": None, "duration_sec": 0.0,
    }


def _stamp_finished(result: dict) -> dict:
    result["finished_at"] = _utcnow()
    result["duration_sec"] = round((result["finished_at"] - result["started_at"]).total_seconds(), 1)
    return result


def check_one(name: str, crawler, sample_size: int) -> dict:
    """Sample-crawl one outlet using the real code paths. Never raises."""
    result = _blank_result(name)
    try:
        soup = crawler.page_loader.get_soup(crawler.website_url)
        if not soup:
            result["note"] = "sitemap fetch failed (get_soup returned None)"
            return result
        branches = crawler._get_branches(soup) or {}
        if not branches:
            result["note"] = "no branches parsed from sitemap"
            return result

        branch_name, branch_link = pick_branch(branches)
        result["branch"] = branch_name
        articles = crawler._scrape(branch_link=branch_link, branch_name=branch_name) or []
        result["sitemap_links"] = len(articles)
        if not articles:
            result["note"] = "first branch scraped 0 article links"
            return result

        dtos = crawler.batch_crawling_sitemap(articles[:sample_size], name) or []
        result["dto_count"] = len(dtos)
        if not dtos:
            result["status"] = STATUS_PARTIAL
            result["note"] = "links found but SitemapDTO validation produced none"
            return result

        # Sample DTOs from a fresh scrape have sitemap_id=None; _get_news_details builds a
        # NewsDetailsDTO(sitemap_id=...) which requires an int. Stamp a placeholder id so the
        # check exercises real article extraction instead of failing validation first.
        # Use object.__setattr__ to bypass the frozen dataclass + pydantic re-validation
        # (dataclasses.replace would re-validate and choke on optional fields like timestamp).
        sample = list(dtos[:sample_size])
        for d in sample:
            try:
                object.__setattr__(d, "sitemap_id", 0)
            except Exception:
                pass
        details = crawler.batch_crawling_details(sample, name) or []
        result["detail_total"] = len(sample)
        lengths = [_extracted_len(d) for d in details]
        ok = [l for l in lengths if l > 0]
        result["detail_ok"] = len(ok)
        result["avg_chars"] = int(sum(ok) / len(ok)) if ok else 0
        # OPS-02: which extractor produced the text, for the samples that succeeded.
        extractors = [(getattr(d, "meta_data", None) or {}).get("extractor") for d, l in zip(details, lengths) if l > 0]
        result["extractors"] = extractors
        result["status"] = classify(result["sitemap_links"], result["detail_ok"], extractors)
        if result["status"] == STATUS_PARTIAL:
            result["note"] = "listing OK but article body extraction returned empty"
        elif result["status"] == STATUS_FALLBACK:
            used = sorted({e for e in extractors if e} or {"unknown"})
            result["note"] = "site selector produced nothing; rescued by " + "/".join(used)
        return result
    except Exception as e:
        result["status"] = STATUS_ERROR
        result["note"] = ("%s: %s" % (type(e).__name__, e))[:200]
        return result
    finally:
        # Every exit above returns the same dict, so stamping it here covers them all.
        _stamp_finished(result)


def run_checks(targets: dict, sample_size: int, workers: int, timeout: int) -> list:
    run_started = _utcnow()
    # OPS-12: a worker that times out never hands back its result dict, so its real
    # start is recorded out-of-band the moment it begins (not when it was queued
    # behind the other `workers` slots). Dict assignment is atomic under the GIL.
    started = {}

    def _timed_check(name, crawler):
        started[name] = _utcnow()
        return check_one(name, crawler, sample_size)

    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_map = {
            ex.submit(_timed_check, name, crawler): name
            for name, crawler in targets.items()
        }
        for fut, name in future_map.items():
            try:
                results.append(fut.result(timeout=timeout))
            except FutureTimeout:
                r = _blank_result(name, started_at=started.get(name, run_started))
                r["status"] = STATUS_ERROR
                r["note"] = "timeout after %ds" % timeout
                results.append(_stamp_finished(r))
    order = {s: i for i, s in enumerate(STATUSES)}
    results.sort(key=lambda r: (order.get(r["status"], 9), r["website"]))
    return results


def render_table(results: list) -> str:
    rows = ["%-14s %-8s %-14s %-6s %-5s %-15s %-6s %s" % (
        "SOURCE", "STATUS", "BRANCH", "LINKS", "DTOs", "DETAIL(ok/tot)", "SECS", "NOTE"),
        "-" * 120]
    for r in results:
        detail = "%d/%d (%dch)" % (r["detail_ok"], r["detail_total"], r["avg_chars"])
        rows.append("%-14s %-8s %-14s %-6d %-5d %-15s %-6s %s" % (
            r["website"][:14], r["status"], r.get("branch", "")[:14], r["sitemap_links"],
            r["dto_count"], detail, "%.1f" % r["duration_sec"], r["note"][:60]))
    return "\n".join(rows)


def _status_breakdown(entries: list) -> str:
    """'10 BROKEN, 1 ERROR, 6 FALLBACK' in severity order, zeros omitted."""
    counts = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    return ", ".join("%d %s" % (counts[s], s) for s in STATUSES if counts.get(s))


def _totals(results: list) -> str:
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    parts = ["%s=%d" % (s, counts.get(s, 0)) for s in
             (STATUS_OK, STATUS_FALLBACK, STATUS_PARTIAL, STATUS_BROKEN, STATUS_ERROR)]
    return ", ".join(parts) + " (of %d)" % len(results)


def summary_line(results: list, delta: dict = None) -> str:
    """The text that becomes the Telegram message.

    Without a delta (no DB, or the baseline read failed) it is the one-line
    totals plus every needs-attention name -- the pre-OPS-13 format. With a delta
    it leads with what *moved* since each outlet's previous crawl_log row, so a
    new breakage is the first thing on the screen and a no-change day says so in
    its first line instead of re-listing the same 17 known-broken outlets."""
    totals = _totals(results)
    if delta is None:
        # OPS-02: FALLBACK is "needs attention" (a dead site selector, silently rescued)
        # but not fatal -- it's listed here, but does not affect the exit code below.
        needs_attention = [r["website"] for r in results if r["status"] in NEEDS_ATTENTION]
        line = "Crawler health: " + totals
        if needs_attention:
            line += " | needs attention: " + ", ".join(needs_attention)
        return line

    def _moved(entries):
        return ", ".join("%s (%s, was %s)" % (e["website"], e["status"], e["previous"]) for e in entries)

    parts = []
    if delta[CHANGE_NEW]:
        parts.append("\U0001F534 NEW: " + _moved(delta[CHANGE_NEW]))
    if delta[CHANGE_CHANGED]:
        parts.append("\U0001F7E1 CHANGED: " + _moved(delta[CHANGE_CHANGED]))
    if delta[CHANGE_RECOVERED]:
        parts.append("\U0001F7E2 RECOVERED: " + _moved(delta[CHANGE_RECOVERED]))
    if delta[CHANGE_BASELINE]:
        parts.append("⚪ NO BASELINE: " + ", ".join(
            "%s (%s)" % (e["website"], e["status"]) for e in delta[CHANGE_BASELINE]))

    unchanged = delta[CHANGE_UNCHANGED]
    known = [e for e in unchanged if e["status"] in NEEDS_ATTENTION]
    if known:
        known_txt = "%d known (%s)" % (len(known), _status_breakdown(known))
    elif unchanged:
        known_txt = "all %d OK" % len(unchanged)
    else:
        known_txt = ""

    head = "Crawler health %s: " % datetime.now().strftime("%Y-%m-%d")
    if parts:
        if known_txt:
            parts.append("unchanged: " + known_txt)
        head += " · ".join(parts)
    else:
        compared_to = delta.get("compared_to")
        since = compared_to.astimezone().strftime("%Y-%m-%d %H:%M") if compared_to else "the previous run"
        head += "no change since %s — %s" % (since, known_txt or "nothing to compare")
    return head + "\nTotals: " + totals


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError("Object of type %s is not JSON serializable" % type(obj).__name__)


def build_payload(results: list, delta: dict = None) -> dict:
    """One payload for the dated JSON report *and* --json stdout, so the scheduled
    wrapper reads exactly what the report file says (summary + delta included)."""
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(results),
        "unhealthy": [r["website"] for r in results if r["status"] in UNHEALTHY],
        "needs_attention": [r["website"] for r in results if r["status"] in NEEDS_ATTENTION],
        "summary": summary_line(results, delta),
        "delta": delta,
        "results": results,
    }


def write_report(payload: dict, report_dir: str) -> str:
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, datetime.now().strftime("%Y-%m-%d") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_json_default)
    return path


# ── crawl_log (OPS-12 / OPS-13) ─────────────────────────────────────────────

def _db_session():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    return SQLAlchemyClient().get_session()


def _logged_status(error_msg) -> str:
    """log_to_db writes error_msg as '<STATUS>' or '<STATUS>: <note>'; recover the
    STATUS, or None for a row that isn't in that shape (hand-written, truncated)."""
    if not error_msg:
        return None
    head = error_msg.split(":", 1)[0].strip()
    return head if head in STATUSES else None


def load_previous_statuses(session) -> dict:
    """{website: {"status": <STATUS>, "finished_at": <aware datetime>}} from each
    outlet's most recent prior task='health_check' row.

    Per outlet (DISTINCT ON website), not "the last batch": a manual
    `--website KOMPAS --log-db` in between must only move KOMPAS's baseline, not
    make the other 31 outlets look like first-run baselines the next morning.
    finished_at is reinterpreted in the session's own TimeZone (what NOW() was
    stored through) so callers get an unambiguous instant, not a naive column."""
    from sqlalchemy import text
    rows = session.execute(text(
        "SELECT DISTINCT ON (website) website, error_msg, "
        "       finished_at AT TIME ZONE current_setting('TimeZone') AS finished_tz "
        "FROM crawl_log WHERE task = 'health_check' "
        "ORDER BY website, finished_at DESC NULLS LAST, log_id DESC"
    ))
    previous = {}
    for website, error_msg, finished_tz in rows:
        status = _logged_status(error_msg)
        if status:
            previous[website] = {"status": status, "finished_at": finished_tz}
    return previous


def classify_change(status: str, previous_status) -> str:
    """Pure: how an outlet moved. 'Healthy' is OK only -- OK -> FALLBACK is a site
    selector that died overnight (OPS-02), which is exactly the kind of NEW the
    operator must see even though it doesn't change the exit code."""
    if previous_status is None:
        return CHANGE_BASELINE
    if status == previous_status:
        return CHANGE_UNCHANGED
    if status == STATUS_OK:
        return CHANGE_RECOVERED
    if previous_status == STATUS_OK:
        return CHANGE_NEW
    return CHANGE_CHANGED


def compute_delta(results: list, previous: dict) -> dict:
    """Bucket this run's results by classify_change against `previous`
    (load_previous_statuses' shape). Pure -- results are not modified.

    Returns {new|changed|recovered|unchanged|baseline: [{website, status, previous}],
             compared_to: latest prior finished_at among the compared outlets or None,
             no_change: True iff something was compared and nothing moved}."""
    delta = {kind: [] for kind in CHANGE_KINDS}
    compared_to = None
    for r in results:
        prev = previous.get(r["website"])
        prev_status = prev["status"] if prev else None
        if prev and prev.get("finished_at") and (compared_to is None or prev["finished_at"] > compared_to):
            compared_to = prev["finished_at"]
        delta[classify_change(r["status"], prev_status)].append(
            {"website": r["website"], "status": r["status"], "previous": prev_status})
    delta["compared_to"] = compared_to
    delta["no_change"] = bool(delta[CHANGE_UNCHANGED]) and not any(
        delta[k] for k in (CHANGE_NEW, CHANGE_CHANGED, CHANGE_RECOVERED, CHANGE_BASELINE))
    return delta


def log_to_db(results: list, session) -> None:
    from sqlalchemy import text
    # crawl_log.status CHECK allows only started/completed/failed.
    for r in results:
        # FALLBACK still produced articles (non-fatal, OPS-02) -- record it as
        # completed, with the note capturing that a fallback extractor was used.
        db_status = "completed" if r["status"] in (STATUS_OK, STATUS_FALLBACK) else "failed"
        note = ("%s: %s" % (r["status"], r["note"])) if r["note"] else r["status"]
        # OPS-12: both timestamps come from the outlet's own check window. Leaving
        # started_at to its DEFAULT NOW() made it equal finished_at on every row
        # (NOW() is transaction-start time), i.e. the *end* of the whole run.
        session.execute(text(
            "INSERT INTO crawl_log (website, task, status, article_count, error_msg, started_at, finished_at) "
            "VALUES (:w, 'health_check', :s, :c, :e, :started, :finished)"
        ), {"w": r["website"], "s": db_status, "c": r["sitemap_links"], "e": note,
            "started": r["started_at"], "finished": r["finished_at"]})
    session.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawler health checker")
    parser.add_argument("--website", help="Comma-separated subset (default: all)")
    parser.add_argument("--sample-size", type=int, default=3, help="Sample articles per outlet (default 3)")
    parser.add_argument("--workers", type=int, default=8, help="Outlet-level parallelism (default 8)")
    parser.add_argument("--timeout", type=int, default=60, help="Per-outlet timeout seconds (default 60)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON to stdout")
    parser.add_argument("--quiet", action="store_true", help="Print only the summary")
    parser.add_argument("--report-dir", default="crawler_health", help="Where to write the dated JSON report")
    parser.add_argument("--log-db", action="store_true",
                        help="Also append one crawl_log row per outlet (implies --diff-db)")
    parser.add_argument("--diff-db", action="store_true",
                        help="Lead the summary with what changed vs. each outlet's previous crawl_log row")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.website:
        wanted = [w.strip().upper() for w in args.website.split(",") if w.strip()]
        targets = {n: c for n, c in CRAWLER_DICT.items() if n.upper() in wanted}
        missing = [w for w in wanted if w not in {n.upper() for n in CRAWLER_DICT}]
        if missing:
            print("Unknown outlet(s): %s" % ", ".join(missing), file=sys.stderr)
        if not targets:
            print("No matching outlets.", file=sys.stderr)
            return 1
    else:
        targets = dict(CRAWLER_DICT)

    # OPS-13: the baseline must be read before this run's own rows land. `previous`
    # stays None (no delta, legacy summary) if the read fails; {} on a first run.
    previous = None
    if args.diff_db or args.log_db:
        try:
            with _db_session() as session:
                previous = load_previous_statuses(session)
        except Exception as e:
            print("WARN: --diff-db could not read the crawl_log baseline (delta omitted): %s" % e, file=sys.stderr)

    results = run_checks(targets, args.sample_size, args.workers, args.timeout)
    delta = compute_delta(results, previous) if previous is not None else None
    payload = build_payload(results, delta)

    report_path = write_report(payload, args.report_dir)
    if args.log_db:
        try:
            with _db_session() as session:
                log_to_db(results, session)
        except Exception as e:
            print("WARN: --log-db failed: %s" % e, file=sys.stderr)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    elif args.quiet:
        print(payload["summary"])
    else:
        print(render_table(results))
        print()
        print(payload["summary"])
        print("Report written to %s" % report_path)

    return 1 if any(r["status"] in UNHEALTHY for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
