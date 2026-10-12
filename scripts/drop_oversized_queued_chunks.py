#!/usr/bin/env python3
r"""
SYS-137 (#316): drop the chunks of queued sitemaps that an older chunker wrote (an L2 row longer
than CHUNK_MAX_TOKENS words), so the crawl chunks them fresh when it reaches them.

VIVA's June backlog (SYS-54) holds chunks written on 2026-06-02, L2 rows of up to 450 words. That
is past MiniLM's 128-token window (SYS-109, ADR-008). The crawl's dedup keeps any stored level, so
when it saves such a sitemap's article, the article adopts the old chunks. A sitemap with no
article row is not served (a hit without an article is dropped) and has no entity mentions, so
its chunks simply go, BOTH levels: its June L1 was cut from June's extraction, and the crawl
writes L1 and L2 from the same fresh fetch. (The first run on 2026-10-12 dropped L2 only and left
2,171 L1-only sitemaps, which the store check reads as `l1_not_in_l2`; a sitemap with no article,
an L1 level and no L2 level is therefore a target too.)

Articles that already adopted such chunks are not this script's: `rechunk_stale_chunks.py
--source VIVA --apply` re-chunks them, keeping their entity mentions.

  Step 1, the dry run (the default), is read-only: the sitemaps, their crawl status, the chunk rows
  that would go.

      venv\Scripts\python.exe scripts\drop_oversized_queued_chunks.py [--source VIVA]

  Step 2, `--apply`, holding the run lock throughout:
    1. back up NEWS_L1/NEWS_L2 and the rows about to change (backups/sys137_<source>_<stamp>/);
    2. delete those sitemaps' vectors from both indexes (atomic, generation-checked saves). Vectors
       go first: a kill then leaves rows without vectors, and a second run deletes them;
    3. one SQL transaction: delete their chunk rows.
  A second run finds nothing. The store check's `l2_over_max_tokens` and `l1_not_in_l2` count what
  is left.

      venv\Scripts\python.exe scripts\drop_oversized_queued_chunks.py --source VIVA --apply

  Exit: 0 done, 1 refused because an entity mention points at a target row, 2 refused (a crawl
  holds the run lock, or a crawl_log row is 'started').
"""
import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import CHUNK_MAX_TOKENS  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# The sitemaps without an article row whose chunks are stale (an L2 row over the limit) or half
# dropped (an L1 level, no L2 level), with what would go: every chunk row of the sitemap.
TARGETS_SQL = text("""
    SELECT s.sitemap_id, s.crawl_status,
           (SELECT count(*) FROM chunks c2 WHERE c2.sitemap_id = s.sitemap_id) AS chunk_rows,
           (SELECT count(*) FROM entity_mentions m JOIN chunks c3 ON c3.chunk_id = m.chunk_id
             WHERE c3.sitemap_id = s.sitemap_id) AS mentions
    FROM sitemaps s
    WHERE (CAST(:source AS text) IS NULL OR s.sources = :source)
      AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = s.sitemap_id)
      AND (EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = s.sitemap_id
                   AND c.chunk_level = 2 AND c.token_count > :m)
           OR (EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = s.sitemap_id AND c.chunk_level = 1)
               AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = s.sitemap_id AND c.chunk_level = 2)))
    ORDER BY s.sitemap_id
""")


def load(client, source):
    with client.get_session() as session:
        return session.execute(TARGETS_SQL, {"source": source, "m": CHUNK_MAX_TOKENS}).fetchall()


def report(targets):
    return ("%d queued sitemap(s) with stale chunks (an L2 row over %d words, or L1 without L2): "
            "%d chunk rows to drop, by status %s; %d entity mention(s)") % (
        len(targets), CHUNK_MAX_TOKENS, sum(t.chunk_rows for t in targets),
        dict(Counter(t.crawl_status for t in targets)), sum(t.mentions for t in targets))


def drop_rows(session, ids):
    """One transaction. Returns the chunk rows deleted."""
    n = session.execute(text("DELETE FROM chunks WHERE sitemap_id = ANY(:i)"), {"i": ids}).rowcount
    session.commit()
    return n


def apply(args, client=None) -> int:
    from newscrawler.tools.run_lock import RunLock, RunLockHeld
    client = client or SQLAlchemyClient()
    try:
        with RunLock(purpose="SYS-137 drop oversized queued chunks %s" % (args.source or "ALL")):
            return _apply_locked(args, client)
    except RunLockHeld as e:
        logger.error("refusing to write: %s", e)
        return 2


def _apply_locked(args, client) -> int:
    import repair_boilerplate_bodies as sys73
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        if sys73._crawl_running(session):
            logger.error("a crawl_log row is 'started' in the last 4 h; refusing to rewrite FAISS under a running crawl")
            return 2
    targets = load(client, args.source)
    print(report(targets))
    if any(t.mentions for t in targets):
        logger.error("entity mentions point at target rows: these are not queued chunks; nothing written")
        return 1
    ids = [t.sitemap_id for t in targets]
    summary = {"sitemaps": len(ids)}
    if ids:
        dirs = sys73._faiss_dirs()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        pairs = [(sid, None) for sid in ids]
        summary["backup"] = sys73.backup(client, args.source or "ALL", pairs, dirs, stamp, tag="sys137")
        summary["vectors_deleted"] = sum(sys73.delete_vectors(pairs, dirs).values())
        with client.get_session() as session:
            summary["chunk_rows_deleted"] = drop_rows(session, ids)
    logger.info("SUMMARY: %s", json.dumps(summary))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None, type=lambda s: s.upper(), help="One source only (default: all)")
    parser.add_argument("--apply", action="store_true", help="Write (default: the dry run)")
    args = parser.parse_args(argv)
    if args.apply:
        # OPS-26/DBT-43: this writes NEWS_L1/L2 (through repair_boilerplate_bodies' helpers); refuse at
        # the door while a crawl holds the run lock, before the database or the indexes are touched.
        from newscrawler.tools.run_lock import refused_by_run_lock
        if refused_by_run_lock(logger):
            return 2
        return apply(args)
    print(report(load(SQLAlchemyClient(), args.source)))
    print("\n(dry run: nothing was written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
