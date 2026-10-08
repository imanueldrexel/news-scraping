#!/usr/bin/env python3
r"""
SYS-105 (#275): re-chunk the stored articles whose chunks the current chunker cuts differently.

The chunker kept an article's trailing sign-off as its own L2 chunk ("(jon)", "--", "Editor: X"):
1,606 L2 chunks had under 10 words, and as one-word vectors they filled the search page's
sources. It now merges a short last paragraph backward. This script brings the stored chunks in
line for the articles that hold a fragment: an L2 chunk under --min-words words (default 15, the
search's own minimum, web/query_processor.MIN_PARAGRAPH_WORDS) where the chunker now cuts the
stored text differently. --min-words 80 (CHUNK_MIN_TOKENS) takes every article the change touches.

  Step 1, the dry run (the default), is read-only: per source, the articles to re-chunk, the chunk
  rows they own, and their L2 chunks under 10 words before and after.

      venv\Scripts\python.exe scripts\rechunk_stale_chunks.py [--source DETIK] [--min-words 15]

  Step 2, `--apply` (every source, or --source NAME), holding the run lock throughout:
    1. back up NEWS_L1/NEWS_L2 and the rows about to change (backups/sys105_<source>_<stamp>/);
    2. delete the targets' vectors from both indexes (atomic, generation-checked saves);
    3. one SQL transaction: detach their entity mentions from the chunk rows (the mentions stay:
       the text does not change, so nothing is re-extracted), delete their chunk rows;
    4. per source, re-chunk and re-embed from the stored text, one FAISS flush per --block
       articles (repair_boilerplate_bodies.rechunk, until --until HH:MM if given);
    5. re-attach every detached mention to its article's new L1 chunk (the extractor's link).
  Killed after 3, a second run finishes 4 and 5 (they pick up articles without chunks and
  mentions without a chunk); it is idempotent.

      venv\Scripts\python.exe scripts\rechunk_stale_chunks.py --apply --until 18:30

  Exit: 0 done, 1 some articles failed to re-chunk, 2 refused (a crawl holds the run lock, or a
  crawl_log row is 'started'), 3 stopped at the deadline with articles left.
"""
import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.chunker import HierarchicalChunker  # noqa: E402
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_MIN_WORDS = 15
FRAGMENT_WORDS = 10     # what QA counted (SYS-105's Done-when: none left that is not a whole article)

# The articles with an L2 chunk under :min_words, their stored text and stored L2 layout. The
# fragment-holders are found first: grouping by the text itself exhausted the container's
# shared memory (a parallel hash aggregate over 90k bodies).
CANDIDATES_SQL = text("""
    WITH fragments AS (
        SELECT DISTINCT sitemap_id FROM chunks WHERE chunk_level = 2 AND token_count < :min_words
    )
    SELECT a.sitemap_id, s.sources AS source, a.extracted_text,
           (SELECT array_agg(c.token_count ORDER BY c.chunk_index) FROM chunks c
            WHERE c.sitemap_id = a.sitemap_id AND c.chunk_level = 2) AS l2_counts
    FROM fragments f
    JOIN articles a ON a.sitemap_id = f.sitemap_id
    JOIN sitemaps s ON s.sitemap_id = a.sitemap_id
    WHERE (CAST(:source AS text) IS NULL OR s.sources = :source)
    ORDER BY a.sitemap_id
""")
DETACH_SQL = text("UPDATE entity_mentions SET chunk_id = NULL WHERE sitemap_id = ANY(:ids) AND chunk_id IS NOT NULL")
DELETE_CHUNKS_SQL = text("DELETE FROM chunks WHERE sitemap_id = ANY(:ids)")
REATTACH_SQL = text("""
    UPDATE entity_mentions m SET chunk_id = c.chunk_id
    FROM chunks c, sitemaps s
    WHERE m.chunk_id IS NULL AND c.sitemap_id = m.sitemap_id AND c.chunk_level = 1
      AND s.sitemap_id = m.sitemap_id AND s.sources = :source
""")


def new_l2_counts(chunker, extracted_text):
    """The word counts of the L2 chunks the chunker gives this stored text now (SYS-18: paragraphs
    are joined with a blank line, as rechunk_articles splits them)."""
    paragraphs = [p for p in (extracted_text or "").split("\n\n") if p.strip()]
    if not paragraphs:
        return []
    news = NewsDetailsDTO(sitemap_id=0, extracted_text=paragraphs, reporter=[], meta_data={"title": ""})
    return [c.token_count for c in chunker.chunk(news) if c.chunk_level == 2]


def select_targets(rows, chunker):
    """Pure. rows: (sitemap_id, source, extracted_text, stored L2 word counts). The articles whose
    layout changes, as {source: [(sitemap_id, stored counts, new counts)]}."""
    targets = defaultdict(list)
    for sitemap_id, source, body, stored in rows:
        new = new_l2_counts(chunker, body)
        if new and list(stored) != new:
            targets[source].append((sitemap_id, list(stored), new))
    return dict(targets)


