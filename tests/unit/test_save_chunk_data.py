"""
Bug A regression tests: save_chunk_data must return ALL represented sitemap_ids
(including sitemaps already embedded in a prior run, whose chunks come back with
embedding_id=None), and must NOT re-insert already-embedded chunks into SQL.
"""
import pytest
from unittest.mock import MagicMock

from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
    DataFlowRepositoryImpl,
)


def make_chunk(sitemap_id, embedding_id=None):
    return ChunkDTO(
        sitemap_id=sitemap_id,
        chunk_level=1,
        chunk_index=0,
        chunk_total=1,
        is_first_chunk=True,
        is_last_chunk=True,
        text_content="text",
        token_count=1,
        title="t",
        source="WARTAEKONOMI",
        category="finansial",
        posted_at=20260101,
        embedding_id=embedding_id,
    )


def build_repo(faiss_return):
    """Build a DataFlowRepositoryImpl with its heavy datasources mocked."""
    repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
    repo.chunk_faiss_datasource = MagicMock()
    repo.chunk_faiss_datasource.save.return_value = faiss_return
    repo.sql_alchemy_chunk_datasource = MagicMock()
    return repo


class TestSaveChunkData:
    def test_already_embedded_sitemap_still_returned(self):
        """A sitemap already in FAISS (embedding_id=None) must still be returned so its
        article gets saved -- this was Bug A (it returned empty -> article never saved)."""
        already = make_chunk(sitemap_id=42, embedding_id=None)
        repo = build_repo([already])

        result = repo.save_chunk_data([make_chunk(42)])

        assert 42 in result, "Bug A: already-embedded sitemap_id must be returned"

    def test_already_embedded_chunks_not_reinserted_to_sql(self):
        already = make_chunk(sitemap_id=42, embedding_id=None)
        repo = build_repo([already])

        repo.save_chunk_data([make_chunk(42)])

        # save_chunks should be called with an empty list (nothing new to persist)
        repo.sql_alchemy_chunk_datasource.save_chunks.assert_called_once()
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert inserted == [], "already-embedded chunks must not be re-inserted to SQL"

    def test_newly_embedded_chunks_inserted_and_returned(self):
        fresh = make_chunk(sitemap_id=7, embedding_id="uuid-123")
        repo = build_repo([fresh])

        result = repo.save_chunk_data([make_chunk(7)])

        assert 7 in result
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert len(inserted) == 1, "newly-embedded chunk must be inserted to SQL"

    def test_mixed_new_and_already_embedded(self):
        fresh = make_chunk(sitemap_id=1, embedding_id="uuid-1")
        already = make_chunk(sitemap_id=2, embedding_id=None)
        repo = build_repo([fresh, already])

        result = repo.save_chunk_data([make_chunk(1), make_chunk(2)])

        assert set(result) == {1, 2}, "both sitemap_ids must be returned"
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert [c.sitemap_id for c in inserted] == [1], "only the new chunk is inserted"
