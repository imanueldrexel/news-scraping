"""
Search-ranking bug regression for QueryProcessor:
  - _re_rank orders by similarity (higher semantic_score first), not inverted.
  - query() drops hits below the relevance floor (off-topic -> no junk),
    but keeps keyword matches covering
    at least RAG_MIN_KEYWORD_COVERAGE of the question (SYS-103).
"""
from datetime import date
from unittest.mock import MagicMock

from newscrawler.web.query_processor import QueryProcessor
from newscrawler.core.constants import (
    RAG_BM25_WEIGHT,
    RAG_MIN_KEYWORD_COVERAGE,
    RAG_MIN_SEMANTIC_SCORE,
    RAG_RECENCY_WEIGHT,
)


def _qp():
    qp = QueryProcessor.__new__(QueryProcessor)
    qp.faiss_ds = MagicMock()
    qp.client = MagicMock()
    qp.summarizer = None  # answer generation disabled; we only assert on sources
    qp.usage = MagicMock()
    # neutralise DB-backed helpers
    qp._fts_search = lambda q, k, filters, today: []
    qp._attach_metadata = lambda hits: hits
    return qp


class TestReRankOrdering:
    def test_higher_semantic_ranks_first(self):
        hits = [
            {"sitemap_id": 1, "semantic_score": 0.3, "keyword_score": 0.0, "posted_at": "20260101"},
            {"sitemap_id": 2, "semantic_score": 0.9, "keyword_score": 0.0, "posted_at": "20260101"},
        ]
        ranked = QueryProcessor._re_rank(hits)
        assert ranked[0]["sitemap_id"] == 2, "higher similarity must rank first (not inverted)"


class TestRelevanceFloor:
    def test_offtopic_low_similarity_returns_no_sources(self):
        qp = _qp()
        low = RAG_MIN_SEMANTIC_SCORE - 0.1
        qp.faiss_ds.search_l2.return_value = [
            {"sitemap_id": 10, "semantic_score": low, "keyword_score": 0.0,
             "posted_at": "20260101", "title": "irrelevant", "text_content": "x"},
        ]
        result = qp.query("off topic", session_history=[])
        assert result["sources"] == [], "below-floor hits must be filtered out"

    def test_relevant_high_similarity_kept(self):
        qp = _qp()
        high = RAG_MIN_SEMANTIC_SCORE + 0.2
        qp.faiss_ds.search_l2.return_value = [
            {"sitemap_id": 11, "semantic_score": high, "keyword_score": 0.0,
             "posted_at": "20260101", "title": "relevant", "text_content": "x"},
        ]
        result = qp.query("on topic", session_history=[])
        assert len(result["sources"]) == 1

    def test_keyword_match_kept_even_below_floor(self):
        qp = _qp()
        low = RAG_MIN_SEMANTIC_SCORE - 0.2
        qp.faiss_ds.search_l2.return_value = []
        qp._fts_search = lambda q, k, filters, today: [
            {"sitemap_id": 12, "semantic_score": 0.0, "keyword_score": RAG_MIN_KEYWORD_COVERAGE,
             "posted_at": "20260101", "title": "keyword hit", "text_content": "x"},
        ]
        result = qp.query("exact keyword", session_history=[])
        assert len(result["sources"]) == 1, "strong keyword match must survive the semantic floor"

    def test_weak_keyword_match_below_both_floors_dropped(self):
        """SYS-103: a paragraph holding a few of the question's words is not a source by itself."""
        qp = _qp()
        qp.faiss_ds.search_l2.return_value = []
        qp._fts_search = lambda q, k, filters, today: [
            {"sitemap_id": 13, "semantic_score": 0.0, "keyword_score": RAG_MIN_KEYWORD_COVERAGE - 0.05,
             "posted_at": "20260101", "title": "partial", "text_content": "x"},
        ]
        assert qp.query("exact keyword", session_history=[])["sources"] == []


class TestKeywordScoreInReRank:
    def test_coverage_counts_as_is_not_scaled(self):
        """SYS-103: keyword_score is a coverage in [0, 1]; the old x10 for ts_rank must not come back."""
        hit = {"sitemap_id": 1, "semantic_score": 0.0, "keyword_score": 0.5, "posted_at": "20260101"}
        QueryProcessor._re_rank([hit], today=date(2026, 1, 1))
        assert abs(hit["final_score"] - (0.5 * RAG_BM25_WEIGHT + RAG_RECENCY_WEIGHT)) < 1e-9

    def test_keyword_coverage_lifts_an_equal_semantic_hit(self):
        a = {"sitemap_id": 1, "semantic_score": 0.7, "keyword_score": 0.0, "posted_at": "20260101"}
        b = {"sitemap_id": 2, "semantic_score": 0.7, "keyword_score": 1.0, "posted_at": "20260101"}
        assert QueryProcessor._re_rank([a, b])[0]["sitemap_id"] == 2

    def test_merge_keeps_the_best_keyword_score_per_article(self):
        semantic = [{"sitemap_id": 5, "semantic_score": 0.8}]
        fts = [{"sitemap_id": 5, "keyword_score": 0.4, "semantic_score": 0.0},
               {"sitemap_id": 5, "keyword_score": 0.9, "semantic_score": 0.0}]
        merged = QueryProcessor._merge(semantic, fts)
        assert len(merged) == 1
        assert merged[0]["keyword_score"] == 0.9 and merged[0]["semantic_score"] == 0.8
