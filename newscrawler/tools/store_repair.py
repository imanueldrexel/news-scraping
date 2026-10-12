"""DBT-67 (#325, ADR-015): the steps every store-repair script shares.

A repair that rewrites stored chunks runs, holding the run lock (`run_lock.RunLock`):
  1. refuse while a crawl runs (`crawl_running`) and when its deadline is too close (`too_close`,
     the deadline resolved once by `parse_until`, SYS-111);
  2. back up NEWS_L1/NEWS_L2 and the rows about to change (`backup`);
  3. delete the targets' vectors (`delete_vectors`: atomic, generation-checked saves);
  4. its own SQL, in one transaction;
  5. re-chunk and re-embed the articles left without chunks, one FAISS flush per block (`rechunk`);
  6. recompute the counters of entities that lost mentions (`recount_entity_counts`, SYS-20).

The scripts (repair_boilerplate_bodies, rechunk_stale_chunks, settle_out_of_scope_links,
drop_oversized_queued_chunks, backfill_orphan_chunks) keep their CLI, dry run, target selection and
report, and import these steps from here; a script never imports another script for them. A value a
test redirects (`BACKUP_DIR`) is read here as a module attribute, so redirecting it once covers every
caller.
"""
import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)   # the scripts configure the root handler at WARNING and their own loggers at INFO

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")
MIN_FREE_GB_FOR_BACKUP = 8      # the FAISS directories are ~2.1 GB and the backup copies them
DEFAULT_BLOCK = 1000            # articles per FAISS flush while re-chunking
# SYS-111 (#287): a write path refuses to start its destructive step with less time than this
# before its deadline; it would delete everything it targets and then stop at once.
MIN_RUN_MINUTES = 15

# The articles that have an `articles` row but miss chunks at either level (SYS-17/SYS-25).
ORPHAN_ARTICLES_SQL = text("""
    SELECT a.sitemap_id, a.extracted_text, a.writer,
           s.headline, s.sources, s.category, s.posted_at
    FROM articles a
    JOIN sitemaps s ON s.sitemap_id = a.sitemap_id
    WHERE (
        NOT EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = a.sitemap_id AND c.chunk_level = 1)
        OR NOT EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = a.sitemap_id AND c.chunk_level = 2)
      )
      AND (:website IS NULL OR s.sources = :website)
    ORDER BY a.sitemap_id
""")

# The entities whose stored counters disagree with their mentions, with both (SYS-20).
ENTITY_DRIFT_SQL = text("""
    SELECT e.entity_id, e.name, e.mention_count, e.first_seen_at, e.last_seen_at,
           COALESCE(m.n, 0) AS true_count, m.lo AS true_first, m.hi AS true_last
    FROM entities e
    LEFT JOIN (SELECT entity_id, COUNT(*) AS n, MIN(posted_at) AS lo, MAX(posted_at) AS hi
               FROM entity_mentions GROUP BY 1) m USING (entity_id)
    WHERE e.mention_count <> COALESCE(m.n, 0)
       OR e.first_seen_at IS DISTINCT FROM m.lo
       OR e.last_seen_at IS DISTINCT FROM m.hi
    ORDER BY e.entity_id
""")

ENTITY_FIX_SQL = text("""
    UPDATE entities e SET
        mention_count = (SELECT COUNT(*) FROM entity_mentions m WHERE m.entity_id = e.entity_id),
        first_seen_at = (SELECT MIN(posted_at) FROM entity_mentions m WHERE m.entity_id = e.entity_id),
        last_seen_at  = (SELECT MAX(posted_at) FROM entity_mentions m WHERE m.entity_id = e.entity_id),
        updated_at    = NOW()
    WHERE e.entity_id = ANY(:ids)
""")


# ── Refusals ─────────────────────────────────────────────────────────────────

def crawl_running(session):
    """The `started` crawl rows of the last 4 hours: a manual crawl takes no run lock."""
    return session.execute(text(
        "SELECT count(*) FROM crawl_log WHERE status = 'started' AND task IN ('sitemap', 'full_text', 'all') "
        "AND started_at > NOW() - INTERVAL '4 hours'")).scalar()


def parse_until(value, now=None):
    """'HH:MM' (local time) -> the next such time: today if still ahead, otherwise tomorrow; None
    without a value. SYS-111 (#287): it used to mean today even when passed, so an evening run
    with --until 06:15 stopped at once, after its deletes. Resolve it once per run."""
    if not value:
        return None
    hour, minute = (int(x) for x in value.split(":"))
    now = now or datetime.now()
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return deadline if deadline > now else deadline + timedelta(days=1)


def too_close(deadline, now=None) -> bool:
    """SYS-111: True when a run with this deadline must not start its destructive step."""
    return deadline is not None and deadline - (now or datetime.now()) < timedelta(minutes=MIN_RUN_MINUTES)


# ── FAISS ────────────────────────────────────────────────────────────────────

