#!/usr/bin/env python3
"""
SYS-16 backfill: classify existing "attempted, no article" sitemaps into
rejected_filter / empty_extraction using the semantic filter against their stored
headline. The article body was never saved for these rows (that's the whole
symptom), so the headline is the only signal available without re-fetching from
the network -- a reasonable approximation of the original title+body decision,
not a re-run of it.

- headline fails the filter        -> crawl_status = 'rejected_filter' (excluded
                                       from load_all_sitemaps permanently)
- headline is blank/whitespace-only -> crawl_status = 'empty_extraction' (keeps the
                                       normal cooldown retry)
- headline passes the filter        -> left 'pending' (the original rejection likely
                                       came from something other than topic -- e.g.
                                       the body had no usable text -- so don't guess
                                       a terminal state; it keeps retrying normally)

Usage:
    python scripts/backfill_sitemap_crawl_status.py [--website NAME] [--batch-size N] [--dry-run]

Requires scripts/migrate_sitemap_crawl_status.sql to have been applied first.

CAUTION -- sources under open "why does this produce zero articles despite a
healthy extractor" investigations (e.g. VIVA, SYS-08) should be excluded via
--website until that investigation lands: this backfill can't tell "genuinely
off-topic" apart from "a systemic bug made every extraction look empty", and
marking the latter rejected_filter would permanently hide the exact rows that
investigation needs to be able to retry once fixed. 2026-09-16: VIVA's 21,788
initial rejected_filter classifications were reverted to pending for this reason
pending SYS-08 -- re-run with --website VIVA once that ticket resolves.
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text
from sentence_transformers import util

from newscrawler.core.constants import INTERESTS
from newscrawler.core.importance_filter import SemanticImportanceFilter
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_FETCH_SQL = text("""
    SELECT s.sitemap_id, s.headline
    FROM sitemaps s
    WHERE s.crawl_status = 'pending'
      AND s.last_crawl_attempt IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = s.sitemap_id)
      AND (:website IS NULL OR s.sources = :website)
    ORDER BY s.sitemap_id
""")


def classify_batch(filter_: SemanticImportanceFilter, headlines):
    """Same decision as SemanticImportanceFilter.is_important(), but batch-encoded
    (one matrix operation for the whole batch instead of one model.encode() call
    per headline) -- the only way this finishes in a reasonable time over ~73k rows.
    """
    non_blank_idx = [i for i, h in enumerate(headlines) if h and h.strip()]
    is_important = [False] * len(headlines)
    if non_blank_idx:
        embeddings = filter_.model.encode([headlines[i] for i in non_blank_idx], convert_to_tensor=True)
        scores = util.cos_sim(embeddings, filter_.interest_embeddings)
        max_scores = scores.max(dim=1).values
        for pos, idx in enumerate(non_blank_idx):
            is_important[idx] = float(max_scores[pos]) >= filter_.threshold
    return is_important


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", default=None, help="Limit to one source (default: all)")
    parser.add_argument("--batch-size", type=int, default=512, help="Headlines encoded per batch (default: 512)")
    parser.add_argument("--dry-run", action="store_true", help="Classify and report counts without writing")
    args = parser.parse_args()

    client = SQLAlchemyClient()
    with client.get_session() as session:
        rows = session.execute(_FETCH_SQL, {"website": args.website}).fetchall()

    logger.info("%d sitemaps pending classification%s", len(rows), f" for {args.website}" if args.website else "")
    if not rows:
        return

    logger.info("Loading semantic filter model...")
    filter_ = SemanticImportanceFilter(interests=INTERESTS, model_name="paraphrase-multilingual-MiniLM-L12-v2")

    rejected_ids, empty_ids, left_pending = [], [], 0
    for start in range(0, len(rows), args.batch_size):
        chunk = rows[start:start + args.batch_size]
        headlines = [r.headline or "" for r in chunk]
        important = classify_batch(filter_, headlines)

        for row, headline, imp in zip(chunk, headlines, important):
            if imp:
                left_pending += 1
            elif headline.strip():
                rejected_ids.append(row.sitemap_id)
            else:
                empty_ids.append(row.sitemap_id)

        logger.info("Classified %d/%d", min(start + args.batch_size, len(rows)), len(rows))

    logger.info(
        "Result: %d -> rejected_filter, %d -> empty_extraction, %d left pending (headline alone looked important).",
        len(rejected_ids), len(empty_ids), left_pending,
    )

    if args.dry_run:
        logger.info("[dry-run] No rows written.")
        return

    with client.get_session() as session:
        if rejected_ids:
            session.execute(
                text("UPDATE sitemaps SET crawl_status = 'rejected_filter' WHERE sitemap_id = ANY(:ids)"),
                {"ids": rejected_ids},
            )
        if empty_ids:
            session.execute(
                text("UPDATE sitemaps SET crawl_status = 'empty_extraction' WHERE sitemap_id = ANY(:ids)"),
                {"ids": empty_ids},
            )
        session.commit()
    logger.info("Written.")


if __name__ == "__main__":
    main()
