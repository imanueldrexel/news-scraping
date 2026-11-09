#!/usr/bin/env python3
"""
DBT-20 (#70) step 2: re-crawl the sitemaps that have an L1 FAISS vector and
nothing else -- no chunks row at any level, no articles row -- so they get real
articles/chunks rows (and L2 vectors) through the normal pipeline.

Why a dedicated script: these rows are `pending`, but they sit behind up to
12,000 other pending rows of the same source in load_all_sitemaps' `ORDER BY
posted_at DESC LIMIT 1000` queue, and MEDIAINDONESIA (the whole population on
2026-09-18) is the one source crawled serially -- "the next task=all picks them
up" was never going to happen. crawl_newsdetails(specific_sitemaps=...) accepts an
explicit list, so this hands it exactly the orphan ids and nothing else.

What happens per sitemap is the ordinary _crawl_newsdetails_inner path: fetch,
extract, semantic filter, chunk, save_chunk_data (which finds the existing L1
vector by (sitemap_id, 1, 0) and reuses its embedding_id -- SYS-17, guarded by
SYS-26 -- and embeds the L2 chunks fresh), then the articles row. A sitemap whose
page now fails the filter is marked rejected_filter (its L1 vector stays an
orphan; see --report), one whose fetch fails is counted by SYS-09/OPS-15.

Step 3, --write-off-remaining: after the re-crawl, an orphan that can never get
an article -- its page the filter now rejects (crawl_status=rejected_filter), or
its URL retired at the fetch cap (fetch_failures >= SITEMAP_MAX_FETCH_FAILURES)
-- still has its L1 vector and nothing else, and that vector is evidence that
contradicts the row's status, which fix_rejected_filter_with_faiss_evidence.py
would flip back to pending, re-crawl, reject again, forever. Those vectors are
deleted from NEWS_L1 (docstore entries backed up to backups/ first). This is the
fleet's one terminal rule (SYS-54's terminal_with_chunks, OPS-25). DBT-27 (#88):
a row below the cap or `empty_extraction` is retried by the pipeline itself and
is left alone, as is any orphan still `pending`.

Usage:
    python scripts/recrawl_faiss_orphans.py --website MEDIAINDONESIA --dry-run
    python scripts/recrawl_faiss_orphans.py --website MEDIAINDONESIA
    python scripts/recrawl_faiss_orphans.py --website MEDIAINDONESIA --limit 50   # a first slice
    python scripts/recrawl_faiss_orphans.py --website MEDIAINDONESIA --write-off-remaining --dry-run
    python scripts/recrawl_faiss_orphans.py --website MEDIAINDONESIA --write-off-remaining
"""
import argparse
import json
import logging
import os
import pickle
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES, VECTOR_DB_NAME_L1
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# The orphan shape, restricted to ids that actually have an L1 vector (passed in).
_ORPHANS_SQL = text("""
    SELECT s.sitemap_id, s.link, s.headline, s.posted_at, s.sources, s.category, s.keywords,
           s.crawl_status, s.fetch_failures
    FROM sitemaps s
    WHERE s.sitemap_id = ANY(:l1_ids)
      AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = s.sitemap_id)
      AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = s.sitemap_id)
      AND (:website IS NULL OR s.sources = :website)
    ORDER BY s.posted_at DESC, s.sitemap_id
""")

_STATUS_SQL = text("""
    SELECT s.crawl_status,
           COUNT(*) AS n,
           COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = s.sitemap_id)) AS with_article,
           COUNT(*) FILTER (WHERE s.fetch_failures > 0) AS fetch_failed
    FROM sitemaps s WHERE s.sitemap_id = ANY(:ids) GROUP BY 1 ORDER BY 2 DESC
""")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")


def unrecoverable(rows):
    """The orphans that can never get an article: rejected by today's filter, or
    retired at the fetch cap. DBT-27: one transient failure (fetch_failures=1) or
    an empty extraction is retried after the cooldown, so its vector stays."""
    return [r for r in rows
            if r.crawl_status == "rejected_filter" or (r.fetch_failures or 0) >= SITEMAP_MAX_FETCH_FAILURES]


