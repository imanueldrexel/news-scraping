"""
Search-ranking bug regression: ChunkFAISSDatasource.search_l2 must convert the FAISS
L2 distance (lower = more similar) into a cosine similarity (higher = more relevant),
so downstream ranking does not invert results.
"""
import math
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
        # d=0.5451 -> cos = 1 - d^2/2 ~= 0.8514
        ds = _ds_with_results([(_doc("x"), 0.5451)])
        sim = ds.search_l2("q", k=1)[0]["semantic_score"]
        assert abs(sim - (1 - 0.5451**2 / 2)) < 1e-6
        assert sim > 0.8

    def test_large_distance_low_similarity(self):
        # d=1.4 -> cos = 1 - 0.98 = 0.02
        ds = _ds_with_results([(_doc("x"), 1.4)])
        sim = ds.search_l2("q", k=1)[0]["semantic_score"]
        assert sim < 0.1

    def test_similarity_never_negative(self):
        ds = _ds_with_results([(_doc("x"), 2.0)])  # max L2 distance for unit vectors
        assert ds.search_l2("q", k=1)[0]["semantic_score"] >= 0.0

    def test_more_similar_ranks_higher(self):
        ds = _ds_with_results([(_doc("near", 1), 0.5), (_doc("far", 2), 1.3)])
        hits = ds.search_l2("q", k=2)
        near = next(h for h in hits if h["sitemap_id"] == 1)
        far  = next(h for h in hits if h["sitemap_id"] == 2)
        assert near["semantic_score"] > far["semantic_score"]
