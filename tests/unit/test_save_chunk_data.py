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

SYS-25: the dedup key is (sitemap_id, chunk_level), not sitemap_id alone -- see
TestSaveChunkDataDedupsPerLevelNotPerSitemap below.
"""
from unittest.mock import MagicMock

from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
    DataFlowRepositoryImpl,
)


def make_chunk(sitemap_id, chunk_level=1, embedding_id=None):
    return ChunkDTO(
        sitemap_id=sitemap_id,
        chunk_level=chunk_level,
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


def build_repo(existing_pairs=frozenset(), faiss_return=None):
    """Build a DataFlowRepositoryImpl with its heavy datasources mocked.
    existing_pairs: set of (sitemap_id, chunk_level) already present in `chunks`.
    """
    repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
    repo.chunk_faiss_datasource = MagicMock()
    if faiss_return is not None:
        repo.chunk_faiss_datasource.save.return_value = faiss_return
    repo.sql_alchemy_chunk_datasource = MagicMock()
    repo.sql_alchemy_chunk_datasource.get_existing_sitemap_level_pairs.return_value = set(existing_pairs)
    return repo


class TestSaveChunkDataDedupsOnSqlNotFaiss:
    def test_sitemap_already_in_chunks_table_is_skipped_entirely(self):
        repo = build_repo(existing_pairs={(42, 1)})

        result = repo.save_chunk_data([make_chunk(42)])

        assert 42 in result, "Bug A: must still be returned so the article gets saved"
        repo.chunk_faiss_datasource.save.assert_not_called()
        repo.sql_alchemy_chunk_datasource.save_chunks.assert_not_called()

    def test_faiss_vectors_with_no_chunks_row_are_still_inserted(self):
        """The actual production bug (SYS-17): a sitemap already embedded in FAISS
        but with zero chunks rows must still get its SQL row -- FAISS membership
        alone must never suppress the insert."""
        recovered = make_chunk(sitemap_id=7, embedding_id="uuid-recovered-from-faiss")
        repo = build_repo(existing_pairs=set(), faiss_return=[recovered])

        result = repo.save_chunk_data([make_chunk(7)])

        assert 7 in result
        repo.chunk_faiss_datasource.save.assert_called_once()
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert len(inserted) == 1, "must be inserted even though FAISS already had the vector"

    def test_newly_embedded_chunks_inserted_and_returned(self):
        fresh = make_chunk(sitemap_id=7, embedding_id="uuid-123")
        repo = build_repo(existing_pairs=set(), faiss_return=[fresh])

        result = repo.save_chunk_data([make_chunk(7)])

        assert 7 in result
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert len(inserted) == 1

    def test_mixed_batch_only_the_not_yet_in_sql_sitemap_reaches_faiss_and_sql(self):
        fresh = make_chunk(sitemap_id=1, embedding_id="uuid-1")
        repo = build_repo(existing_pairs={(2, 1)}, faiss_return=[fresh])

        result = repo.save_chunk_data([make_chunk(1), make_chunk(2)])

        assert set(result) == {1, 2}, "both sitemap_ids must be returned"
        faiss_call_arg = repo.chunk_faiss_datasource.save.call_args[0][0]
        assert [c.sitemap_id for c in faiss_call_arg] == [1], "sitemap 2 must not be re-embedded"
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert [c.sitemap_id for c in inserted] == [1], "sitemap 2 must not be re-inserted"

    def test_empty_input_returns_empty_without_any_calls(self):
        repo = build_repo()

        assert repo.save_chunk_data([]) == []
        repo.sql_alchemy_chunk_datasource.get_existing_sitemap_level_pairs.assert_not_called()

    def test_all_sitemaps_already_in_sql_makes_no_faiss_or_sql_calls(self):
        repo = build_repo(existing_pairs={(1, 1), (2, 1)})

        result = repo.save_chunk_data([make_chunk(1), make_chunk(2)])

        assert set(result) == {1, 2}
        repo.chunk_faiss_datasource.save.assert_not_called()
        repo.sql_alchemy_chunk_datasource.save_chunks.assert_not_called()


class TestSaveChunkDataDedupsPerLevelNotPerSitemap:
    """SYS-25: a sitemap can have chunks saved at one level and missing the other
    (a partial prior write). Sitemap-level dedup treated any existing row as "fully
    saved" and permanently dropped the missing level -- the same class of bug SYS-17
    fixed for FAISS-vs-SQL, one level down."""

    def test_sitemap_with_only_l2_saved_still_inserts_l1_on_retry(self):
        l1 = make_chunk(sitemap_id=99, chunk_level=1, embedding_id="uuid-l1")
        repo = build_repo(existing_pairs={(99, 2)}, faiss_return=[l1])

        result = repo.save_chunk_data([make_chunk(99, chunk_level=1)])

        assert 99 in result
        repo.chunk_faiss_datasource.save.assert_called_once()
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert len(inserted) == 1, "the missing L1 chunk must still be inserted"

    def test_sitemap_with_only_l1_saved_still_inserts_l2_on_retry(self):
        l2 = make_chunk(sitemap_id=100, chunk_level=2, embedding_id="uuid-l2")
        repo = build_repo(existing_pairs={(100, 1)}, faiss_return=[l2])

        result = repo.save_chunk_data([make_chunk(100, chunk_level=2)])

        assert 100 in result
        inserted = repo.sql_alchemy_chunk_datasource.save_chunks.call_args[0][0]
        assert len(inserted) == 1, "the missing L2 chunk must still be inserted"

    def test_mixed_levels_only_the_missing_level_reaches_faiss_and_sql(self):
        """A batch carrying both an L1 and an L2 chunk for the same sitemap, where
        only L1 is already saved, must process just the L2 chunk."""
        l2 = make_chunk(sitemap_id=55, chunk_level=2, embedding_id="uuid-l2")
        repo = build_repo(existing_pairs={(55, 1)}, faiss_return=[l2])

        result = repo.save_chunk_data([
            make_chunk(55, chunk_level=1), make_chunk(55, chunk_level=2),
        ])

        assert 55 in result
        faiss_call_arg = repo.chunk_faiss_datasource.save.call_args[0][0]
        assert [c.chunk_level for c in faiss_call_arg] == [2], "L1 must not be re-embedded"

    def test_both_levels_already_saved_skips_entirely(self):
        repo = build_repo(existing_pairs={(101, 1), (101, 2)})

        result = repo.save_chunk_data([
            make_chunk(101, chunk_level=1), make_chunk(101, chunk_level=2),
        ])

        assert 101 in result
        repo.chunk_faiss_datasource.save.assert_not_called()
        repo.sql_alchemy_chunk_datasource.save_chunks.assert_not_called()