def write_off(client, rows, dry_run: bool, ds=None) -> int:
    """Delete the L1 vectors of `rows` (already known to have no chunks/articles
    row). Backs up each docstore entry (page_content + metadata) first, so the
    two-paragraph text is recoverable if anyone ever wants it. Returns the number
    of vectors removed (or that would be). `ds` is a ChunkFAISSDatasource; built
    here when not given (the tests pass their own)."""
    ids = {r.sitemap_id for r in rows}
    if not ids:
        logger.info("Nothing to write off.")
        return 0
    if ds is None:
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource,
        )
        ds = ChunkFAISSDatasource()
    doomed = {doc_id: doc for doc_id, doc in ds.vs_l1.docstore._dict.items()
              if doc.metadata.get("sitemap_id") is not None and int(doc.metadata["sitemap_id"]) in ids}
    logger.info("%d L1 vector(s) belong to the %d unrecoverable orphan(s)", len(doomed), len(ids))
    if dry_run or not doomed:
        return len(doomed)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"dbt20_written_off_l1_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"embedding_id": k, "page_content": d.page_content, "metadata": d.metadata}
                   for k, d in doomed.items()], f, default=str, indent=2)
    logger.info("Backed up %d docstore entries to %s", len(doomed), path)
    ds.vs_l1.delete(list(doomed))
    ds._atomic_save_local(ds.vs_l1, VECTOR_DB_NAME_L1)  # DBT-10: crash-safe swap, not a direct in-place overwrite
    logger.info("Deleted %d vector(s) from %s", len(doomed), VECTOR_DB_NAME_L1)
    return len(doomed)


def load_l1_sitemap_ids() -> set:
    with open(os.path.join(VECTOR_DB_NAME_L1, "index.pkl"), "rb") as f:
        docstore, _ = pickle.load(f)
    return {int(d.metadata["sitemap_id"]) for d in docstore._dict.values() if d.metadata.get("sitemap_id") is not None}


def find_orphans(session, l1_ids, website=None):
    return session.execute(_ORPHANS_SQL, {"l1_ids": list(l1_ids), "website": website}).fetchall()


def to_dtos(rows):
    from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
    dtos = []
    for r in rows:
        ts = datetime.strptime(str(r.posted_at), "%Y%m%d") if r.posted_at else None
        dtos.append(SitemapDTO(headline=r.headline, link=r.link, sources=r.sources, category=r.category,
                               timestamp=ts, keywords=r.keywords, sitemap_id=r.sitemap_id))
    return dtos


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", required=True, help="Source to re-crawl (one crawler per run)")
    parser.add_argument("--limit", type=int, default=None, help="Only the first N orphans (newest first)")
    parser.add_argument("--write-off-remaining", action="store_true",
                        help="Step 3: delete the L1 vectors of orphans that can never get an article "
                             "(rejected_filter / at the fetch cap); no fetching")
    parser.add_argument("--dry-run", action="store_true", help="List the population; fetch nothing, write nothing")
    args = parser.parse_args(argv)
    # OPS-26 (#175): not while a scheduled crawl holds FAISS in memory.
    from newscrawler.tools.run_lock import refused_by_run_lock
    if not args.dry_run and refused_by_run_lock(logger):
        return 2

    l1_ids = load_l1_sitemap_ids()
    client = SQLAlchemyClient()
    with client.get_session() as session:
        rows = find_orphans(session, l1_ids, args.website)

    by_status = {}
    for r in rows:
        by_status[r.crawl_status] = by_status.get(r.crawl_status, 0) + 1
    logger.info("%d L1-only orphan(s) for %s (crawl_status: %s)", len(rows), args.website, by_status)

    if args.write_off_remaining:
        doomed_rows = unrecoverable(rows)
        logger.info("%d of them are unrecoverable (rejected_filter / at the fetch cap); "
                    "%d still pending are left alone", len(doomed_rows), len(rows) - len(doomed_rows))
        n = write_off(client, doomed_rows, args.dry_run)
        if args.dry_run:
            logger.info("[dry-run] Would delete %d L1 vector(s).", n)
        return 0

    rows = [r for r in rows if r.crawl_status == "pending"]
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        logger.info("Nothing to re-crawl.")
        return 0
    if args.dry_run:
        for r in rows[:5]:
            logger.info("  e.g. %d %s %s", r.sitemap_id, r.posted_at, r.link)
        logger.info("[dry-run] Would re-crawl the %d URL(s) above through crawl_newsdetails(specific_sitemaps=...).",
                    len(rows))
        return 0

    from newscrawler.core.chunker import HierarchicalChunker
    from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
    from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl

    service = CrawlerServiceImpl(DataFlowRepositoryImpl(client), chunker=HierarchicalChunker())
    ids = [r.sitemap_id for r in rows]
    service.crawl_newsdetails(args.website, specific_sitemaps=to_dtos(rows))

    with client.get_session() as session:
        after = session.execute(_STATUS_SQL, {"ids": ids}).fetchall()
        still_orphan = len(find_orphans(session, set(ids), args.website))
    logger.info("After re-crawl, the %d target(s) are now: %s",
                len(ids), "; ".join(f"{r.crawl_status}: {r.n} (with article {r.with_article}, fetch_failed {r.fetch_failed})"
                                    for r in after))
    logger.info("Still L1-only orphans among the targets: %d "
                "(rejected_filter / fetch failures keep their orphan L1 vector -- write those off separately)",
                still_orphan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
