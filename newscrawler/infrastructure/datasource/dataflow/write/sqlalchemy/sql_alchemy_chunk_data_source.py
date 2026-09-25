import logging
from datetime import datetime
from typing import List, Set, Tuple

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from newscrawler.infrastructure.datasource.dataflow.model.chunk_model import ChunkModel
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import ChunksTable

logger = logging.getLogger(__name__)


class SQLAlchemyChunkDataSource:
    def __init__(self, sql_alchemy_client):
        self.sql_alchemy_client = sql_alchemy_client

    def get_existing_sitemap_level_pairs(self, sitemap_ids) -> Set[Tuple[int, int]]:
        """SYS-17: the source of truth for "has this sitemap's chunks already been
        saved" -- FAISS membership alone must not answer this question, since FAISS
        is persisted before the SQL commit and a failed commit then leaves FAISS
        holding vectors for a sitemap that has zero rows here, permanently (every
        later attempt would see the FAISS vectors and skip the SQL insert again).

        SYS-25: keyed on (sitemap_id, chunk_level), not sitemap_id alone -- a
        sitemap can have one level's chunks saved and the other missing (a partial
        prior write), and sitemap-level dedup treated any existing row as "fully
        saved," permanently dropping the missing level from every future call.
        Same class of bug as SYS-17, one level down.

        DBT-23 (#74): a level counts as saved only when EVERY row it has carries
        an embedding_id. A row with embedding_id NULL (the DBT-17 shape:
        chunk_status='pending_embedding', a write that stopped between the
        SQL insert and the vector) used to be invisible -- the level looked
        saved, nothing re-embedded it, and only a repair script could see it.
        Now the level is offered again and save_chunks() repairs the row in
        place (upsert on the DBT-09 unique key)."""
        if not sitemap_ids:
            return set()
        with self.sql_alchemy_client.get_session() as session:
            rows = session.execute(
                text(f"SELECT {ChunksTable.sitemap_id.name}, {ChunksTable.chunk_level.name} "
                     f"FROM {ChunksTable.__tablename__} "
                     f"WHERE {ChunksTable.sitemap_id.name} = ANY(:ids) "
                     f"GROUP BY {ChunksTable.sitemap_id.name}, {ChunksTable.chunk_level.name} "
                     f"HAVING COUNT(*) FILTER (WHERE {ChunksTable.embedding_id.name} IS NULL) = 0"),
                {"ids": list(sitemap_ids)},
            ).fetchall()
        return {(row[0], row[1]) for row in rows}

    def count_unembedded(self) -> int:
        """DBT-23: rows the pipeline will repair on the sitemap's next save;
        OPERATIONS.md's health query, callable."""
        with self.sql_alchemy_client.get_session() as session:
            return session.execute(
                text(f"SELECT COUNT(*) FROM {ChunksTable.__tablename__} WHERE {ChunksTable.embedding_id.name} IS NULL")
            ).scalar()

    def load_unembedded_chunks(self, website=None):
        """DBT-10: chunk rows with no embedding_id, as ChunkDTOs ready to embed
        (the DBT-17 repair's query, shared with the deferred-save recovery)."""
        from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
        with self.sql_alchemy_client.get_session() as session:
            rows = session.execute(text(
                "SELECT c.chunk_id, c.sitemap_id, c.chunk_level, c.chunk_index, c.chunk_total, "
                "c.is_first_chunk, c.is_last_chunk, c.text_content, c.token_count, "
                "s.headline, s.sources, s.category, s.posted_at "
                "FROM chunks c JOIN sitemaps s ON s.sitemap_id = c.sitemap_id "
                "WHERE c.embedding_id IS NULL AND (:website IS NULL OR s.sources = :website) "
                "ORDER BY c.chunk_id"), {"website": website}).fetchall()
        return [ChunkDTO(sitemap_id=r.sitemap_id, chunk_level=r.chunk_level, chunk_index=r.chunk_index,
                         chunk_total=r.chunk_total, is_first_chunk=r.is_first_chunk,
                         is_last_chunk=r.is_last_chunk, text_content=r.text_content,
                         token_count=r.token_count, title=r.headline, source=r.sources,
                         category=r.category, posted_at=r.posted_at, chunk_id=r.chunk_id)
                for r in rows]

    def set_embedding_ids(self, ids_by_key) -> int:
        """DBT-10: after a deferred FAISS flush, give each chunk row its vector's id
        and mark it embedded. Keyed by the DBT-09 unique key; only rows still
        unembedded are touched. Returns rows updated."""
        if not ids_by_key:
            return 0
        params = [{"sid": k[0], "lvl": k[1], "idx": k[2], "eid": v} for k, v in ids_by_key.items()]
        with self.sql_alchemy_client.get_session() as session:
            n = 0
            for p in params:
                n += session.execute(text(
                    "UPDATE chunks SET embedding_id = :eid, chunk_status = 'embedded' "
                    "WHERE sitemap_id = :sid AND chunk_level = :lvl AND chunk_index = :idx "
                    "AND embedding_id IS NULL"), p).rowcount
            session.commit()
        return n

    def save_chunks(self, chunks: List[ChunkModel]) -> None:
        """Insert, or -- DBT-23 (#74) -- on the DBT-09 unique key
        (sitemap_id, chunk_level, chunk_index) update the row in place with the
        new embedding_id, chunk_status, text and counts. A NULL-embedding row is
        thereby repaired by the normal save path instead of duplicated or
        skipped."""
        if not chunks:
            return
        now = datetime.utcnow()
        values = [
            {
                "sitemap_id": c.sitemap_id, "chunk_level": c.chunk_level, "chunk_index": c.chunk_index,
                "chunk_total": c.chunk_total, "is_first_chunk": bool(c.is_first_chunk),
                "is_last_chunk": bool(c.is_last_chunk), "text_content": c.text_content,
                "token_count": c.token_count, "embedding_id": c.embedding_id, "chunk_status": c.chunk_status,
                "created_at": now,
            }
            for c in chunks
        ]
        stmt = pg_insert(ChunksTable).values(values)
        stmt = stmt.on_conflict_do_update(
            # scripts/migrate_chunks_unique.sql creates a unique INDEX (not a named
            # constraint), so the conflict target is the column list.
            index_elements=["sitemap_id", "chunk_level", "chunk_index"],
            set_={
                "embedding_id": stmt.excluded.embedding_id,
                "chunk_status": stmt.excluded.chunk_status,
                "text_content": stmt.excluded.text_content,
                "token_count": stmt.excluded.token_count,
                "chunk_total": stmt.excluded.chunk_total,
                "is_first_chunk": stmt.excluded.is_first_chunk,
                "is_last_chunk": stmt.excluded.is_last_chunk,
            },
        )
        with self.sql_alchemy_client.get_session() as session:
            session.execute(stmt)
            session.commit()
        logger.info(f"Saved {len(chunks)} chunk records to PostgreSQL")
