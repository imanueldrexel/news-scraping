"""
Search-ranking regressions for QueryProcessor:
  - _re_rank orders by similarity (higher semantic_score first), not inverted.
  - query() drops hits below the relevance floor (off-topic -> no junk),
    but keeps keyword matches covering
    at least RAG_MIN_KEYWORD_COVERAGE of the question (SYS-103).
  - SYS-105: a sign-off paragraph ("(jon)") is never a source, however similar.
  - SYS-106: an article one retriever found is scored on the other signal too.
  - SYS-107: a question that asks for the latest news prefers recent articles.
  - SYS-104/SYS-140 (ADR-010): a follow-up is rewritten into a standalone question, with a
    deterministic fallback; keyword names are judged per question.
"""
import logging
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import newscrawler.web.query_processor as qp_mod
from newscrawler.web import keywords
from newscrawler.web.filters import Filters
from newscrawler.core.summarizer import Reply, SummarizerError
from newscrawler.web.query_processor import QueryProcessor, recency
from newscrawler.core.constants import (
    RAG_BM25_WEIGHT,
    RAG_DAILY_COST_LIMIT_USD,
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


def _qp(semantic=(), fts=(), similarity=None, coverage=None, subject=None):
    """A QueryProcessor whose two retrievers return these hits. `similarity` / `coverage` score the
    other signal of a one-retriever hit (SYS-106); by default 0. `subject` says which texts hold the
    question's subject (ADR-013); by default all do."""
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
    qp._holds_subject = MagicMock(side_effect=subject or (lambda kq, texts: [True] * len(texts)))
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

    def test_the_minimum_is_fifteen_words(self):
        """DBT-66 (#319): SYS-105 chose 15 on evidence ("15, not 8 ... 10-14-word DETIK sign-offs were
        hubs too"). A 12-word sign-off is not a source; a 15-word paragraph is."""
        sign_off = "Baca berita terbaru lainnya di kanal ekonomi kami hari ini (ega/ega) --"
        assert len(sign_off.split()) == 12
        fifteen = " ".join(["kata"] * 15)
        qp = _qp(semantic=[_hit(1, semantic=0.9, text_content=fifteen), _hit(2, semantic=0.95, text_content=sign_off)])
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

    def test_each_cue_weighs_its_own_weight(self):
        """'hari ini' 0.3, 'pekan ini' 0.2, 'terbaru' 0.1, on an article of today."""
        for question, weight in (("hari ini", 0.3), ("pekan ini", 0.2), ("terbaru", 0.1)):
            hit = {"sitemap_id": 1, "semantic_score": 0.8, "keyword_score": 0.0, "posted_at": "20261007"}
            QueryProcessor._re_rank([hit], TODAY, keywords.recency_cue(question))
            assert hit["final_score"] == pytest.approx(0.8 * 0.6 + weight), question

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


class _Rewriter:
    """A rewrite model: returns `text` (or raises `error`), and records the prompts it was given."""
    name = "deepseek-v4-flash"
    priced = True

    def __init__(self, text=None, error=None):
        self.text, self.error, self.prompts = text, error, []

    def complete(self, prompt):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return Reply(self.text, 150, 20)


def _usage(spent=0.0):
    usage = MagicMock()
    usage.get_today_api_usage.return_value = SimpleNamespace(cost_usd=spent)
    return usage


class TestFollowUp:
    """SYS-104 (#274) + SYS-140 (#322), ADR-010: a follow-up is rewritten into a standalone question
    by one call and retrieved on it; without a usable rewrite, a deterministic fallback."""
    OJK = [{"question": "Apa kata OJK soal kredit perbankan?", "answer": "OJK menyebut ..."}]
    RUPIAH_THIS_WEEK = [{"question": "Kenapa rupiah melemah pekan ini?", "answer": "-"}]

    def _qp(self, rewriter=None, spent=0.0):
        qp = _qp(semantic=[_hit(1, semantic=0.9)], fts=[_hit(2, keyword=1.0)])
        qp.rewriter = rewriter
        qp.usage = _usage(spent)
        return qp

    def test_a_topic_switch_is_retrieved_on_its_own_subject(self):
        """QA's send-back: 'Apa itu Danantara?' after an OJK question got 5 OJK cards. The model
        keeps a question that names its own subject; both retrievers and the scores read it alone."""
        qp = self._qp(_Rewriter("Apa itu Danantara?"))
        _, counts = qp.candidates("Apa itu Danantara?", Filters(), TODAY, self.OJK)
        assert qp.faiss_ds.search_l2.call_args.args[0] == "Apa itu Danantara?"
        qp._keyword_query.assert_called_once_with("Apa itu Danantara?")
        assert qp.faiss_ds.similarity.call_args.args[0] == "Apa itu Danantara?"
        assert counts["rewrite"] == "kept"

    def test_an_elliptical_follow_up_is_retrieved_on_its_rewrite(self):
        rewritten = "Berapa target pertumbuhan kredit perbankan menurut OJK tahun depan?"
        qp = self._qp(_Rewriter(rewritten))
        _, counts = qp.candidates("Berapa target pertumbuhannya tahun depan?", Filters(), TODAY, self.OJK)
        assert qp.faiss_ds.search_l2.call_args.args[0] == rewritten
        qp._keyword_query.assert_called_once_with(rewritten)
        assert counts["rewrite"] == "llm"

    def test_the_prompt_holds_the_last_two_questions_oldest_first_and_the_follow_up(self):
        rewriter = _Rewriter("x?")
        history = [{"question": f"q{i}", "answer": "a"} for i in range(1, 5)]
        self._qp(rewriter).candidates("lanjut?", Filters(), TODAY, history)
        prompt = rewriter.prompts[0]
        assert '1. "q3"' in prompt and '2. "q4"' in prompt and "q2" not in prompt
        assert 'Pertanyaan lanjutan: "lanjut?"' in prompt

    def test_the_recency_cue_comes_from_the_rewrite(self):
        """The model carries 'pekan ini' only for the same event; what it returns is what counts."""
        qp = self._qp(_Rewriter("Apa yang dilakukan BI terhadap pelemahan rupiah pekan ini?"))
        _, counts = qp.candidates("Apa yang dilakukan BI?", Filters(), TODAY, self.RUPIAH_THIS_WEEK)
        assert counts["recent"] == "3d"
        qp = self._qp(_Rewriter("Apa isi UU Ketenagakerjaan yang baru?"))
        _, counts = qp.candidates("Apa isi UU Ketenagakerjaan yang baru?", Filters(), TODAY, self.RUPIAH_THIS_WEEK)
        assert counts["recent"] is None

    def test_the_rewrite_is_counted_under_the_pages_key(self):
        qp = self._qp(_Rewriter("x?"))
        qp.candidates("Dampaknya?", Filters(), TODAY, self.OJK)
        key, = qp.usage.increment_api_call_count.call_args.args
        assert key == "web:deepseek-v4-flash"
        kwargs = qp.usage.increment_api_call_count.call_args.kwargs
        assert kwargs["input_tokens"] == 150 and kwargs["output_tokens"] == 20 and kwargs["cost_usd"] > 0

    def test_over_the_daily_cap_no_call_is_made(self):
        rewriter = _Rewriter("x?")
        qp = self._qp(rewriter, spent=RAG_DAILY_COST_LIMIT_USD)
        _, counts = qp.candidates("Dampaknya?", Filters(), TODAY, self.OJK)
        assert rewriter.prompts == [] and counts["rewrite"] == "fallback-thread"

    @pytest.mark.parametrize("rewriter", [None, _Rewriter(error=SummarizerError("ReadTimeout")),
                                          _Rewriter(""), _Rewriter("satu\ndua")])
    def test_a_follow_up_that_refers_back_falls_back_to_the_thread(self, rewriter):
        """No provider, a failed call, or an unusable output: '-nya' points back, so the thread is used,
        its keyword terms question by question (SYS-140), the recency cue from the follow-up alone."""
        qp = self._qp(rewriter)
        _, counts = qp.candidates("Apa dampaknya ke kredit?", Filters(), TODAY, self.RUPIAH_THIS_WEEK)
        assert qp.faiss_ds.search_l2.call_args.args[0] == "Apa dampaknya ke kredit? Kenapa rupiah melemah pekan ini?"
        qp._keyword_query.assert_called_once_with("Apa dampaknya ke kredit?", "Kenapa rupiah melemah pekan ini?")
        assert counts["rewrite"] == "fallback-thread" and counts["recent"] is None

    def test_an_unusable_reply_is_still_counted(self):
        """DBT-69 (ADR-010 decision 7): a reply that fails the check was paid for, so it counts
        against RAG_DAILY_COST_LIMIT_USD like a usable one."""
        qp = self._qp(_Rewriter("satu\ndua"))
        _, counts = qp.candidates("Apa dampaknya ke kredit?", Filters(), TODAY, self.OJK)
        assert counts["rewrite"] == "fallback-thread"
        kwargs = qp.usage.increment_api_call_count.call_args.kwargs
        assert qp.usage.increment_api_call_count.call_count == 1
        assert kwargs["input_tokens"] == 150 and kwargs["output_tokens"] == 20 and kwargs["cost_usd"] > 0

    def test_a_refusal_falls_back_and_is_never_searched(self):
        """SYS-143: 'Maaf, saya tidak dapat ...' was searched as the question."""
        qp = self._qp(_Rewriter("Maaf, saya tidak dapat menulis ulang pertanyaan tersebut."))
        _, counts = qp.candidates("Berapa target pertumbuhannya tahun depan?", Filters(), TODAY, self.OJK)
        assert counts["rewrite"] == "fallback-thread"
        assert "Maaf" not in qp.faiss_ds.search_l2.call_args.args[0]
        qp.usage.increment_api_call_count.assert_called_once()

    def test_a_kept_follow_up_that_refers_back_is_retrieved_with_the_thread(self):
        """SYS-145 (ADR-014), the composed path: both retrievers and the keyword terms get the thread,
        the cue the follow-up's own words."""
        fed = [{"question": "Apa keputusan The Fed terbaru?", "answer": "-"}]
        qp = self._qp(_Rewriter("Bagaimana dampaknya ke rupiah?"))
        _, counts = qp.candidates("Bagaimana dampaknya ke rupiah?", Filters(), TODAY, fed)
        assert qp.faiss_ds.search_l2.call_args.args[0] == "Bagaimana dampaknya ke rupiah? Apa keputusan The Fed terbaru?"
        qp._keyword_query.assert_called_once_with("Bagaimana dampaknya ke rupiah?", "Apa keputusan The Fed terbaru?")
        assert counts["rewrite"] == "kept-thread" and counts["recent"] is None

    def test_a_follow_up_with_an_adverb_in_nya_falls_back_to_its_own_words(self):
        """SYS-144, the composed path: 'selanjutnya' does not pull a new subject to the old thread."""
        qp = self._qp(None)
        _, counts = qp.candidates("Bagaimana nasib Sritex selanjutnya?", Filters(), TODAY, self.OJK)
        assert qp.faiss_ds.search_l2.call_args.args[0] == "Bagaimana nasib Sritex selanjutnya?"
        assert counts["rewrite"] == "fallback-own"

    def test_a_follow_up_that_names_its_subject_falls_back_to_its_own_words(self):
        qp = self._qp(None)
        _, counts = qp.candidates("Di mana terjadi banjir minggu ini?", Filters(), TODAY, self.OJK)
        assert qp.faiss_ds.search_l2.call_args.args[0] == "Di mana terjadi banjir minggu ini?"
        assert counts["rewrite"] == "fallback-own" and counts["recent"] == "3d"

    def test_the_search_box_makes_no_call(self):
        rewriter = _Rewriter("x?")
        qp = self._qp(rewriter)
        _, counts = qp.candidates("Apa itu Danantara?", Filters(), TODAY, [])
        assert rewriter.prompts == [] and counts["rewrite"] == "alone"

    def test_the_retrieve_log_names_the_rewrite(self, caplog):
        qp = self._qp(_Rewriter("Apa itu Danantara?"))
        with caplog.at_level(logging.INFO, logger="newscrawler.web.query_processor"):
            qp.retrieve("Apa itu Danantara?", Filters(), TODAY, history=self.OJK)
        assert "rewrite=kept" in caplog.text and "query='Apa itu Danantara?'" in caplog.text

    def test_query_resolves_with_the_session_history(self):
        qp = self._qp(None)
        qp.query("Dampaknya?", session_history=self.OJK)
        assert "OJK" in qp.faiss_ds.search_l2.call_args.args[0]

    def test_query_resolves_with_the_thread_when_given(self):
        """The JSON API passes every question asked; the prompt keeps the answered turns."""
        qp = self._qp(None)
        qp.query("Dampaknya?", session_history=[], thread=self.OJK)
        assert "OJK" in qp.faiss_ds.search_l2.call_args.args[0]


class TestWeekWindow:
    """SYS-138 (#317, ADR-012): 'KPK minggu ini' from the search box got 5 cards of 18 Sep-30 Jul
    while the week's 141 KPK articles were stored. A "this week" question prefers the last 7 days;
    the rest of the corpus only fills what the week cannot."""

    @staticmethod
    def _dated(sid, days_old, semantic):
        d = TODAY - timedelta(days=days_old)
        return _hit(sid, semantic=semantic, posted_at=d.strftime("%Y%m%d"), posted_date=d)

    def test_a_3_day_old_paragraph_outranks_a_20_day_old_closer_one(self):
        """The ticket's unit test: semantic 0.70 three days old over 0.80 twenty days old."""
        qp = _qp(semantic=[self._dated(1, 20, 0.80), self._dated(2, 3, 0.70)])
        hits = qp.retrieve("Apa perkembangan kasus KPK minggu ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [2, 1]

    def test_the_week_beats_a_closer_paragraph_the_cue_weight_alone_cannot_lift(self):
        """QA's arithmetic, the shape that failed: 4 days at 0.70 scores 0.42 + 0.086, 24 days at 0.85
        scores 0.51 + 0.022. Without the window the old one leads; with it, the week's does."""
        qp = _qp(semantic=[self._dated(1, 24, 0.85), self._dated(2, 4, 0.70)])
        hits = qp.retrieve("Apa perkembangan kasus KPK minggu ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [2, 1]

    def test_a_full_week_is_the_whole_result(self):
        week = [self._dated(i, i, 0.70) for i in range(1, 6)]
        qp = _qp(semantic=week + [self._dated(9, 20, 0.95)])
        hits = qp.retrieve("Bagaimana kinerja IHSG pekan ini?", Filters(), TODAY)
        assert sorted(h["sitemap_id"] for h in hits) == [1, 2, 3, 4, 5]

    def test_the_window_is_seven_days_inclusive(self):
        week = [self._dated(i, 6, 0.70) for i in range(1, 6)]
        qp = _qp(semantic=week + [self._dated(9, 7, 0.95)])
        assert 9 not in [h["sitemap_id"] for h in qp.retrieve("IHSG pekan ini?", Filters(), TODAY)]

    def test_a_readers_own_date_filter_wins(self):
        qp = _qp(semantic=[self._dated(1, 24, 0.85), self._dated(2, 4, 0.70)])
        hits = qp.retrieve("Apa perkembangan kasus KPK minggu ini?", Filters(days=30), TODAY)
        assert [h["sitemap_id"] for h in hits] == [1, 2]

    @pytest.mark.parametrize("question", ["Berapa harga emas Antam hari ini?", "Harga minyak terbaru?",
                                          "Siapa Menteri Keuangan sekarang?", "Apa itu Danantara?"])
    def test_only_the_week_cue_has_a_window(self, question):
        """ADR-012 measured a window for 'sekarang' and a relevance gate: neither met SYS-112's
        goal, and the gate cost other questions. Only "this week" gets one."""
        qp = _qp(semantic=[self._dated(1, 20, 0.95), self._dated(2, 3, 0.60)])
        _, counts = qp.candidates(question, Filters(), TODAY)
        assert counts["window"] is None
        assert qp.faiss_ds.search_l2.call_count == 1

    def test_one_rewrite_one_keyword_query_and_the_log_names_the_window(self, caplog):
        qp = _qp(semantic=[self._dated(1, 20, 0.80), self._dated(2, 3, 0.70)])
        with caplog.at_level(logging.INFO, logger="newscrawler.web.query_processor"):
            qp.retrieve("KPK minggu ini?", Filters(), TODAY)
        qp._keyword_query.assert_called_once()
        assert "window=7d+1 " in caplog.text and "recent=3d " in caplog.text

    def test_the_window_keeps_the_readers_topic(self):
        qp = _qp(semantic=[self._dated(1, 2, 0.80)])
        qp.candidates("IHSG pekan ini?", Filters(topic="markets"), TODAY)
        windowed = qp._fts_search.call_args_list[0].args[2]
        assert windowed == Filters(topic="markets", days=7)

    @pytest.mark.parametrize("filters", [Filters(date_from=date(2026, 9, 1)),
                                         Filters(date_to=date(2026, 9, 30)),
                                         Filters(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))])
    def test_a_readers_picked_dates_win(self, filters):
        """QA mutant qa1012b_picked_dates_ignored: only the `days` chip was covered."""
        qp = _qp(semantic=[self._dated(1, 24, 0.85), self._dated(2, 4, 0.70)])
        _, counts = qp.candidates("Apa perkembangan kasus KPK minggu ini?", filters, TODAY)
        assert counts["window"] is None
        assert qp.faiss_ds.search_l2.call_count == 1

    def test_below_floor_week_hits_do_not_make_a_full_week(self):
        """QA mutant qa1012b_window_leads_below_floor: four of five this-week hits are below the
        floor, so the week is thin and an older relevant article fills."""
        week = [self._dated(1, 1, 0.70)] + [self._dated(i, i, 0.05) for i in range(2, 6)]
        qp = _qp(semantic=week + [self._dated(9, 20, 0.90)])
        hits = qp.retrieve("Bagaimana kinerja IHSG pekan ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [1, 9]


def _off_subject(*ids):
    """A `subject` stub: the texts of these sitemaps do not hold the question's subject. Texts are
    tagged with their sitemap id by `_tagged`."""
    return lambda kq, texts: [not any(t.endswith(f"#{i}") for i in ids) for t in texts]


def _tagged(hit):
    return dict(hit, text_content=f"{PARA} #{hit['sitemap_id']}")


class TestWeekWindowSubjectGate:
    """SYS-138 sent back (QA 2026-10-12), ADR-013: on a thin week the window led with any paragraph
    over the floor. 'Apa kabar Danantara pekan ini?' got a Primbon piece of 6 Oct as card 1 (semantic
    0.558, none of the question's words) above Danantara articles (semantic 0.25, coverage 1.0)."""

    _dated = staticmethod(TestWeekWindow._dated)

    def _danantara(self, subject):
        week = _tagged(self._dated(1, 6, 0.558))                        # FAISS only, the Primbon piece
        older = dict(self._dated(2, 11, 0.0), keyword_score=1.0)       # the keyword half found it
        return _qp(semantic=[week], fts=[older], subject=subject,
                   similarity=lambda q, texts, ids=None: [0.249] * len(texts))

    def test_a_this_week_paragraph_without_the_subject_does_not_lead(self):
        qp = self._danantara(subject=_off_subject(1))
        hits = qp.retrieve("Apa kabar Danantara pekan ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [2, 1]

    def test_it_is_not_dropped_and_the_log_counts_no_leader(self, caplog):
        """A gate on the lead, not a filter: the paragraph still passes the floor and still shows,
        where its score puts it without the window."""
        qp = self._danantara(subject=_off_subject(1))
        with caplog.at_level(logging.INFO, logger="newscrawler.web.query_processor"):
            hits = qp.retrieve("Apa kabar Danantara pekan ini?", Filters(), TODAY)
        assert 1 in [h["sitemap_id"] for h in hits]
        assert "window=7d+0 " in caplog.text

    def test_the_same_paragraph_holding_the_subject_leads(self):
        qp = self._danantara(subject=_off_subject())
        assert [h["sitemap_id"] for h in qp.retrieve("Apa kabar Danantara pekan ini?", Filters(), TODAY)][0] == 1

    def test_only_semantic_only_hits_over_the_floor_are_tested(self):
        """A keyword hit holds the subject by the FTS rule; a below-floor hit cannot lead anyway."""
        both = _tagged(self._dated(3, 2, 0.70))
        qp = _qp(semantic=[_tagged(self._dated(1, 2, 0.70)), _tagged(self._dated(4, 3, 0.05)), both],
                 fts=[dict(both, keyword_score=1.0), dict(_tagged(self._dated(5, 1, 0.0)), keyword_score=1.0)])
        qp.candidates("Bagaimana kinerja IHSG pekan ini?", Filters(), TODAY)
        tested = [t for call in qp._holds_subject.call_args_list for t in call.args[1]]
        assert tested == [f"{PARA} #1"]

    def test_only_leaders_count_toward_a_full_week(self):
        """Five this-week paragraphs over the floor, four off the subject: the week is thin, so the
        older on-subject article fills, after the one leader."""
        week = [_tagged(self._dated(i, i, 0.70)) for i in range(1, 6)]
        qp = _qp(semantic=week + [_tagged(self._dated(9, 20, 0.95))], subject=_off_subject(2, 3, 4, 5))
        _, counts = qp.candidates("Bagaimana kinerja IHSG pekan ini?", Filters(), TODAY)
        assert counts["window"] == "7d+1"
        assert [h["sitemap_id"] for h in qp.retrieve("Bagaimana kinerja IHSG pekan ini?", Filters(), TODAY)][:2] == [1, 9]

    def test_a_full_week_puts_every_leader_before_an_off_subject_paragraph(self):
        week = [_tagged(self._dated(i, 3, 0.70)) for i in range(1, 6)]
        loud = _tagged(self._dated(6, 1, 0.95))              # fresher and closer, but off the subject
        qp = _qp(semantic=[loud] + week, subject=_off_subject(6))
        hits = qp.retrieve("Bagaimana kinerja IHSG pekan ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [1, 2, 3, 4, 5]
        assert qp.faiss_ds.search_l2.call_count == 1      # a full week needs no second retrieval

    def test_without_a_keyword_query_the_floor_decides(self):
        qp = _qp(semantic=[self._dated(1, 2, 0.70), self._dated(2, 20, 0.90)],
                 subject=lambda kq, texts: [False] * len(texts))
        qp._keyword_query = MagicMock(return_value=None)
        hits = qp.retrieve("Apa yang terjadi pekan ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [1, 2]
        qp._holds_subject.assert_not_called()

    def test_if_the_subject_test_fails_no_unchecked_paragraph_leads(self, caplog):
        def boom(kq, texts):
            raise RuntimeError("db down")
        qp = self._danantara(subject=boom)
        with caplog.at_level(logging.WARNING, logger="newscrawler.web.query_processor"):
            hits = qp.retrieve("Apa kabar Danantara pekan ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [2, 1]
        assert "Subject test of the window's hits failed: RuntimeError: db down" in caplog.text


class TestTheRewriterFromConfig:
    """ADR-010: left out, the rewriter is RAG_LLM_PROVIDER's with the rewrite's short timeout, no SDK
    retry and no wait on a rate limit."""

    def test_built_with_the_rewrite_options(self, monkeypatch):
        calls = []
        monkeypatch.setattr(qp_mod, "build_summarizer", lambda **kw: calls.append(kw) or MagicMock())
        QueryProcessor(MagicMock(), MagicMock(), summarizer=None, usage=MagicMock())
        rewrite, = [c for c in calls if c.get("max_retries") == 0]
        assert rewrite["timeout_s"] == qp_mod.RAG_REWRITE_TIMEOUT_S == 6
        assert rewrite["max_tokens"] == qp_mod.RAG_REWRITE_MAX_TOKENS
        assert rewrite["provider"] == qp_mod.RAG_LLM_PROVIDER
        with pytest.raises(SummarizerError):
            rewrite["sleep"](30)


class TestFollowUpKeywordNames:
    """SYS-140 (#322), the composed path: the fallback's thread reaches the real `_keyword_query`. An
    earlier question's capitalised first word ('Kebijakan', df 4.8%) is not a name, so it is not
    required in every keyword hit; a real name in the thread ('OJK') still is one."""

    def test_names_are_judged_per_question(self):
        qp = QueryProcessor.__new__(QueryProcessor)
        qp.keyword_df = MagicMock()
        qp.keyword_df.get.side_effect = lambda words: {w: 0.048 for w in words}
        kq = qp._keyword_query("Apa dampaknya ke kredit?", "Kebijakan OJK soal suku bunga?")
        assert "kebijakan" not in kq.names
        assert "ojk" in kq.names


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
