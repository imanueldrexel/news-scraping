#!/usr/bin/env python3
"""
SRC-29 (#111): retire INEWS's regional-mirror duplicates, keeping each article's
one live copy.

What the backlog actually is (2026-09-25, `scripts/experiments/probe_inews_hosts.py`
and the EXPERIMENTS entry): the 22,406 regional-subdomain rows are only **199
distinct articles**. INEWS's regional sitemaps list every regional article under
**112 hosts** (`/read/<id>/<slug>` on bogor., gowa., subang. ...), and only the
article's home host serves it. The other copies return HTTP 404, so every
`task=full_text` spent most of its 1,000 fetches on them. The ticket's original
idea, "the 113 hosts are dead", is false: `bogor.inews.id/read/716996` is live,
and `gowa.inews.id/read/716996` is a 404. Retiring by host would lose the
live copies.

Per article id:
  * if a copy already has an `articles` row, that copy is the keeper (no fetch);
  * otherwise copies are fetched, hosts named in the slug first (a Bogor
    story usually lives on bogor.), through INEWS's own
    `page_loader.get_soup_with_reason`, until one is live -- the keeper;
  * every other copy of that id is retired: `fetch_failures` set to
    SITEMAP_MAX_FETCH_FAILURES and `last_fetch_error` naming the keeper, which is
    how `load_all_sitemaps` already excludes a dead URL (SYS-09);
  * an id where any fetch failed for a reason that is not per-URL (timeout,
    403, 5xx) is left completely alone. Only a 404/410/soft-404 is evidence;
  * an id with no live copy at all has every copy retired.
Keeping one copy per article is also the right dedup: two live copies of the same
story would otherwise become two articles.

Only `/read/<id>/` rows on a regional host are touched; `www.inews.id` and the
few non-article rows are not.

The network work happens once, in the dry run, which writes a plan; --apply
writes exactly that plan (backup first, one transaction), re-checking that each
row is still unsaved and not already retired.

    python scripts/retire_inews_mirror_duplicates.py --dry-run --plan backups/src29_plan.json
    python scripts/retire_inews_mirror_duplicates.py --apply backups/src29_plan.json   # after the owner's go
    # undo:  python scripts/reset_fetch_failures.py --like "HTTP 404 (SRC-29%"
"""
import argparse
import collections
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")
PER_URL_MARKERS = ("http 404", "http 410", "soft-404")  # = CrawlerServiceImpl.PER_URL_FAILURE_MARKERS

_MIRROR_RE = re.compile(r"^https?://([a-z0-9-]+)\.inews\.id/read/(\d+)/([^?#]*)")

_ROWS_SQL = text("""
    SELECT s.sitemap_id, s.link, s.fetch_failures, (a.sitemap_id IS NOT NULL) AS has_article
    FROM sitemaps s LEFT JOIN articles a ON a.sitemap_id = s.sitemap_id
    WHERE s.sources = 'INEWS' AND s.link ~ '^https?://[a-z0-9-]+\\.inews\\.id/read/[0-9]+/'
      AND s.link !~ '^https?://(www\\.)?inews\\.id/'
    ORDER BY s.sitemap_id
""")


def parse(link):
    """(host, article_id, slug) for a regional-mirror article link, else None."""
    m = _MIRROR_RE.match(link or "")
    if not m or m.group(1) == "www":
        return None
    return m.group(1), m.group(2), m.group(3)


def fetch_order(copies):
    """Hosts named in the slug first (`...-tenjo-bogor-terbakar` -> bogor.), then
    the rest by host name, so the order is deterministic."""
    def key(row):
        host, _, slug = parse(row.link)
        return (0 if host in slug.split("-") else 1, host)
    return sorted(copies, key=key)


def is_per_url(reason):
    text_ = (reason or "").lower()
    return any(m in text_ for m in PER_URL_MARKERS)


def plan_for_id(article_id, copies, fetch):
    """Pure given `fetch(link) -> reason or None (live)`.

    Returns {"id", "keep": sitemap_id or None, "retire": [sitemap_ids],
    "status": saved|found|none_live|unresolved, "fetches": n}."""
    saved = [r for r in copies if r.has_article]
    if saved:
        keep = saved[0].sitemap_id
        return {"id": article_id, "keep": keep, "status": "saved", "fetches": 0,
                "retire": [r.sitemap_id for r in copies if r.sitemap_id != keep and not r.has_article]}
    fetches = 0
    for row in fetch_order(copies):
        reason = fetch(row.link)
        fetches += 1
        if reason is None:
            return {"id": article_id, "keep": row.sitemap_id, "status": "found", "fetches": fetches,
                    "retire": [r.sitemap_id for r in copies if r.sitemap_id != row.sitemap_id]}
        if not is_per_url(reason):
            return {"id": article_id, "keep": None, "status": "unresolved", "fetches": fetches,
                    "retire": [], "reason": reason}
    return {"id": article_id, "keep": None, "status": "none_live", "fetches": fetches,
            "retire": [r.sitemap_id for r in copies]}


