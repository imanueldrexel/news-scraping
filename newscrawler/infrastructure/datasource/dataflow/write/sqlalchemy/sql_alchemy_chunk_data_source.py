import logging
from typing import List, Set, Tuple

from sqlalchemy import text

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
        Same class of bug as SYS-17, one level down."""
        if not sitemap_ids:
            return set()
        with self.sql_alchemy_client.get_session() as session:
            rows = session.execute(
                text(f"SELECT DISTINCT {ChunksTable.sitemap_id.name}, {ChunksTable.chunk_level.name} "
                     f"FROM {ChunksTable.__tablename__} "
                     f"WHERE {ChunksTable.sitemap_id.name} = ANY(:ids)"),
                {"ids": list(sitemap_ids)},
            ).fetchall()
        return {(row[0], row[1]) for row in rows}

    def save_chunks(self, chunks: List[ChunkModel]) -> None:
        if not chunks:
            return
        with self.sql_alchemy_client.get_session() as session:
            rows = [ChunksTable(chunk) for chunk in chunks]
            session.add_all(rows)
            session.commit()
        logger.info(f"Saved {len(chunks)} chunk records to PostgreSQL")