def faiss_dirs():
    """(NEWS_L1, NEWS_L2) as the datasource resolves them, so a test that redirects them is obeyed."""
    import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as cfd
    return cfd.VECTOR_DB_NAME_L1, cfd.VECTOR_DB_NAME_L2


class NoEmbeddings:
    """FAISS.load_local needs an embeddings object; a repair that only deletes never embeds."""
    def embed_documents(self, texts):
        raise RuntimeError("repair must not embed")

    def embed_query(self, text_):
        raise RuntimeError("repair must not embed")


def vector_ids_for(docstore_dict, sitemap_ids):
    """Pure. Docstore ids of every vector belonging to one of `sitemap_ids`."""
    wanted = set(sitemap_ids)
    return [doc_id for doc_id, doc in docstore_dict.items()
            if doc.metadata.get("sitemap_id") is not None and int(doc.metadata["sitemap_id"]) in wanted]


def delete_vectors(targets, dirs):
    """Remove the targets' vectors from NEWS_L1/NEWS_L2: atomic save, generation-checked (SYS-53/56).
    `targets`: (sitemap_id, anything) pairs. They must go before the new chunks are embedded: the reuse
    path (SYS-17) finds an existing vector by (sitemap, level, index) and would link the new rows to
    the old ones."""
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    ids = [sid for sid, _ in targets]
    deleted = {}
    for db in dirs:
        store = load_index(db, NoEmbeddings())
        doomed = vector_ids_for(store.docstore._dict, ids)
        if doomed:
            store.delete(doomed)
            ChunkFAISSDatasource._atomic_save_local(store, db)
        deleted[db] = len(doomed)
        logger.info("%s: deleted %d vector(s), saved", db, len(doomed))
    return deleted


# ── Backup ───────────────────────────────────────────────────────────────────

def require_free_disk(path):
    """Raise unless the disk holding `path` (or the repository, before `path` exists) has
    MIN_FREE_GB_FOR_BACKUP free."""
    free_gb = shutil.disk_usage(path if os.path.isdir(path) else REPO_ROOT).free / 1e9
    if free_gb < MIN_FREE_GB_FOR_BACKUP:
        raise RuntimeError("only %.1f GB free; the backup needs about %d" % (free_gb, MIN_FREE_GB_FOR_BACKUP))


def backup(client, source, targets, dirs, stamp, tag="sys73"):
    """FAISS directories and the rows about to change, under BACKUP_DIR/<tag>_<source>_<stamp>/.
    `targets`: (sitemap_id, anything) pairs."""
    require_free_disk(BACKUP_DIR)
    path = os.path.join(BACKUP_DIR, "%s_%s_%s" % (tag, source, stamp))
    for db in dirs:
        shutil.copytree(db, os.path.join(path, os.path.basename(db.rstrip("/\\"))))
    ids = [sid for sid, _ in targets]
    with client.get_session() as session:
        dump = {
            "articles": [dict(r._mapping) for r in session.execute(text(
                "SELECT * FROM articles WHERE sitemap_id = ANY(:i)"), {"i": ids})],
            "chunks": [dict(r._mapping) for r in session.execute(text(
                "SELECT chunk_id, sitemap_id, article_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                "is_last_chunk, text_content, token_count, embedding_id, chunk_status FROM chunks "
                "WHERE sitemap_id = ANY(:i)"), {"i": ids})],
            "entity_mentions": [dict(r._mapping) for r in session.execute(text(
                "SELECT * FROM entity_mentions WHERE sitemap_id = ANY(:i)"), {"i": ids})],
        }
    with open(os.path.join(path, "rows.json"), "w", encoding="utf-8") as f:
        json.dump(dump, f, default=str)
    logger.info("backup: %s (FAISS + %d article, %d chunk, %d mention rows)", path, len(dump["articles"]),
                len(dump["chunks"]), len(dump["entity_mentions"]))
    return path


# ── Re-chunk ─────────────────────────────────────────────────────────────────

