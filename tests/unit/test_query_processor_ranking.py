"""
Search-ranking regressions for QueryProcessor:
  - _re_rank orders by similarity (higher semantic_score first), not inverted.
  - query() drops hits below the relevance floor (off-topic -> no junk),
    but keeps keyword matches covering
    at least RAG_MIN_KEYWORD_COVERAGE of the question (SYS-103).
  - SYS-105: a sign-off paragraph ("(jon)") is never a source, however similar.
  - SYS-106: an article one retriever found is scored on the other signal too.
  - SYS-107: a question that asks for the latest news prefers recent articles.
  - SYS-104: a follow-up is retrieved with the thread's questions.
"""
import logging
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

import newscrawler.web.query_processor as qp_mod
from newscrawler.web import keywords
from newscrawler.web.filters import Filters
from newscrawler.web.query_processor import QueryProcessor, recency, retrieval_text
from newscrawler.core.constants import (
    RAG_BM25_WEIGHT,
    RAG_MIN_KEYWORD_COVERAGE,
    RAG_MIN_SEMANTIC_SCORE,
    RAG_RECENCY_WEIGHT,
    RAG_TOP_K,
)

TODAY = date(2026, 10, 7)
# A real paragraph is longer than MIN_PARAGRAPH_WORDS; a test hit with one word of text is a
# sign-off and is dropped (SYS-105).
PARA = "Bank Indonesia menahan suku bunga acuan di level 5,75 persen pada rapat dewan gubernur bulan ini."
KQ = object()
TODAY_CUE = keywords.recency_cue("hari ini")   # a keyword query; its content does not matter once _fts_search / _coverage are stubbed


def _hit(sid, semantic=0.0, keyword=0.0, posted_at="20261007", text_content=PARA, **extra):
    return dict({"sitemap_id": sid, "semantic_score": semantic, "keyword_score": keyword, "posted_at": posted_at,
                 "title": f"t{sid}", "text_content": text_content}, **extra)


def _qp(semantic=(), fts=(), similarity=None, coverage=None):
    """A QueryProcessor whose two retrievers return these hits. `similarity` / `coverage` score the
    other signal of a one-retriever hit (SYS-106); by default 0."""
    qp = QueryProcessor.__new__(QueryProcessor)
    qp.faiss_ds = MagicMock()
    qp.faiss_ds.search_l2.return_value = [dict(h) for h in semantic]
    qp.faiss_ds.similarity.side_effect = similarity or (lambda q, texts, ids=None: [0.0] * len(texts))
    qp.client = MagicMock()
    qp.summarizer = None  # answer generation disabled; we only assert on sources
    qp.usage = MagicMock()
    # neutralise DB-backed helpers
    qp._keyword_query = MagicMock(return_value=KQ)
    qp._fts_search = MagicMock(side_effect=lambda kq, k, filters, today, recent=False: [dict(h) for h in fts])
    qp._coverage = MagicMock(side_effect=coverage or (lambda kq, texts: [0.0] * len(texts)))
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
        qp = _qp(semantic=[_hit(10, semantic=RAG_MIN_SEMANTIC_SCORE - 0.1)])
        result = qp.query("off topic", session_history=[])
        assert result["sources"] == [], "below-floor hits must be filtered out"

    def test_relevant_high_similarity_kept(self):
        qp = _qp(semantic=[_hit(11, semantic=RAG_MIN_SEMANTIC_SCORE + 0.2)])
        result = qp.query("on topic", session_history=[])
        assert len(result["sources"]) == 1

    def test_keyword_match_kept_even_below_floor(self):
        qp = _qp(fts=[_hit(12, keyword=RAG_MIN_KEYWORD_COVERAGE)],
                 similarity=lambda q, texts, ids=None: [RAG_MIN_SEMANTIC_SCORE - 0.2] * len(texts))
        result = qp.query("exact keyword", session_history=[])
        assert len(result["sources"]) == 1, "strong keyword match must survive the semantic floor"

    def test_weak_keyword_match_below_both_floors_dropped(self):
        """SYS-103: a paragraph holding a few of the question's words is not a source by itself."""
        qp = _qp(fts=[_hit(13, keyword=RAG_MIN_KEYWORD_COVERAGE - 0.05)])
        assert qp.query("exact keyword", session_history=[])["sources"] == []

    def test_at_most_top_k_sources(self):
        """DBT-62: eight relevant hits give RAG_TOP_K (5) cards, numbered from 1."""
        qp = _qp(semantic=[_hit(i, semantic=0.9 - i / 100) for i in range(8)])
        hits = qp.retrieve("q", Filters(), TODAY)
        assert len(hits) == RAG_TOP_K == 5
        assert [h["n"] for h in hits] == [1, 2, 3, 4, 5]


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

    def test_merge_keeps_the_best_semantic_score_per_article(self):
        """DBT-62: two paragraphs of one article; the better match is the article's score."""
        merged = QueryProcessor._merge([{"sitemap_id": 5, "semantic_score": 0.6},
                                        {"sitemap_id": 5, "semantic_score": 0.8}], [])
        assert merged[0]["semantic_score"] == 0.8

    def test_merge_records_which_retriever_found_the_article(self):
        merged = {h["sitemap_id"]: h["origin"] for h in QueryProcessor._merge(
            [{"sitemap_id": 1, "semantic_score": 0.8}, {"sitemap_id": 2, "semantic_score": 0.7}],
            [{"sitemap_id": 2, "keyword_score": 0.9}, {"sitemap_id": 3, "keyword_score": 1.0}])}
        assert merged == {1: "semantic", 2: "both", 3: "keyword"}


