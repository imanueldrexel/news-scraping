#!/usr/bin/env python3
r"""
Re-chunk the stored articles whose L2 chunks the current chunker cuts differently. L2 only:
L1 rows, L1 vectors and entity mentions (which point at L1) are never touched.

- SYS-105 (#275): the chunker kept an article's trailing sign-off as its own L2 chunk ("(jon)").
  `--min-words N` (default 15, the search's own minimum) takes the articles that hold an L2 chunk
  under N words.
- SYS-109 (#283, ADR-008): L2 chunks became windows of at most 80 words that fit MiniLM's
  128-token input (they were up to 450 words, mostly unseen by semantic search). `--all` takes
  every article whose stored L2 layout differs from the chunker's.

  Step 1, the dry run (the default), is read-only: per source, the articles to re-chunk, their L2
  rows before -> after, and the L2 chunks under 10 words and over CHUNK_MAX_TOKENS before -> after.

      venv\Scripts\python.exe scripts\rechunk_stale_chunks.py [--source DETIK] [--min-words 15 | --all]

  Step 2, `--apply` (every source, or --source NAME), holding the run lock throughout:
    1. one backup for the run, under backups/<tag>_<source>_<stamp>/: a copy of NEWS_L2 and the
       L2 rows about to go (l2_rows.jsonl);
    2. delete the targets' L2 vectors (one atomic, generation-checked save);
    3. one SQL transaction: delete the targets' L2 rows (DBT-64's index makes the mention FK check
       cheap);
    4. per source, re-chunk from the stored text: `save_chunk_data` keeps the L1 row and vector it
       finds (SYS-17/SYS-25) and embeds the new L2, `--group` articles per embedding batch and one
       FAISS flush per `--block` articles, until --until HH:MM;
    5. re-attach any mention left without a chunk by an earlier version of this script;
    6. `ANALYZE chunks`, so the keyword half's pg_stats reflects the new rows (ADR-006).
  `--apply --resume` after a stop runs 4-6 only (the articles without L2 rows), with no new backup.

      venv\Scripts\python.exe scripts\rechunk_stale_chunks.py --all --apply --until 06:15
      venv\Scripts\python.exe scripts\rechunk_stale_chunks.py --apply --resume --until 11:30

  Exit: 0 done, 1 some articles failed to re-chunk, 2 refused (a crawl holds the run lock, or a
  crawl_log row is 'started'), 3 stopped at the deadline with articles left (run --resume).
"""
import argparse
import json
import logging
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core import constants  # noqa: E402
from newscrawler.core.chunker import HierarchicalChunker  # noqa: E402
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_MIN_WORDS = 15
FRAGMENT_WORDS = 10     # what QA counted (SYS-105's Done-when: none left that is not a whole article)
DEFAULT_BLOCK = 5000    # articles per FAISS flush: each flush rewrites the whole NEWS_L2 pair
DEFAULT_GROUP = 50      # articles per embedding batch

_LAYOUT = ("(SELECT array_agg(c.token_count ORDER BY c.chunk_index) FROM chunks c "
           "WHERE c.sitemap_id = a.sitemap_id AND c.chunk_level = 2)")
# The articles holding an L2 chunk under :min_words. The fragment-holders are found first:
# grouping by the text itself exhausted the container's shared memory.
FRAGMENT_CANDIDATES_SQL = text(f"""
    WITH fragments AS (
        SELECT DISTINCT sitemap_id FROM chunks WHERE chunk_level = 2 AND token_count < :min_words
    )
    SELECT a.sitemap_id, s.sources AS source, a.extracted_text, {_LAYOUT} AS l2_counts
    FROM fragments f
    JOIN articles a ON a.sitemap_id = f.sitemap_id
    JOIN sitemaps s ON s.sitemap_id = a.sitemap_id
    WHERE s.sources = :source
""")
# Every article of the source (--all), read per source and streamed.
ALL_CANDIDATES_SQL = text(f"""
    SELECT a.sitemap_id, s.sources AS source, a.extracted_text, {_LAYOUT} AS l2_counts
    FROM articles a JOIN sitemaps s ON s.sitemap_id = a.sitemap_id
    WHERE s.sources = :source
""")
SOURCES_SQL = text("SELECT DISTINCT s.sources FROM articles a JOIN sitemaps s ON s.sitemap_id = a.sitemap_id "
                   "WHERE (CAST(:source AS text) IS NULL OR s.sources = :source) ORDER BY 1")
