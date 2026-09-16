"""
Bug A / SYS-17: save_chunk_data must return ALL represented sitemap_ids (so the
caller still saves the article even for a sitemap whose chunks were already fully
persisted -- Bug A), and must dedup against the chunks table, not FAISS membership.

FAISS is written to disk before the SQL commit; treating FAISS presence as "already
saved" (the pre-SYS-17 design) meant a sitemap whose SQL insert failed (or was
skipped) after its vectors were already embedded got permanently stuck -- every
later attempt saw the FAISS vectors and skipped the SQL insert again, forever. This
was production's actual symptom: 152 WARTAEKONOMI articles rows with FAISS vectors
in both indexes and zero chunks rows, unrepairable by re-running the pipeline.
"""
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


def build_repo(existing_sql_sitemap_ids=frozenset(), faiss_return=None):
    """Build a DataFlowRepositoryImpl with its heavy datasources mocked."""
    repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
    repo.chunk_faiss_datasource = MagicMock()
    if faiss_return is not None:
        repo.chunk_faiss_datasource.save.return_value = faiss_return
    repo.sql_alchemy_chunk_datasource = MagicMock()
    repo.sql_alchemy_chunk_datasource.get_existing_sitemap_ids.return_value = set(existing_sql_sitemap_ids)
    return repo


class TestSaveChunkDataDedupsOnSqlNotFaiss:
    def test_sitemap_already_in_chunks_table_is_skipped_entirely(self):
        repo = build_repo(existing_sql_sitemap_ids={42})

        result = repo.save_chunk_data([make_chunk(42)])

        assert 42 in result, "Bug A: must still be returned so the article gets saved"
        repo.chunk_faiss_datasource.save.assert_not_called()
        repo.sql_alchemy_chunk_datasource.save_chunks.assert_not_called()

    def test_faiss_vectors_with_no_chunks_row_are_still_inserted(self):
        """The actual production bug (SYS-17): a sitemap already embedded in FAISS
        but with zero chunks rows must still get its SQL row -- FAISS membership
        alone must never suppress the insert."""
        recovered = make_chunk(sitemap_id=7, embedding_id="uuid-recovered-from-faiss")
        repo = build_repo(existing_sql_sitemap_ids=set(), faiss_return=[recovered])

        result = repo.save_chunk_data([make_chunk(7)])

        assert 7 in result
        repo.chunk_faiss_datasource.save.assert_called_once()
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert len(inserted) == 1, "must be inserted even though FAISS already had the vector"

    def test_newly_embedded_chunks_inserted_and_returned(self):
        fresh = make_chunk(sitemap_id=7, embedding_id="uuid-123")
        repo = build_repo(existing_sql_sitemap_ids=set(), faiss_return=[fresh])

        result = repo.save_chunk_data([make_chunk(7)])

        assert 7 in result
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert len(inserted) == 1

    def test_mixed_batch_only_the_not_yet_in_sql_sitemap_reaches_faiss_and_sql(self):
        fresh = make_chunk(sitemap_id=1, embedding_id="uuid-1")
        repo = build_repo(existing_sql_sitemap_ids={2}, faiss_return=[fresh])

        result = repo.save_chunk_data([make_chunk(1), make_chunk(2)])

        assert set(result) == {1, 2}, "both sitemap_ids must be returned"
        faiss_call_arg = repo.chunk_faiss_datasource.save.call_args[0][0]
        assert [c.sitemap_id for c in faiss_call_arg] == [1], "sitemap 2 must not be re-embedded"
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert [c.sitemap_id for c in inserted] == [1], "sitemap 2 must not be re-inserted"

    def test_empty_input_returns_empty_without_any_calls(self):
        repo = build_repo()

        assert repo.save_chunk_data([]) == []
        repo.sql_alchemy_chunk_datasource.get_existing_sitemap_ids.assert_not_called()

    def test_all_sitemaps_already_in_sql_makes_no_faiss_or_sql_calls(self):
        repo = build_repo(existing_sql_sitemap_ids={1, 2})

        result = repo.save_chunk_data([make_chunk(1), make_chunk(2)])

        assert set(result) == {1, 2}
        repo.chunk_faiss_datasource.save.assert_not_called()
        repo.sql_alchemy_chunk_datasource.save_chunks.assert_not_called()
