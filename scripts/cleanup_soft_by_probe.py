#!/usr/bin/env python3
"""
SYS-45 (#140): remove saved articles the SYS-37 probe now calls soft.

Two populations, reported separately because they are different decisions:
  --scope allow-since   (SYS-45's own): articles saved under an allow-set
                        category since 2026-09-20 15:20 UTC -- the rows the
                        SYS-35 "never reject" gate waved through before the
                        probe existed (sitemaps.last_crawl_attempt is the
                        fetch stamp; articles has no created_at).
  --scope all           every saved article the probe calls soft -- the old
                        cosine score's accumulated noise across the corpus
                        (24.4% on the 2026-09-22 backfill dry-run). A far
                        bigger delete; the owner decides whether at all.

Verdicts come from the probe. By default they are re-derived from the
backfill's backup (backups/sys37_topic_backfill_*.json records is_news per
articles_id, same artifact) so this does not re-embed 11,700 rows through
e5-large; --recompute runs the live filter instead (30 min on CPU).

The delete itself is cleanup_offtopic_articles.py's machinery: JSON backup of
the articles + chunks about to go, SQL delete of articles/chunks/entity
mentions-free rows and the sitemaps status flip to rejected_filter, then the
FAISS vectors. Rows referenced by entity_mentions are skipped and counted.

    python scripts/cleanup_soft_by_probe.py --dry-run [--scope allow-since|all] [--sample 50]
    python scripts/cleanup_soft_by_probe.py --scope allow-since          # after the owner's go
"""
import argparse
import collections
import glob
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.importance_filter import category_gate  # noqa: E402
from newscrawler.core.importance_probe import PROBE_BODY_CHARS, build_check_text  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")
ALLOW_SINCE = datetime(2026, 9, 20, 15, 20, tzinfo=timezone.utc)

_ARTICLES_SQL = text("""
    SELECT a.articles_id, a.sitemap_id, s.sources, s.category, s.headline, s.last_crawl_attempt,
           LEFT(a.extracted_text, :n) AS body_head,
           EXISTS (SELECT 1 FROM entity_mentions m WHERE m.sitemap_id = a.sitemap_id) AS referenced
    FROM articles a JOIN sitemaps s USING (sitemap_id)
    ORDER BY a.articles_id
""")


def latest_backfill_backup():
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "sys37_topic_backfill_*.json")))
    return files[-1] if files else None


def verdicts_from_backup(path):
    with open(path, encoding="utf-8") as f:
        return {r["articles_id"]: bool(r["is_news"]) for r in json.load(f)}


def verdicts_recomputed(rows):
    from newscrawler.core.importance_filter import SemanticImportanceFilter
    filt = SemanticImportanceFilter()
    out = {}
    for i in range(0, len(rows), 256):
        chunk = rows[i:i + 256]
        decisions = filt.classify_batch([build_check_text(r.headline, r.body_head) for r in chunk], [r.category for r in chunk])
        out.update({r.articles_id: d.is_important for r, d in zip(chunk, decisions)})
    return out


def in_scope(row, scope):
    if scope == "all":
        return True
    stamp = row.last_crawl_attempt
    if stamp is not None and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return category_gate(row.category) == "allow" and stamp is not None and stamp >= ALLOW_SINCE


def select(rows, verdicts, scope):
    """(scoped, soft, unknown, referenced, deletable) -- pure, for the tests."""
    scoped = [r for r in rows if in_scope(r, scope)]
    soft = [r for r in scoped if verdicts.get(r.articles_id) is False]
    unknown = [r for r in scoped if r.articles_id not in verdicts]
    referenced = [r for r in soft if r.referenced]
    deletable = [r for r in soft if not r.referenced]
    return scoped, soft, unknown, referenced, deletable


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scope", choices=("allow-since", "all"), default="allow-since")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--recompute", action="store_true", help="Run the live filter instead of reading the backfill backup")
    parser.add_argument("--seed", type=int, default=20260922)
    args = parser.parse_args(argv)

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        rows = session.execute(_ARTICLES_SQL, {"n": PROBE_BODY_CHARS}).fetchall()

    if args.recompute:
        verdicts = verdicts_recomputed(rows)
        logger.info("verdicts recomputed through the live filter for %d articles", len(verdicts))
    else:
        path = latest_backfill_backup()
        if not path:
            logger.error("no backups/sys37_topic_backfill_*.json -- run the backfill or pass --recompute")
            return 1
        verdicts = verdicts_from_backup(path)
        logger.info("verdicts from %s (%d articles)", os.path.basename(path), len(verdicts))

    scoped, soft, unknown, referenced, deletable = select(rows, verdicts, args.scope)
    logger.info("scope %s: %d articles; probe says soft: %d (%.1f%%); %d referenced by entity_mentions (kept); "
                "%d deletable; %d without a verdict (saved after the backfill -- rerun it or --recompute)",
                args.scope, len(scoped), len(soft), 100 * len(soft) / max(1, len(scoped)), len(referenced), len(deletable), len(unknown))
    by = collections.Counter((r.sources, r.category) for r in deletable)
    for (src, cat), n in by.most_common(25):
        logger.info("  %-15s %-24s %5d", src, cat, n)
    rng = random.Random(args.seed)
    for r in rng.sample(deletable, min(args.sample, len(deletable))):
        logger.info("  SOFT  %-14s %-16s %s", r.sources, (r.category or "")[:16], (r.headline or "")[:95])

    if args.dry_run or not deletable:
        logger.info("[dry-run] would delete %d article(s) (+ their chunks and FAISS vectors) and mark their sitemaps rejected_filter. Nothing written.", len(deletable))
        return 0

    from scripts.cleanup_offtopic_articles import delete_articles  # the SYS-31/SYS-34 machinery: backup -> SQL -> FAISS
    tag = f"sys45_soft_by_probe_{args.scope}"
    n = delete_articles(client, [r.sitemap_id for r in deletable], backup_tag=tag)
    logger.info("deleted %d article(s); sitemaps -> rejected_filter; backup in %s", n, BACKUP_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