L2_ROWS_SQL = text("SELECT chunk_id, sitemap_id, article_id, chunk_index, chunk_total, is_first_chunk, is_last_chunk, "
                   "text_content, token_count, embedding_id, chunk_status FROM chunks "
                   "WHERE sitemap_id = ANY(:ids) AND chunk_level = 2")
DELETE_L2_SQL = text("DELETE FROM chunks WHERE sitemap_id = ANY(:ids) AND chunk_level = 2")
# Mentions an earlier version of this script detached (it deleted L1 rows too); idempotent.
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
    """Pure. rows: (sitemap_id, source, extracted_text, stored L2 word counts or None). The articles
    whose layout changes, as {source: [(sitemap_id, stored counts, new counts)]}."""
    targets = defaultdict(list)
    for sitemap_id, source, body, stored in rows:
        new = new_l2_counts(chunker, body)
        if new and list(stored or []) != new:
            targets[source].append((sitemap_id, list(stored or []), new))
    return dict(targets)


def report(targets, max_words):
    lines = ["source            articles   L2 rows before -> after   L2 < %d words   L2 > %d words"
             % (FRAGMENT_WORDS, max_words)]
    total = [0] * 7
    for source in sorted(targets):
        items = targets[source]
        row = [len(items),
               sum(len(s) for _, s, _ in items), sum(len(n) for _, _, n in items),
               sum(1 for _, s, _ in items for w in s if w < FRAGMENT_WORDS),
               sum(1 for _, _, n in items for w in n if w < FRAGMENT_WORDS),
               sum(1 for _, s, _ in items for w in s if w > max_words),
               sum(1 for _, _, n in items for w in n if w > max_words)]
        lines.append("%-16s %9d %12d -> %-9d %6d -> %-5d %6d -> %d" % (source, *row))
        total = [a + b for a, b in zip(total, row)]
    lines.append("%-16s %9d %12d -> %-9d %6d -> %-5d %6d -> %d" % ("TOTAL", *total))
    return "\n".join(lines)


def load_targets(client, source, min_words, all_articles=False):
    """{source: [(sitemap_id, stored, new)]}, computed one source at a time (bodies are streamed)."""
    chunker = HierarchicalChunker()
    sql = ALL_CANDIDATES_SQL if all_articles else FRAGMENT_CANDIDATES_SQL
    with client.get_session() as session:
        sources = [r[0] for r in session.execute(SOURCES_SQL, {"source": source}).fetchall()]
    targets = {}
    for src in sources:
        with client.get_session() as session:
            rows = session.execute(sql.execution_options(stream_results=True),
                                   {"source": src, "min_words": min_words})
            found = select_targets(((r.sitemap_id, r.source, r.extracted_text, r.l2_counts) for r in rows), chunker)
        targets.update(found)
    return targets


def backup_l2(client, ids, l2_dir, path):
    """A copy of NEWS_L2 and the L2 rows about to be deleted (JSON lines), under `path`."""
    from repair_boilerplate_bodies import MIN_FREE_GB_FOR_BACKUP
    free_gb = shutil.disk_usage(os.path.dirname(path) if os.path.isdir(os.path.dirname(path)) else ROOT).free / 1e9
    if free_gb < MIN_FREE_GB_FOR_BACKUP:
        raise RuntimeError("only %.1f GB free; the backup needs about %d" % (free_gb, MIN_FREE_GB_FOR_BACKUP))
    os.makedirs(path, exist_ok=True)
    shutil.copytree(l2_dir, os.path.join(path, os.path.basename(l2_dir.rstrip("/\\"))))
    n = 0
    with open(os.path.join(path, "l2_rows.jsonl"), "w", encoding="utf-8") as f:
        for start in range(0, len(ids), 5000):
            with client.get_session() as session:
                for r in session.execute(L2_ROWS_SQL, {"ids": ids[start:start + 5000]}):
                    f.write(json.dumps(dict(r._mapping), default=str) + "\n")
                    n += 1
    logger.info("backup: %s (NEWS_L2 + %d L2 row(s))", path, n)
    return path


def apply(args, client=None, make_repo=None) -> int:
    """The write step. Holds the run lock (a crawl, the newsletter and the extraction wait or
    refuse meanwhile). Exit: 0 done, 1 failures, 2 refused, 3 stopped at the deadline."""
    from newscrawler.tools.run_lock import RunLock, RunLockHeld
    client = client or SQLAlchemyClient()
    try:
        with RunLock(purpose="re-chunk L2 (SYS-105/SYS-109)"):
            return _apply_locked(args, client, make_repo)
    except RunLockHeld as e:
        logger.error("refusing to write: %s", e)
        return 2


