"""
Search-ranking bug regression: ChunkFAISSDatasource.search_l2 must convert the FAISS
distance (lower = more similar) into a cosine similarity (higher = more relevant),
so downstream ranking does not invert results. SYS-110 (#284): an IndexFlatL2 returns the
SQUARED L2 distance, d = 2 - 2*cos for unit vectors, so cos = 1 - d/2 (it read 1 - d^2/2).
"""
import math

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
    ChunkFAISSDatasource,
)


def _doc(text, sitemap_id=1):
    return SimpleNamespace(page_content=text, metadata={"sitemap_id": sitemap_id,
                                                        "title": "t", "source": "S",
                                                        "posted_at": "20260101"})


def _ds_with_results(results):
    ds = ChunkFAISSDatasource.__new__(ChunkFAISSDatasource)
    ds.vs_l2 = MagicMock()
    ds.vs_l2.similarity_search_with_score.return_value = results
    return ds


class TestSearchL2Score:
    def test_distance_zero_maps_to_similarity_one(self):
        ds = _ds_with_results([(_doc("x"), 0.0)])
        assert ds.search_l2("q", k=1)[0]["semantic_score"] == 1.0

    def test_small_distance_high_similarity(self):
        # squared distance 0.3623 -> cos = 1 - 0.3623/2 = 0.8189 (the gold question's top hit, 2026-10-08)
        ds = _ds_with_results([(_doc("x"), 0.3623)])
        sim = ds.search_l2("q", k=1)[0]["semantic_score"]
        assert abs(sim - 0.81885) < 1e-6

    def test_large_distance_low_similarity(self):
        # squared distance 1.4 -> cos = 0.3
        ds = _ds_with_results([(_doc("x"), 1.4)])
        sim = ds.search_l2("q", k=1)[0]["semantic_score"]
        assert abs(sim - 0.3) < 1e-6

    def test_similarity_never_negative(self):
        ds = _ds_with_results([(_doc("x"), 4.0)])  # max squared L2 distance for unit vectors (cos -1)
        assert ds.search_l2("q", k=1)[0]["semantic_score"] >= 0.0

    def test_more_similar_ranks_higher(self):
        ds = _ds_with_results([(_doc("near", 1), 0.5), (_doc("far", 2), 1.3)])
        hits = ds.search_l2("q", k=2)
        near = next(h for h in hits if h["sitemap_id"] == 1)
        far  = next(h for h in hits if h["sitemap_id"] == 2)
        assert near["semantic_score"] > far["semantic_score"]


from langchain_core.embeddings import Embeddings  # noqa: E402


class _Embeddings(Embeddings):
    """Deterministic unit vectors per text, counting what it embeds."""
    def __init__(self, vectors):
        self.vectors, self.embedded = vectors, []

    def embed_documents(self, texts):
        self.embedded.extend(texts)
        return [self.vectors[t] for t in texts]

    def embed_query(self, text):
        return self.vectors[text]


class TestSimilarityOfKeywordOnlyParagraphs:
    """SYS-106 (#276): a paragraph the keyword half found is scored on search_l2's scale, from its
    stored NEWS_L2 vector when it has one (re-embedding 20 paragraphs cost ~500 ms per question)."""

    def _ds(self):
        from langchain_community.vectorstores import FAISS
        s = 0.6 ** 0.5
        vectors = {"q": [1.0, 0.0, 0.0], "near": [s, (1 - 0.6) ** 0.5, 0.0], "far": [0.0, 0.0, 1.0],
                   "new paragraph": [0.8, 0.6, 0.0]}
        emb = _Embeddings(vectors)
        ds = ChunkFAISSDatasource.__new__(ChunkFAISSDatasource)
        ds.embedding_model = emb
        ds.vs_l2 = FAISS.from_texts(["near", "far"], emb, metadatas=[{"sitemap_id": 1}, {"sitemap_id": 2}],
                                    ids=["id-near", "id-far"])
        emb.embedded.clear()
        return ds, emb

    def test_a_stored_paragraph_is_scored_with_its_vector_not_re_embedded(self):
        ds, emb = self._ds()
        assert ds.similarity("q", ["near", "far"], ["id-near", "id-far"]) == [
            pytest.approx(0.6 ** 0.5), pytest.approx(0.0)]
        assert emb.embedded == []

    def test_it_matches_search_l2s_score_for_the_same_paragraph(self):
        """SYS-110 (#284): on a real IndexFlatL2, search_l2's score is the cosine (the dot product of
        the unit vectors), the scale a keyword-only paragraph is scored on."""
        ds, _ = self._ds()
        searched = {h["text_content"]: h["semantic_score"] for h in ds.search_l2("q", k=2)}
        assert ds.similarity("q", ["near"], ["id-near"]) == [pytest.approx(searched["near"], abs=1e-6)]

    def test_an_unknown_or_missing_id_is_embedded(self):
        ds, emb = self._ds()
        got = ds.similarity("q", ["near", "new paragraph", "far"], ["id-near", "id-gone", None])
        assert got == [pytest.approx(0.6 ** 0.5), pytest.approx(0.8), pytest.approx(0.0)]
        assert emb.embedded == ["new paragraph", "far"]

    def test_no_ids_embeds_every_text(self):
        ds, emb = self._ds()
        assert ds.similarity("q", ["new paragraph"]) == [pytest.approx(0.8)]
        assert emb.embedded == ["new paragraph"]

    def test_the_position_map_follows_a_reloaded_index(self):
        from langchain_community.vectorstores import FAISS
        ds, emb = self._ds()
        ds.similarity("q", ["near"], ["id-near"])
        # Reloaded: the id now sits at another position and holds "far"; the cached map would read
        # position 0 ("near" in the new index) and score 0.77.
        ds.vs_l2 = FAISS.from_texts(["near", "far"], emb, ids=["id-new", "id-near"])
        emb.embedded.clear()
        assert ds.similarity("q", ["far"], ["id-near"]) == [pytest.approx(0.0)]
        assert emb.embedded == []

    def test_a_reload_during_the_call_does_not_mix_two_indexes(self):
        """SYS-141 (#323): `refresh_stale` swaps vs_l2 between the position lookup and the vector
        read. In the new index the old position of 'id-near' holds 'far' (cosine 0): the score must
        still be the paragraph's own (0.77), read from the index its position came from."""
        from langchain_community.vectorstores import FAISS
        ds, emb = self._ds()
        reloaded = FAISS.from_texts(["far", "near"], emb, ids=["id-far", "id-near"])
        lookup = ds._l2_positions

        def lookup_then_reload(vs):
            positions = lookup(vs)
            ds.vs_l2 = reloaded
            return positions
        ds._l2_positions = lookup_then_reload
        emb.embedded.clear()

        assert ds.similarity("q", ["near"], ["id-near"]) == [pytest.approx(0.6 ** 0.5)]
        assert emb.embedded == []
