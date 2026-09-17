"""
SYS-17: ChunkFAISSDatasource must recover the *real* embedding_id for a chunk
already present in the index (keyed on sitemap_id + chunk_level + chunk_index, the
docstore key it was originally added under) instead of returning it with
embedding_id=None. This is what makes SQL-based dedup (DataFlowRepositoryImpl.
save_chunk_data) self-healing: a sitemap whose SQL insert failed after FAISS already
had its vectors gets retried, finds those exact vectors, and reuses their real ids
instead of creating duplicates or leaving the SQL row unfillable.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
    ChunkFAISSDatasource,
)


def _doc(sitemap_id, chunk_level, chunk_index):
    return SimpleNamespace(
        page_content="x",
        metadata={"sitemap_id": sitemap_id, "chunk_level": chunk_level, "chunk_index": chunk_index},
    )


def _chunk(sitemap_id, chunk_level=1, chunk_index=0):
    return ChunkDTO(
        sitemap_id=sitemap_id, chunk_level=chunk_level, chunk_index=chunk_index,
        chunk_total=1, is_first_chunk=True, is_last_chunk=True,
        text_content="text", token_count=1, title="t", source="S",
        category="finansial", posted_at=20260101,
    )


def _vs_with_docstore(docstore_dict):
    vs = MagicMock()
    vs.docstore._dict = docstore_dict
    return vs


def _ds():
    return ChunkFAISSDatasource.__new__(ChunkFAISSDatasource)


class TestGetExistingEmbeddingIds:
    def test_maps_sitemap_level_index_to_docstore_key(self):
        vs = _vs_with_docstore({"real-uuid-1": _doc(42, 1, 0), "real-uuid-2": _doc(42, 2, 0)})
        result = ChunkFAISSDatasource._get_existing_embedding_ids(vs)
        assert result == {(42, 1, 0): "real-uuid-1", (42, 2, 0): "real-uuid-2"}

    def test_docs_missing_required_metadata_are_skipped(self):
        vs = _vs_with_docstore({"uuid": SimpleNamespace(metadata={"other": "data"})})
        assert ChunkFAISSDatasource._get_existing_embedding_ids(vs) == {}


class TestEmbedBatchRecoversRealEmbeddingId:
    def test_chunk_already_in_index_gets_its_real_embedding_id_not_none(self):
        ds = _ds()
        vs = _vs_with_docstore({"real-uuid": _doc(7, 1, 0)})

        result = ds._embed_batch([_chunk(7)], vs, "NEWS_L1")

        assert len(result) == 1
        assert result[0].embedding_id == "real-uuid"
        assert result[0].chunk_status == "embedded"
        vs.add_documents.assert_not_called()
        vs.save_local.assert_not_called()

    def test_new_chunk_is_embedded_and_index_saved(self):
        ds = _ds()
        vs = _vs_with_docstore({})
        vs.add_documents.return_value = ["new-uuid"]

        result = ds._embed_batch([_chunk(9)], vs, "NEWS_L1")

        assert len(result) == 1
        assert result[0].embedding_id == "new-uuid"
        vs.add_documents.assert_called_once()
        vs.save_local.assert_called_once_with("NEWS_L1")

    def test_mixed_batch_splits_correctly(self):
        ds = _ds()
        vs = _vs_with_docstore({"real-uuid": _doc(1, 1, 0)})
        vs.add_documents.return_value = ["new-uuid"]

        result = ds._embed_batch([_chunk(1), _chunk(2)], vs, "NEWS_L1")

        by_sitemap = {c.sitemap_id: c for c in result}
        assert by_sitemap[1].embedding_id == "real-uuid"
        assert by_sitemap[2].embedding_id == "new-uuid"
        # only the genuinely-new chunk (sitemap 2) is sent to add_documents
        added_docs = vs.add_documents.call_args[0][0]
        assert len(added_docs) == 1
        assert added_docs[0].metadata["sitemap_id"] == 2

    def test_duplicate_key_within_same_batch_is_embedded_once(self):
        """DBT-09: two chunks sharing (sitemap_id, chunk_level, chunk_index) in the
        SAME call (e.g. a specific_sitemaps list with a duplicate entry) must not
        both be embedded -- that produced 1,035 duplicate rows/vectors in production."""
        ds = _ds()
        vs = _vs_with_docstore({})
        vs.add_documents.return_value = ["only-uuid"]

        result = ds._embed_batch([_chunk(9), _chunk(9)], vs, "NEWS_L1")

        assert len(result) == 1
        assert result[0].embedding_id == "only-uuid"
        vs.add_documents.assert_called_once()
        assert len(vs.add_documents.call_args[0][0]) == 1  # only one Document sent to FAISS

    def test_duplicate_key_already_in_faiss_is_returned_once(self):
        """SYS-26: DBT-09's guard only covered the new-chunk branch. When the
        duplicated key is ALREADY in FAISS (the SYS-17 recovery path -- exactly
        DBT-20's orphan-repair shape), both copies used to reach `result`, and
        save_chunks' unique index then aborted the whole batch on the second row."""
        ds = _ds()
        vs = _vs_with_docstore({"real-uuid": _doc(9, 1, 0)})

        result = ds._embed_batch([_chunk(9), _chunk(9)], vs, "NEWS_L1")

        assert len(result) == 1
        assert result[0].embedding_id == "real-uuid"
        vs.add_documents.assert_not_called()

    def test_duplicate_key_mixing_existing_and_new_within_same_batch(self):
        """Three copies of the same key, one already in FAISS: still exactly one
        result, and the two new-looking copies never both reach add_documents."""
        ds = _ds()
        vs = _vs_with_docstore({"real-uuid": _doc(9, 1, 0)})

        result = ds._embed_batch([_chunk(9), _chunk(9), _chunk(9)], vs, "NEWS_L1")

        assert len(result) == 1
        assert result[0].embedding_id == "real-uuid"
        vs.add_documents.assert_not_called()

    def test_multiple_chunks_same_sitemap_different_index_are_matched_independently(self):
        """A sitemap can have several L2 chunks; each (level, index) pair must match
        its own docstore entry, not just the sitemap_id."""
        ds = _ds()
        vs = _vs_with_docstore({"uuid-0": _doc(5, 2, 0), "uuid-1": _doc(5, 2, 1)})

        result = ds._embed_batch([_chunk(5, 2, 0), _chunk(5, 2, 1)], vs, "NEWS_L2")

        by_index = {c.chunk_index: c for c in result}
        assert by_index[0].embedding_id == "uuid-0"
        assert by_index[1].embedding_id == "uuid-1"
        vs.add_documents.assert_not_called()


class TestSaveRoutesByChunkLevel:
    def test_l1_and_l2_chunks_go_to_their_own_index(self):
        ds = _ds()
        ds.vs_l1 = _vs_with_docstore({})
        ds.vs_l1.add_documents.return_value = ["l1-uuid"]
        ds.vs_l2 = _vs_with_docstore({})
        ds.vs_l2.add_documents.return_value = ["l2-uuid"]

        result = ds.save([_chunk(1, chunk_level=1), _chunk(1, chunk_level=2)])

        by_level = {c.chunk_level: c for c in result}
        assert by_level[1].embedding_id == "l1-uuid"
        assert by_level[2].embedding_id == "l2-uuid"