def _apply_locked(args, client, make_repo) -> int:
    import repair_boilerplate_bodies as sys73
    _, l2_dir = sys73._faiss_dirs()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        if sys73._crawl_running(session):
            logger.error("a crawl_log row is 'started' in the last 4 h; refusing to rewrite FAISS under a running crawl")
            return 2
    source = args.source.upper() if args.source else None
    summary = {"articles": 0, "l2_rows_deleted": 0, "vectors_deleted": 0}
    if not args.resume:
        targets = load_targets(client, source, args.min_words, args.all)
        print(report(targets, constants.CHUNK_MAX_TOKENS))
        ids = [sid for items in targets.values() for sid, _, _ in items]
        summary["articles"] = len(ids)
        if ids:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            tag = "sys109" if args.all else "sys105"
            summary["backup"] = backup_l2(client, ids, l2_dir,
                                          os.path.join(sys73.BACKUP_DIR, "%s_%s_%s" % (tag, source or "ALL", stamp)))
            summary["vectors_deleted"] = sum(sys73.delete_vectors([(sid, None) for sid in ids], [l2_dir]).values())
            with client.get_session() as session:
                summary["l2_rows_deleted"] = session.execute(DELETE_L2_SQL, {"ids": ids}).rowcount
                session.commit()
            logger.info("deleted %d L2 row(s) and %d vector(s) of %d article(s)", summary["l2_rows_deleted"],
                        summary["vectors_deleted"], len(ids))
    deadline = sys73.parse_until(args.until)
    if make_repo is None:
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl
        make_repo = DataFlowRepositoryImpl
    # One repository (one load of the encoder and both indexes) for every source, built after the
    # deletes above so it loads the index they saved.
    built = {}

    def shared_repo(c):
        if "repo" not in built:
            built["repo"] = make_repo(c)
        return built["repo"]

    with client.get_session() as session:
        sources = [r[0] for r in session.execute(SOURCES_SQL, {"source": source}).fetchall()]
    failed = left = reattached = 0
    for src in sources:
        repaired, empty, f, lft = sys73.rechunk(client, src, args.block, deadline, shared_repo, group_size=args.group)
        failed, left = failed + f, left + lft
        with client.get_session() as session:
            reattached += session.execute(REATTACH_SQL, {"source": src}).rowcount
            session.commit()
        if lft:
            break
    if not left:
        with client.get_session() as session:
            session.execute(text("ANALYZE chunks"))
            session.commit()
        logger.info("ANALYZE chunks done")
    summary.update(failed=failed, left=left, mentions_reattached=reattached)
    logger.info("SUMMARY: %s", json.dumps(summary))
    return 3 if left else (1 if failed else 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None, help="One source only (default: all)")
    parser.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS,
                        help="Re-chunk articles holding an L2 chunk under this many words (default 15)")
    parser.add_argument("--all", action="store_true",
                        help="Every article whose L2 layout differs from the chunker's (SYS-109)")
    parser.add_argument("--apply", action="store_true", help="Write (default: the dry run)")
    parser.add_argument("--resume", action="store_true",
                        help="With --apply: re-chunk the articles a stopped run left without L2 rows; no backup")
    parser.add_argument("--block", type=int, default=DEFAULT_BLOCK, help="Articles per FAISS flush (default 5000)")
    parser.add_argument("--group", type=int, default=DEFAULT_GROUP, help="Articles per embedding batch (default 50)")
    parser.add_argument("--until", default=None, metavar="HH:MM", help="Stop starting blocks at this local time")
    args = parser.parse_args(argv)

    if args.apply:
        # OPS-26/DBT-43: this writes NEWS_L2 (through repair_boilerplate_bodies' helpers); refuse at
        # the door while a crawl holds the run lock, before the database or the indexes are touched.
        from newscrawler.tools.run_lock import refused_by_run_lock
        if refused_by_run_lock(logger):
            return 2
        return apply(args)

    targets = load_targets(SQLAlchemyClient(), args.source.upper() if args.source else None, args.min_words, args.all)
    print(report(targets, constants.CHUNK_MAX_TOKENS))
    print("\n(dry run: nothing was written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