class TestShortParagraphs:
    """SYS-105 (#275): a one-word chunk is a hub (semantic ~0.78 to any question)."""

    def test_a_one_word_chunk_is_never_a_source(self):
        qp = _qp(semantic=[_hit(1, semantic=0.78, text_content="(jon)"),
                           _hit(2, semantic=0.70)])
        assert [h["sitemap_id"] for h in qp.retrieve("Apa itu Danantara?", Filters(), TODAY)] == [2]

    def test_only_fragments_give_no_sources(self):
        """'qwerty asdf zxcv' got three cards of one-word chunks instead of the no-hits state."""
        qp = _qp(semantic=[_hit(i, semantic=0.67, text_content=t) for i, t in enumerate(["--", "( )", "Editor: X"])])
        assert qp.retrieve("qwerty asdf zxcv", Filters(), TODAY) == []

    def test_the_minimum_is_inclusive_and_applies_to_keyword_hits(self):
        n = qp_mod.MIN_PARAGRAPH_WORDS
        qp = _qp(semantic=[_hit(1, semantic=0.9, text_content=" ".join(["kata"] * n))],
                 fts=[_hit(2, keyword=1.0, text_content=" ".join(["kata"] * (n - 1)))])
        assert [h["sitemap_id"] for h in qp.retrieve("q", Filters(), TODAY)] == [1]