def build_plan(rows, fetch, workers=6):
    by_id = collections.defaultdict(list)
    for r in rows:
        p = parse(r.link)
        if p:
            by_id[p[1]].append(r)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        plans = list(ex.map(lambda kv: plan_for_id(kv[0], kv[1], fetch), sorted(by_id.items())))
    return plans


def _live_fetch():
    from newscrawler.core.crawler_dict_list import CRAWLER_DICT
    loader = CRAWLER_DICT["INEWS"].page_loader

    def fetch(link):
        url = link if "?page=all" in link else link + "?page=all"
        soup, reason = loader.get_soup_with_reason(url)
        return None if soup is not None else (reason or "unknown failure")
    return fetch


def summarise(plans):
    st = collections.Counter(p["status"] for p in plans)
    logger.info("%d article id(s): %s", len(plans), dict(st))
    logger.info("rows to retire: %d; live copies kept: %d; fetches spent: %d",
                sum(len(p["retire"]) for p in plans), sum(1 for p in plans if p["keep"]),
                sum(p["fetches"] for p in plans))
    for p in [p for p in plans if p["status"] == "unresolved"][:10]:
        logger.warning("  unresolved id %s: %s -- left untouched", p["id"], p.get("reason"))


def apply(client, plan_path):
    with open(plan_path, encoding="utf-8") as f:
        plans = json.load(f)["plans"]
    retire = {sid: p for p in plans for sid in p["retire"]}
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        current = session.execute(text(
            "SELECT s.sitemap_id, s.fetch_failures, s.last_fetch_error, s.last_crawl_attempt, "
            "(a.sitemap_id IS NOT NULL) AS has_article FROM sitemaps s "
            "LEFT JOIN articles a ON a.sitemap_id = s.sitemap_id WHERE s.sitemap_id = ANY(:ids)"),
            {"ids": list(retire)}).fetchall()
    todo = [r for r in current if not r.has_article and r.fetch_failures < SITEMAP_MAX_FETCH_FAILURES]
    skipped = len(retire) - len(todo)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = os.path.join(BACKUP_DIR, "src29_inews_mirror_retire_%s.json" % stamp)
    with open(backup, "w", encoding="utf-8") as f:
        json.dump([{"sitemap_id": r.sitemap_id, "fetch_failures": r.fetch_failures,
                    "last_fetch_error": r.last_fetch_error,
                    "last_crawl_attempt": r.last_crawl_attempt.isoformat() if r.last_crawl_attempt else None}
                   for r in todo], f)
    logger.info("backup of %d row(s) written to %s (%d skipped: saved meanwhile or already retired)",
                len(todo), backup, skipped)
    with client.get_session() as session:
        n = 0
        for r in todo:
            p = retire[r.sitemap_id]
            note = ("HTTP 404 (SRC-29: INEWS mirror duplicate of article %s; live copy sitemap %s)"
                    % (p["id"], p["keep"]) if p["keep"] else
                    "HTTP 404 (SRC-29: INEWS mirror duplicate of article %s; no live copy on any host)" % p["id"])
            n += session.execute(text(
                "UPDATE sitemaps SET fetch_failures = :cap, last_fetch_error = :note, last_crawl_attempt = NOW() "
                "WHERE sitemap_id = :sid AND fetch_failures < :cap"),
                {"cap": SITEMAP_MAX_FETCH_FAILURES, "note": note, "sid": r.sitemap_id}).rowcount
        session.commit()
    logger.info("retired %d row(s) in one transaction.", n)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Fetch, decide and write --plan; change nothing")
    g.add_argument("--apply", metavar="PLAN_JSON", help="Write a plan produced by --dry-run")
    ap.add_argument("--plan", default=os.path.join(BACKUP_DIR, "src29_inews_mirror_plan.json"))
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    if args.apply:
        return apply(client, args.apply)
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        rows = session.execute(_ROWS_SQL).fetchall()
    logger.info("%d regional-mirror article row(s) loaded", len(rows))
    plans = build_plan(rows, _live_fetch(), workers=args.workers)
    summarise(plans)
    os.makedirs(os.path.dirname(os.path.abspath(args.plan)), exist_ok=True)
    with open(args.plan, "w", encoding="utf-8") as f:
        json.dump({"created": datetime.now(timezone.utc).isoformat(), "plans": plans}, f)
    logger.info("[dry-run] plan written to %s. Nothing changed in the database.", args.plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