def report(targets, chunk_rows):
    lines = ["source            articles  chunk rows  L2 < %d words: before -> after" % FRAGMENT_WORDS]
    total = [0, 0, 0, 0]
    for source in sorted(targets):
        items = targets[source]
        before = sum(1 for _, stored, _ in items for n in stored if n < FRAGMENT_WORDS)
        after = sum(1 for _, _, new in items for n in new if n < FRAGMENT_WORDS)
        rows = chunk_rows.get(source, 0)
        lines.append("%-16s %9d %11d %10d -> %d" % (source, len(items), rows, before, after))
        total = [total[0] + len(items), total[1] + rows, total[2] + before, total[3] + after]
    lines.append("%-16s %9d %11d %10d -> %d" % ("TOTAL", *total))
    return "\n".join(lines)


def load_targets(client, source, min_words):
    chunker = HierarchicalChunker()
    with client.get_session() as session:
        rows = session.execute(CANDIDATES_SQL, {"source": source, "min_words": min_words}).fetchall()
    targets = select_targets(((r.sitemap_id, r.source, r.extracted_text, r.l2_counts) for r in rows), chunker)
    chunk_rows = {}
    with client.get_session() as session:
        for src, items in targets.items():
            chunk_rows[src] = session.execute(text("SELECT count(*) FROM chunks WHERE sitemap_id = ANY(:i)"),
                                              {"i": [sid for sid, _, _ in items]}).scalar()
    return targets, chunk_rows


def apply(args, client=None, make_repo=None) -> int:
    """The write step. Holds the run lock (a crawl, the newsletter and the extraction wait or
    refuse meanwhile). Exit: 0 done, 1 failures, 2 refused, 3 stopped at the deadline."""
    from newscrawler.tools.run_lock import RunLock, RunLockHeld
    client = client or SQLAlchemyClient()
    try:
        with RunLock(purpose="SYS-105 re-chunk"):
            return _apply_locked(args, client, make_repo)
    except RunLockHeld as e:
        logger.error("refusing to write: %s", e)
        return 2


def _apply_locked(args, client, make_repo) -> int:
    import repair_boilerplate_bodies as sys73
    dirs = sys73._faiss_dirs()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        if sys73._crawl_running(session):
            logger.error("a crawl_log row is 'started' in the last 4 h; refusing to rewrite FAISS under a running crawl")
            return 2
    source = args.source.upper() if args.source else None
    targets, chunk_rows = load_targets(client, source, args.min_words)
    print(report(targets, chunk_rows))
    ids = [sid for items in targets.values() for sid, _, _ in items]
    summary = {"articles": len(ids), "chunk_rows_deleted": 0, "vectors_deleted": 0, "mentions_detached": 0}
    if ids:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        summary["backup"] = sys73.backup(client, source or "ALL", [(sid, None) for sid in ids], dirs, stamp,
                                         tag="sys105")
        summary["vectors_deleted"] = sum(sys73.delete_vectors([(sid, None) for sid in ids], dirs).values())
        with client.get_session() as session:
            summary["mentions_detached"] = session.execute(DETACH_SQL, {"ids": ids}).rowcount
            summary["chunk_rows_deleted"] = session.execute(DELETE_CHUNKS_SQL, {"ids": ids}).rowcount
            session.commit()
        logger.info("deleted %d chunk row(s) of %d article(s); %d mention(s) detached", summary["chunk_rows_deleted"],
                    len(ids), summary["mentions_detached"])
    deadline = sys73.parse_until(args.until)
    failed = left = 0
    reattached = 0
    for src in sorted(set(targets) | ({source} if source else set())):
        if make_repo is None:
            from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
                DataFlowRepositoryImpl,
            )
            make_repo = DataFlowRepositoryImpl
        repaired, empty, f, lft = sys73.rechunk(client, src, args.block, deadline, make_repo)
        failed, left = failed + f, left + lft
        with client.get_session() as session:
            reattached += session.execute(REATTACH_SQL, {"source": src}).rowcount
            session.commit()
        if lft:
            break
    summary.update(failed=failed, left=left, mentions_reattached=reattached)
    logger.info("SUMMARY: %s", json.dumps(summary))
    return 3 if left else (1 if failed else 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None, help="One source only (default: all)")
    parser.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS,
                        help="Re-chunk articles holding an L2 chunk under this many words (default 15)")
    parser.add_argument("--apply", action="store_true", help="Write (default: the dry run)")
    parser.add_argument("--block", type=int, default=1000, help="Articles per FAISS flush (default 1000)")
    parser.add_argument("--until", default=None, metavar="HH:MM", help="Stop starting blocks at this local time")
    args = parser.parse_args(argv)

    if args.apply:
        # OPS-26/DBT-43: this writes NEWS_L1/L2 (through repair_boilerplate_bodies' helpers); refuse at
        # the door while a crawl holds the run lock, before the database or the indexes are touched.
        from newscrawler.tools.run_lock import refused_by_run_lock
        if refused_by_run_lock(logger):
            return 2
        return apply(args)

    targets, chunk_rows = load_targets(SQLAlchemyClient(), args.source.upper() if args.source else None,
                                       args.min_words)
    print(report(targets, chunk_rows))
    print("\n(dry run: nothing was written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
