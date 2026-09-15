"""
Search-ranking bug regression for QueryProcessor:
  - _re_rank orders by similarity (higher semantic_score first), not inverted.
  - query() drops hits below the relevance floor (off-topic -> no junk),
    but keeps keyword (bm25) matches.
"""
from unittest.mock import MagicMock

from newscrawler.web.query_processor import QueryProcessor
from newscrawler.core.constants import RAG_MIN_SEMANTIC_SCORE


def _qp():
    qp = QueryProcessor.__new__(QueryProcessor)
    qp.faiss_ds = MagicMock()
    qp.client = MagicMock()
    qp._gemini = None  # answer generation disabled; we only assert on sources
    # neutralise DB-backed helpers
    qp._fts_search = lambda q, k: []
    qp._enrich_with_parent_context = lambda hits: hits
    return qp


class TestReRankOrdering:
    def test_higher_semantic_ranks_first(self):
        hits = [
            {"sitemap_id": 1, "semantic_score": 0.3, "bm25_score": 0.0, "posted_at": "20260101"},
            {"sitemap_id": 2, "semantic_score": 0.9, "bm25_score": 0.0, "posted_at": "20260101"},
        ]
        ranked = QueryProcessor._re_rank(hits)
        assert ranked[0]["sitemap_id"] == 2, "higher similarity must rank first (not inverted)"


class TestRelevanceFloor:
    def test_offtopic_low_similarity_returns_no_sources(self):
        qp = _qp()
        low = RAG_MIN_SEMANTIC_SCORE - 0.1
        qp.faiss_ds.search_l2.return_value = [
            {"sitemap_id": 10, "semantic_score": low, "bm25_score": 0.0,
             "posted_at": "20260101", "title": "irrelevant", "text_content": "x"},
        ]
        result = qp.query("off topic", session_history=[])
        assert result["sources"] == [], "below-floor hits must be filtered out"

    def test_relevant_high_similarity_kept(self):
        qp = _qp()
        high = RAG_MIN_SEMANTIC_SCORE + 0.2
        qp.faiss_ds.search_l2.return_value = [
            {"sitemap_id": 11, "semantic_score": high, "bm25_score": 0.0,
             "posted_at": "20260101", "title": "relevant", "text_content": "x"},
        ]
        result = qp.query("on topic", session_history=[])
        assert len(result["sources"]) == 1

    def test_keyword_match_kept_even_below_floor(self):
        qp = _qp()
        low = RAG_MIN_SEMANTIC_SCORE - 0.2
        qp.faiss_ds.search_l2.return_value = []
        qp._fts_search = lambda q, k: [
            {"sitemap_id": 12, "semantic_score": 0.0, "bm25_score": 0.5,
             "posted_at": "20260101", "title": "keyword hit", "text_content": "x"},
        ]
        result = qp.query("exact keyword", session_history=[])
        assert len(result["sources"]) == 1, "strong keyword match must survive the semantic floor"
