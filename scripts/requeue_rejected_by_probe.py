#!/usr/bin/env python3
"""
SYS-38 (#122): give the rows the OLD filter rejected a second chance under the
SYS-37 probe.

`rejected_filter` is terminal (SYS-16): a row the cosine filter rejected is
never offered again, and its body was never stored. So every false negative of
that filter is still lost unless the row is re-queued. Rows rejected since the
probe went live (2026-09-22 02:10 UTC) were decided by the probe itself, with
the body; re-scoring those on the headline alone could only be worse, so they
are not touched.

Selection: `rejected_filter` rows whose rejection is older than the probe
(`last_crawl_attempt < PROBE_LIVE_AT`), posted on or after --since (default
90 days back, on `posted_at`), not denied by the category gate for their source
(soft verticals stay rejected), and below the fetch-failure cap. Each is scored
by `SemanticImportanceFilter.classify_batch` on its headline alone -- the live
decision function, not a copy -- and re-queued when P(soft) < --soft-threshold
(default 0.7, lenient on purpose: the headline is a weaker input, and the live
filter makes the real call with the body when the row is fetched again).

The real run, after a JSON backup to backups/, in one transaction:
    crawl_status 'rejected_filter' -> 'pending', last_crawl_attempt -> NULL
and one crawl_log row (website 'ALL', task 'requeue_rejected'). Idempotent: a
re-queued row is no longer 'rejected_filter', and a row the live filter
rejects again is stamped after PROBE_LIVE_AT, so a second run selects nothing.
Nothing is fetched here; the rows re-enter load_all_sitemaps' newest-first
queue behind the fresh ones (they are older).

    python scripts/requeue_rejected_by_probe.py --dry-run [--website A,B] [--exclude VIVA] [--since 20260701]
    python scripts/requeue_rejected_by_probe.py [--website A,B] [--limit N]
"""
import argparse
import collections
import json
import logging
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES, SOFT_THRESHOLD  # noqa: E402
from newscrawler.core.importance_filter import category_gate  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")
PROBE_LIVE_AT = datetime(2026, 9, 22, 2, 10, tzinfo=timezone.utc)
DEFAULT_SINCE_DAYS = 90

_CANDIDATES_SQL = text("""
    SELECT s.sitemap_id, s.sources AS source, s.category, s.headline, s.posted_at, s.last_crawl_attempt
    FROM sitemaps s
    WHERE s.crawl_status = 'rejected_filter'
      AND s.last_crawl_attempt < :probe_live_at
      AND s.posted_at >= :since
      AND s.fetch_failures < :cap
      AND s.headline IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = s.sitemap_id)
    ORDER BY s.posted_at DESC, s.sitemap_id DESC
""")
_REQUEUE_SQL = text("""
    UPDATE sitemaps SET crawl_status = 'pending', last_crawl_attempt = NULL
    WHERE sitemap_id = ANY(:ids) AND crawl_status = 'rejected_filter'
""")


def select_rows(rows, websites=None, exclude=()):
    """Pure: the candidates a run may score -- source filters applied, the
    category gate's denials dropped (soft verticals stay rejected)."""
    wanted = set(websites) if websites else None
    out = []
    for r in rows:
        if wanted is not None and r["source"] not in wanted:
            continue
        if r["source"] in exclude:
            continue
        if category_gate(r["category"], r["source"]) == "deny":
            continue
        out.append(r)
    return out


def decide(rows, decisions, soft_threshold):
    """Pure: (requeue, keep) given one FilterDecision per row, in order."""
    if len(decisions) != len(rows):
        raise RuntimeError(f"{len(decisions)} decisions for {len(rows)} rows")
    requeue, keep = [], []
    for r, d in zip(rows, decisions):
        r = dict(r, p_soft=d.p_soft, topic=d.topic)
        (requeue if d.p_soft is not None and d.p_soft < soft_threshold else keep).append(r)
    return requeue, keep


def score(rows):
    from newscrawler.core.importance_filter import SemanticImportanceFilter
    from newscrawler.core.importance_probe import build_check_text
    filt = SemanticImportanceFilter(soft_threshold=SOFT_THRESHOLD)
    decisions = []
    for i in range(0, len(rows), 512):
        chunk = rows[i:i + 512]
        decisions += filt.classify_batch([build_check_text(r["headline"], "") for r in chunk],
                                         [r["category"] for r in chunk], [r["source"] for r in chunk])
        logger.info("  scored %d/%d", i + len(chunk), len(rows))
    return decisions


def report(requeue, keep, rng):
    by_src = collections.Counter(r["source"] for r in requeue)
    by_cell = collections.Counter((r["source"], r["category"]) for r in requeue)
    by_topic = collections.Counter(r["topic"] for r in requeue)
    logger.info("re-queue %d, keep rejected %d", len(requeue), len(keep))
    logger.info("re-queue by source: %s", dict(by_src.most_common()))
    logger.info("re-queue by source x category (top 20): %s", by_cell.most_common(20))
    logger.info("re-queue by predicted topic: %s", dict(by_topic.most_common()))
    for label, rows in (("RE-QUEUE", requeue), ("KEEP", keep)):
        for r in rng.sample(rows, min(25, len(rows))):
            logger.info("  %s p_soft=%.2f %s/%s %s | %s", label, r["p_soft"] or -1, r["source"], r["category"],
                        r["topic"], (r["headline"] or "")[:100])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--website", help="comma-separated sources (default: all)")
    ap.add_argument("--exclude", default="", help="comma-separated sources to leave out")
    ap.add_argument("--since", type=int, default=None, help="posted_at YYYYMMDD floor (default: 90 days back)")
    ap.add_argument("--soft-threshold", type=float, default=0.7)
    ap.add_argument("--limit", type=int, default=None, help="re-queue at most N (newest first)")
    ap.add_argument("--seed", type=int, default=20260929)
    args = ap.parse_args(argv)
    since = args.since or int((date.today() - timedelta(days=DEFAULT_SINCE_DAYS)).strftime("%Y%m%d"))

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    with client.get_session() as s:
        rows = [dict(r._mapping) for r in s.execute(_CANDIDATES_SQL, {
            "probe_live_at": PROBE_LIVE_AT, "since": since, "cap": SITEMAP_MAX_FETCH_FAILURES})]
    websites = args.website.split(",") if args.website else None
    exclude = tuple(x for x in args.exclude.split(",") if x)
    candidates = select_rows(rows, websites, exclude)
    logger.info("%d pre-probe rejects posted since %d; %d after source filters and the category gate",
                len(rows), since, len(candidates))
    if not candidates:
        return 0
    requeue, keep = decide(candidates, score(candidates), args.soft_threshold)
    if args.limit:
        requeue = requeue[:args.limit]
    report(requeue, keep, random.Random(args.seed))
    if args.dry_run:
        logger.info("[dry-run] nothing written.")
        return 0

    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
        SQLAlchemyArticleDataSource,
    )
    log_ds = SQLAlchemyArticleDataSource(client)
    log_id = log_ds.log_crawl_start("ALL", "requeue_rejected")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"sys38_requeue_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(requeue, f, ensure_ascii=False, default=str, indent=1)
    with client.get_session() as s:
        n = s.execute(_REQUEUE_SQL, {"ids": [r["sitemap_id"] for r in requeue]}).rowcount
        s.commit()
    log_ds.log_crawl_complete(log_id, n, note=f"re-queued {n} pre-probe rejects (headline P(soft) < "
                                              f"{args.soft_threshold}, since {since}); backup {path}")
    logger.info("re-queued %d row(s); backup %s", n, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
