#!/usr/bin/env python3
r"""
SRC-60 (#279): settle the stored sitemaps a crawler now calls out of scope by their URL.

KUMPARAN's news sitemaps list readers' blog posts next to the newsroom's articles; 321 of its
1,878 stored articles (2026-10-08) are "Tulisan dari ... tidak mewakili pandangan dari redaksi
kumparan" and they reached the top of the search. The crawler now skips them when listing
(`Crawler.out_of_scope_reason`); this script applies the same rule, imported, never re-derived,
to what is already stored: every sitemap of the source whose link the crawler calls out of scope
and that is not yet settled (an article, chunk rows, or a status other than rejected_filter).

  Step 1, the dry run (the default), is read-only: how many sitemaps, articles, chunk rows and
  entity mentions would go, a sample per account, and how many of the articles to delete and of
  the articles kept carry KUMPARAN's reader-post disclaimer (a check on the rule).

      venv\Scripts\python.exe scripts\settle_out_of_scope_links.py --source KUMPARAN

  Step 2, `--apply --source NAME`, holding the run lock throughout:
    1. back up NEWS_L1/NEWS_L2 and the rows about to change (backups/src60_<source>_<stamp>/);
    2. delete their vectors from both indexes (atomic, generation-checked saves; vectors first,
       so a kill leaves rows without vectors, never vectors without rows: SYS-54's order);
    3. one SQL transaction: delete their entity mentions, chunk rows and articles, and set
       sitemaps.crawl_status = 'rejected_filter', so the queue never offers them again;
    4. recompute the counters of the entities that lost mentions (SYS-20).
  A second run finds nothing left to settle.

      venv\Scripts\python.exe scripts\settle_out_of_scope_links.py --source KUMPARAN --apply

  Exit: 0 done, 2 refused (a crawl holds the run lock, or a crawl_log row is 'started').
"""
import argparse
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

READER_POST_DISCLAIMER = "tidak mewakili pandangan dari redaksi kumparan"

ROWS_SQL = text("""
    SELECT s.sitemap_id, s.link, s.headline, s.crawl_status,
           a.sitemap_id IS NOT NULL AS has_article,
           COALESCE(a.extracted_text ILIKE :disclaimer, false) AS has_disclaimer,
           EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = s.sitemap_id) AS has_chunks
    FROM sitemaps s LEFT JOIN articles a ON a.sitemap_id = s.sitemap_id
    WHERE s.sources = :source
""")


def select_targets(rows, reason_of):
    """Pure. rows: objects with sitemap_id, link, crawl_status, has_article, has_chunks.
    The rows the crawler calls out of scope and that are not settled yet, as (row, reason)."""
    out = []
    for r in rows:
        reason = reason_of(r.link)
        if reason and (r.has_article or r.has_chunks or r.crawl_status != "rejected_filter"):
            out.append((r, reason))
    return out


def account(link):
    return urlparse(link or "").path.strip("/").split("/")[0]


def report(rows, targets):
    target_ids = {r.sitemap_id for r, _ in targets}
    kept = [r for r in rows if r.sitemap_id not in target_ids and r.has_article]
    articles = [r for r, _ in targets if r.has_article]
    lines = [
        "%d sitemap(s) to settle: %d with an article, %d with chunk rows, by status %s" % (
            len(targets), len(articles), sum(1 for r, _ in targets if r.has_chunks),
            dict(Counter(r.crawl_status for r, _ in targets))),
        "reasons: %s" % dict(Counter(reason for _, reason in targets)),
        "reader-post disclaimer: %d of the %d articles to delete; %d of the %d articles kept" % (
            sum(1 for r in articles if r.has_disclaimer), len(articles),
            sum(1 for r in kept if r.has_disclaimer), len(kept)),
        "accounts of the articles to delete (most frequent, 3 headlines each):",
    ]
    by_account = defaultdict(list)
    for r in articles:
        by_account[account(r.link)].append(r.headline)
    for name, headlines in sorted(by_account.items(), key=lambda kv: -len(kv[1]))[:12]:
        lines.append("  %-32s %3d  %s" % (name[:32], len(headlines), " | ".join(h[:60] for h in headlines[:3])))
    return "\n".join(lines)


def load(client, source):
    from newscrawler.core.crawler_dict_list import CRAWLER_DICT
    crawler = CRAWLER_DICT[source]
    with client.get_session() as session:
        rows = session.execute(ROWS_SQL, {"source": source, "disclaimer": "%" + READER_POST_DISCLAIMER + "%"}).fetchall()
    return rows, select_targets(rows, crawler.out_of_scope_reason)


def settle_rows(session, ids):
    """One transaction. Returns (mentions, chunk rows, articles deleted, sitemaps settled)."""
    mentions = session.execute(text("DELETE FROM entity_mentions WHERE sitemap_id = ANY(:i)"), {"i": ids}).rowcount
    chunks = session.execute(text("DELETE FROM chunks WHERE sitemap_id = ANY(:i)"), {"i": ids}).rowcount
    articles = session.execute(text("DELETE FROM articles WHERE sitemap_id = ANY(:i)"), {"i": ids}).rowcount
    settled = session.execute(text("UPDATE sitemaps SET crawl_status = 'rejected_filter' WHERE sitemap_id = ANY(:i)"),
                              {"i": ids}).rowcount
    session.commit()
    return mentions, chunks, articles, settled


def apply(args, client=None) -> int:
    from newscrawler.tools.run_lock import RunLock, RunLockHeld
    client = client or SQLAlchemyClient()
    try:
        with RunLock(purpose="SRC-60 settle out-of-scope links %s" % args.source):
            return _apply_locked(args, client)
    except RunLockHeld as e:
        logger.error("refusing to write: %s", e)
        return 2


def _apply_locked(args, client) -> int:
    import repair_boilerplate_bodies as sys73
    source = args.source.upper()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        if sys73._crawl_running(session):
            logger.error("a crawl_log row is 'started' in the last 4 h; refusing to rewrite FAISS under a running crawl")
            return 2
    rows, targets = load(client, source)
    print(report(rows, targets))
    ids = [r.sitemap_id for r, _ in targets]
    summary = {"sitemaps": len(ids)}
    if ids:
        dirs = sys73._faiss_dirs()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        summary["backup"] = sys73.backup(client, source, [(sid, None) for sid in ids], dirs, stamp, tag="src60")
        summary["vectors_deleted"] = sum(sys73.delete_vectors([(sid, None) for sid in ids], dirs).values())
        with client.get_session() as session:
            m, c, a, s = settle_rows(session, ids)
        summary.update(mentions_deleted=m, chunk_rows_deleted=c, articles_deleted=a, sitemaps_settled=s)
        if m:
            import recount_entity_mentions
            recount_entity_mentions.main([])     # SYS-20: the counters of entities that lost mentions
    logger.info("SUMMARY %s: %s", source, json.dumps(summary))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="The source whose crawler decides (e.g. KUMPARAN)")
    parser.add_argument("--apply", action="store_true", help="Write (default: the dry run)")
    args = parser.parse_args(argv)
    if args.apply:
        # OPS-26/DBT-43: this writes NEWS_L1/L2 (through repair_boilerplate_bodies' helpers); refuse at
        # the door while a crawl holds the run lock, before the database or the indexes are touched.
        from newscrawler.tools.run_lock import refused_by_run_lock
        if refused_by_run_lock(logger):
            return 2
        return apply(args)
    rows, targets = load(SQLAlchemyClient(), args.source.upper())
    print(report(rows, targets))
    print("\n(dry run: nothing was written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
