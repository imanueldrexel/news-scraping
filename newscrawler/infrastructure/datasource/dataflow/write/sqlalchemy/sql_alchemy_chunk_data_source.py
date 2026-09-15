import logging
from typing import List

from newscrawler.infrastructure.datasource.dataflow.model.chunk_model import ChunkModel
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import ChunksTable

logger = logging.getLogger(__name__)


class SQLAlchemyChunkDataSource:
    def __init__(self, sql_alchemy_client):
        self.sql_alchemy_client = sql_alchemy_client

    def save_chunks(self, chunks: List[ChunkModel]) -> None:
        if not chunks:
            return
        with self.sql_alchemy_client.get_session() as session:
            rows = [ChunksTable(chunk) for chunk in chunks]
            session.add_all(rows)
            session.commit()
        logger.info(f"Saved {len(chunks)} chunk records to PostgreSQL")