class TestBothSignalsScored:
    """SYS-106 (#276): a missing score used to count as 0, so a keyword-only hit scored at most
    0.40 and never reached the five sources."""

    def test_a_full_coverage_keyword_only_hit_outranks_a_semantic_hit_without_the_words(self):
        qp = _qp(semantic=[_hit(1, semantic=0.75)], fts=[_hit(2, keyword=1.0)],
                 similarity=lambda q, texts, ids=None: [0.70] * len(texts))
        hits = qp.retrieve("Apa itu Danantara?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [2, 1]
        assert hits[0]["semantic_score"] == 0.70 and hits[0]["origin"] == "keyword"

    def test_each_one_retriever_hit_gets_the_other_score_for_its_own_paragraph(self):
        sem_para, kw_para = PARA + " semantik", PARA + " kata kunci"
        qp = _qp(semantic=[_hit(1, semantic=0.8, text_content=sem_para)],
                 fts=[_hit(2, keyword=0.9, text_content=kw_para, embedding_id="e2")],
                 similarity=lambda q, texts, ids=None: [0.65] * len(texts), coverage=lambda kq, texts: [0.5] * len(texts))
        hits = {h["sitemap_id"]: h for h in qp.retrieve("Apa itu Danantara?", Filters(), TODAY)}
        assert (hits[1]["keyword_score"], hits[2]["semantic_score"]) == (0.5, 0.65)
        qp.faiss_ds.similarity.assert_called_once_with("Apa itu Danantara?", [kw_para], ["e2"])
        qp._coverage.assert_called_once_with(KQ, [sem_para])

    def test_an_article_both_found_is_not_rescored(self):
        qp = _qp(semantic=[_hit(1, semantic=0.8)], fts=[_hit(1, keyword=0.9)])
        hits = qp.retrieve("q", Filters(), TODAY)
        assert (hits[0]["semantic_score"], hits[0]["keyword_score"]) == (0.8, 0.9)
        assert not qp.faiss_ds.similarity.called and not qp._coverage.called

    def test_no_keyword_query_no_coverage(self):
        qp = _qp(semantic=[_hit(1, semantic=0.8)])
        qp._keyword_query.return_value = None
        qp.retrieve("qwerty", Filters(), TODAY)
        assert not qp._fts_search.called and not qp._coverage.called

    def test_a_failed_score_stays_zero_and_is_logged(self, caplog):
        qp = _qp(semantic=[_hit(1, semantic=0.8)], fts=[_hit(2, keyword=1.0)])
        qp.faiss_ds.similarity.side_effect = RuntimeError("encoder gone")
        qp._coverage.side_effect = RuntimeError("db down")
        hits = {h["sitemap_id"]: h for h in qp.retrieve("q", Filters(), TODAY)}
        assert hits[2]["semantic_score"] == 0.0 and hits[1]["keyword_score"] == 0.0
        assert "keyword-only hits failed" in caplog.text and "semantic-only hits failed" in caplog.text

    def test_the_log_counts_kept_keyword_only_hits(self, caplog):
        caplog.set_level(logging.INFO, logger="newscrawler.web.query_processor")
        qp = _qp(semantic=[_hit(1, semantic=0.8)], fts=[_hit(1, keyword=0.9), _hit(2, keyword=1.0), _hit(3, keyword=1.0)],
                 similarity=lambda q, texts, ids=None: [0.7] * len(texts))
        qp.retrieve("q", Filters(), TODAY)
        assert "keyword_only=2" in caplog.text


class TestRecency:
    """SYS-107 (#277): 'Berapa harga emas Antam hari ini?' was answered with the 1 Oct price."""

    def test_default_fades_slowly(self):
        assert recency(TODAY, TODAY) == 1.0
        assert recency(TODAY - timedelta(days=7), TODAY) == pytest.approx(0.9)
        assert recency(TODAY - timedelta(days=700), TODAY) == 0.0

    def test_asked_for_recent_halves_at_the_horizon(self):
        assert [recency(TODAY - timedelta(days=d), TODAY, 1) for d in (0, 1, 3)] == [1.0, 0.5, 0.25]
        assert recency(TODAY - timedelta(days=7), TODAY, 7) == 0.5

    def test_undated_and_future_articles(self):
        assert recency(None, TODAY, 1) == recency(None, TODAY) == 0.5
        assert recency(TODAY + timedelta(days=3), TODAY, 1) == 1.0

    def test_today_beats_last_weeks_near_copy_only_when_asked(self):
        def hits():
            return [{"sitemap_id": 1, "semantic_score": 0.93, "keyword_score": 1.0, "posted_at": "20260930"},
                    {"sitemap_id": 2, "semantic_score": 0.90, "keyword_score": 1.0, "posted_at": "20261007"}]
        assert QueryProcessor._re_rank(hits(), TODAY, TODAY_CUE)[0]["sitemap_id"] == 2
        assert QueryProcessor._re_rank(hits(), TODAY)[0]["sitemap_id"] == 1

    def test_a_keyword_match_of_today_does_not_beat_a_relevant_article(self):
        """'Siapa Menteri Keuangan sekarang?' ranked a rice-aid story of today (semantic 0.52,
        coverage 1.0) above the minister's appointment: recency counts only for an article that is
        relevant by meaning."""
        hits = [{"sitemap_id": 1, "semantic_score": 0.52, "keyword_score": 1.0, "posted_at": "20261007"},
                {"sitemap_id": 2, "semantic_score": 0.90, "keyword_score": 1.0, "posted_at": "20261001"}]
        ranked = QueryProcessor._re_rank(hits, TODAY, TODAY_CUE)
        assert ranked[0]["sitemap_id"] == 2
        assert ranked[1]["final_score"] == pytest.approx(0.52 * 0.6 + 0.3), "no recency below the semantic floor"

    def test_the_latest_decision_outranks_todays_market_outlook(self):
        """'terbaru' asks for the latest there is: recency only breaks near-ties. Measured on
        'Apa keputusan Bank Indonesia soal suku bunga terbaru?': the decision of 15 days ago
        (cosine 0.75) under a market outlook of today (0.63) holding every word, with one weight
        for every cue."""
        hits = [{"sitemap_id": 1, "semantic_score": 0.63, "keyword_score": 1.0, "posted_at": "20261007"},
                {"sitemap_id": 2, "semantic_score": 0.75, "keyword_score": 1.0, "posted_at": "20260922"}]
        assert QueryProcessor._re_rank(hits, TODAY, keywords.recency_cue("terbaru"))[0]["sitemap_id"] == 2
        assert QueryProcessor._re_rank(hits, TODAY, TODAY_CUE)[0]["sitemap_id"] == 1, "'hari ini' means today"

    def test_the_question_decides_and_reaches_the_keyword_half(self, caplog):
        caplog.set_level(logging.INFO, logger="newscrawler.web.query_processor")
        qp = _qp(semantic=[_hit(1, semantic=0.9)])
        qp.retrieve("Berapa harga emas Antam hari ini?", Filters(), TODAY)
        assert qp._fts_search.call_args.args[4] is True and "recent=1d " in caplog.text
        qp.retrieve("Berapa harga emas Antam?", Filters(), TODAY)
        assert qp._fts_search.call_args.args[4] is False and "recent=None " in caplog.text

    def test_the_semantic_half_over_fetches(self):
        qp = _qp()
        qp.retrieve("q", Filters(), TODAY)
        assert qp.faiss_ds.search_l2.call_args.kwargs["k"] == qp_mod.SEMANTIC_K == 100


class TestFollowUp:
    """SYS-104 (#274): 'Berapa target pertumbuhannya tahun depan?' after an OJK credit question
    returned and answered GDP growth 2027."""
    HISTORY = [{"question": "Apa kata OJK soal kredit perbankan?", "answer": "OJK menyebut ..."}]

    def test_a_follow_up_carries_the_previous_question(self):
        assert retrieval_text("Berapa target pertumbuhannya tahun depan?", self.HISTORY) == (
            "Berapa target pertumbuhannya tahun depan? Apa kata OJK soal kredit perbankan?")

    def test_the_newest_questions_follow_its_own_words(self):
        history = [{"question": f"q{i}", "answer": "a"} for i in range(1, 5)]
        assert retrieval_text("lanjut?", history) == "lanjut? q4 q3"

    def test_without_history_a_question_is_retrieved_on_its_own_text(self):
        assert retrieval_text("  Apa itu Danantara?  ", []) == "Apa itu Danantara?"
        assert retrieval_text("Apa itu Danantara?", [{"question": " ", "answer": "a"}]) == "Apa itu Danantara?"

    def test_both_retrievers_and_the_scores_get_the_threads_subject(self):
        qp = _qp(semantic=[_hit(1, semantic=0.9)], fts=[_hit(2, keyword=1.0)])
        qp.retrieve("Berapa target pertumbuhannya tahun depan?", Filters(), TODAY, history=self.HISTORY)
        expected = "Berapa target pertumbuhannya tahun depan? Apa kata OJK soal kredit perbankan?"
        assert qp.faiss_ds.search_l2.call_args.args[0] == expected
        qp._keyword_query.assert_called_once_with(expected)
        assert qp.faiss_ds.similarity.call_args.args[0] == expected

    def test_query_retrieves_with_the_session_history(self):
        qp = _qp(semantic=[_hit(1, semantic=0.9)])
        qp.query("Dampaknya?", session_history=self.HISTORY)
        assert "OJK" in qp.faiss_ds.search_l2.call_args.args[0]

    def test_query_retrieves_with_the_thread_when_given(self):
        """SYS-104: the JSON API passes every question asked; the prompt keeps the answered turns."""
        qp = _qp(semantic=[_hit(1, semantic=0.9)])
        qp.query("Dampaknya?", session_history=[], thread=self.HISTORY)
        assert "OJK" in qp.faiss_ds.search_l2.call_args.args[0]


class TestSessionMemories:
    """SYS-104: the prompt's answered turns and the retrieval thread are kept apart."""

    def test_questions_and_answered_turns(self):
        from newscrawler.web.session_manager import SessionManager
        sm = SessionManager()
        sm.record_question("s", "q1")
        sm.record_question("s", "q2")
        sm.update("s", "q2", "a2")
        assert sm.get_questions("s") == [{"question": "q1"}, {"question": "q2"}]
        assert sm.get_history("s") == [{"question": "q2", "answer": "a2"}]
        assert sm.get_questions(None) == [] and sm.get_questions("other") == []

    def test_the_thread_keeps_the_last_five(self):
        from newscrawler.web.session_manager import SessionManager
        sm = SessionManager()
        for i in range(7):
            sm.record_question("s", f"q{i}")
        assert [t["question"] for t in sm.get_questions("s")] == ["q2", "q3", "q4", "q5", "q6"]

    def test_an_expired_session_forgets_both(self):
        from newscrawler.web.session_manager import SessionManager
        sm = SessionManager(ttl_seconds=-1)
        sm.record_question("s", "q1")
        sm.update("s", "q1", "a1")
        assert sm.get_questions("s") == [] and sm.get_history("s") == []