def rechunk_articles(repo, chunker, rows, group_size=1):
    """Re-chunk and save `rows` (articles with an `articles` row but missing chunks) from their
    stored text. Returns (repaired, empty, failed). `rechunk` wraps it in `deferred_embeddings` so a
    block of articles costs one FAISS save instead of one per article.

    `group_size`: articles per `save_chunk_data` call, so their chunks are embedded in one batch
    (SYS-109: the whole corpus at ~8 windows an article). A group that fails is saved again
    article by article, so one bad article fails alone."""
    from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
    from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
    repaired, empty, failed = 0, 0, 0
    group = []

    def save_group():
        nonlocal repaired, failed
        if not group:
            return
        try:
            repo.save_chunk_data([c for _, chunks in group for c in chunks])
            repaired += len(group)
        except Exception as e:
            if len(group) == 1:
                logger.error("sitemap_id %d: failed to save chunks: %s", group[0][0], e)
                failed += 1
            else:
                logger.warning("a group of %d articles failed to save (%s); saving them one by one", len(group), e)
                for sitemap_id, chunks in group:
                    try:
                        repo.save_chunk_data(chunks)
                        repaired += 1
                    except Exception as e1:
                        logger.error("sitemap_id %d: failed to save chunks: %s", sitemap_id, e1)
                        failed += 1
        group.clear()

    for row in rows:
        # SYS-18: extracted_text is prose joined with "\n\n" at the write boundary
        # (sql_alchemy_articles_data_source.save_newsdetails); split it the same way.
        paragraphs = [p for p in (row.extracted_text or "").split("\n\n") if p.strip()]
        if not paragraphs:
            logger.warning("sitemap_id %d: extracted_text is empty, skipping", row.sitemap_id)
            empty += 1
            continue

        if not row.posted_at:
            logger.warning("sitemap_id %d: no posted_at, skipping", row.sitemap_id)
            empty += 1
            continue
        posted_at_dt = datetime.strptime(str(row.posted_at), "%Y%m%d")

        news = NewsDetailsDTO(
            sitemap_id=row.sitemap_id,
            extracted_text=paragraphs,
            reporter=row.writer,
            meta_data={"title": row.headline, "posted_at": row.posted_at},
        )
        sitemap = SitemapDTO(
            headline=row.headline, link="", sources=row.sources, category=row.category,
            timestamp=posted_at_dt, sitemap_id=row.sitemap_id,
        )
        chunks = chunker.chunk(news, sitemap)
        if not chunks:
            logger.warning("sitemap_id %d: chunker produced 0 chunks, skipping", row.sitemap_id)
            empty += 1
            continue

        group.append((row.sitemap_id, chunks))
        if len(group) >= group_size:
            save_group()
    save_group()
    return repaired, empty, failed


def rechunk(client, source, block, deadline, make_repo=None, now=datetime.now, group_size=1):
    """Re-chunk and re-embed this source's articles that have no chunks, `block` articles per FAISS
    flush (`deferred_embeddings`: without it every article would rewrite the 2 GB index). Stops starting
    blocks at the deadline. Returns (repaired, empty, failed, left)."""
    from newscrawler.core.chunker import HierarchicalChunker
    with client.get_session() as session:
        orphans = session.execute(ORPHAN_ARTICLES_SQL, {"website": source}).fetchall()
    logger.info("%s: %d article(s) to re-chunk", source, len(orphans))
    if not orphans:
        return 0, 0, 0, 0
    if make_repo is None:
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl
        make_repo = DataFlowRepositoryImpl
    repo = make_repo(client)
    chunker = HierarchicalChunker()
    repaired = empty = failed = 0
    for start in range(0, len(orphans), block):
        if deadline is not None and now() >= deadline:
            logger.warning("deadline %s reached: %d article(s) not re-chunked yet (run again with --rechunk-only)",
                           deadline.strftime("%H:%M"), len(orphans) - start)
            return repaired, empty, failed, len(orphans) - start
        with repo.deferred_embeddings(source):
            r, e, f = rechunk_articles(repo, chunker, orphans[start:start + block], group_size=group_size)
        repaired, empty, failed = repaired + r, empty + e, failed + f
        logger.info("%s: %d/%d re-chunked (%d empty, %d failed)", source, start + len(orphans[start:start + block]),
                    len(orphans), empty, failed)
    return repaired, empty, failed, 0


# ── Entity counters ──────────────────────────────────────────────────────────

def recount_entity_counts(client, dry_run=False) -> int:
    """SYS-20: recompute the counters of every entity whose stored counts disagree with its mentions,
    after backing the drifted rows up. Exit: 0 nothing left drifting (or a dry run), 1 drift left."""
    with client.get_session() as session:
        rows = session.execute(ENTITY_DRIFT_SQL).fetchall()
        if not rows:
            logger.info("No drift: every entity's counters match entity_mentions.")
            return 0
        count_drift = sum(r.mention_count - r.true_count for r in rows)
        logger.info("%d entit(y/ies) drift; net mention_count drift %+d; e.g. %s", len(rows), count_drift,
                    "; ".join(f"{r.name!r} {r.mention_count}->{r.true_count}" for r in rows[:5]))
        if dry_run:
            logger.info("[dry-run] Would recompute %d entit(y/ies).", len(rows))
            return 0
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, f"sys20_entity_counts_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([dict(r._mapping) for r in rows], f, default=str, indent=2)
        logger.info("Backed up %d row(s) to %s", len(rows), path)
        session.execute(ENTITY_FIX_SQL, {"ids": [r.entity_id for r in rows]})
        session.commit()
        left = session.execute(ENTITY_DRIFT_SQL).fetchall()
    logger.info("Recomputed %d entit(y/ies); drift left: %d", len(rows), len(left))
    return 0 if not left else 1
