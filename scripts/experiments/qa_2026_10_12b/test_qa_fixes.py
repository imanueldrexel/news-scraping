"""QA 2026-10-12, second pass: QA's own tests for the dev's fixes of SYS-111, SYS-139, SYS-104/140,
SYS-141 and SYS-138, written from each ticket's Done-when and ADR rather than from the dev's tests.

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_12b/test_qa_fixes.py -q -p no:cacheprovider

No DB, no network, no model call. The SYS-139 worker tests spawn a real SourceWorker child.
"""
import os
import sys
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from newscrawler.core.summarizer import Reply  # noqa: E402
from newscrawler.web import followup, keywords  # noqa: E402
from newscrawler.web.filters import Filters  # noqa: E402
from tests.unit.test_query_processor_ranking import TODAY, _hit, _qp, _usage  # noqa: E402


# ── SYS-139 (#320): the soft deadline, through the real worker and its kill ─────────────────────

class TestSys139RealWorkerKill:
    """Done-when: "a fake source whose batches would cross the deadline flushes its vectors and exits
    cleanly before the kill". The dev's tests check the loop with a fake clock and the deadline value
    the child computes, separately. This runs both together: the real worker, the real timeout and
    kill, the real CrawlerAPI and batch loop. 10 batches of 0.6 s take 6 s, and the timeout is 4 s."""

    @pytest.fixture(autouse=True)
    def _env(self, tmp_path, monkeypatch):
        self.marker = tmp_path / "flush.txt"
        monkeypatch.setenv("QA_FLUSH_MARKER", str(self.marker))
        monkeypatch.setenv("QA_BATCH_S", "0.6")

    def _run(self, margin):
        import qa_worker_stubs
        from newscrawler.tools.source_worker import SourceWorker
        w = SourceWorker(factory=qa_worker_stubs.soft_deadline_factory, init_timeout=120, soft_margin_s=margin)
        try:
            return w.run("VIVA", "full_text", timeout=4)
        finally:
            w.close()

    def test_with_the_margin_the_run_completes_and_flushes_before_the_kill(self):
        status, _ = self._run(margin=1.5)
        assert status == "ok"
        assert self.marker.read_text() == "flushed\n"

    def test_control_without_a_margin_the_same_run_is_killed_and_never_flushes(self):
        """Proves the fixture: the same source without a soft deadline is the incident."""
        status, _ = self._run(margin=None)
        assert status == "timeout"
        assert not self.marker.exists()


class TestSys139Boundary:
    """'would cross the deadline': a batch that ends exactly at it does not cross it."""

    def _service(self, n_rows=100, batch_s=100.0):
        sys.path.insert(0, os.path.join(ROOT, "tests", "unit"))
        from test_soft_deadline import _Clock, _rows, _service
        clock = _Clock()
        svc, offered = _service(_rows(n_rows), clock, [batch_s] * 10)
        return svc, offered, clock

    def test_a_batch_that_ends_exactly_at_the_deadline_still_runs(self):
        svc, offered, clock = self._service()
        svc.crawl_newsdetails("VIVA", deadline=clock.now + 500)
        assert len(offered) == 5

    def test_a_deadline_after_the_last_batch_leaves_no_note(self):
        svc, offered, clock = self._service()
        svc.crawl_newsdetails("VIVA", deadline=clock.now + 1000)
        assert len(offered) == 10
        assert svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"] is None

    def test_the_note_counts_the_rows_left(self):
        """95 rows make 10 batches of 10 (the last holds 5): stopping before batch 5 leaves 55."""
        svc, offered, clock = self._service(n_rows=95)
        svc.crawl_newsdetails("VIVA", deadline=clock.now + 450)
        note = svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert len(offered) == 4 and "55 rows left for the next run" in note, note


# ── SYS-104 (#274) / SYS-140 (#322), ADR-010 ──────────────────────────────────────────────────────

OJK = [{"question": "Apa kata OJK soal kredit perbankan?", "answer": "-"}]


class _Rewriter:
    name = "deepseek-v4-flash"
    priced = True

    def __init__(self, text):
        self.text, self.prompts = text, []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return Reply(self.text, 150, 20)


def _processor(rewriter):
    qp = _qp(semantic=[_hit(1, semantic=0.9)], fts=[_hit(2, keyword=1.0)])
    qp.rewriter = rewriter
    qp.usage = _usage(0.0)
    return qp


class TestSys104RewriteCheck:
    """ADR-010 decision 3: 'It must be one line, non-empty, at most 300 chars, and must not be a
    refusal or a list.' A refusal is one short line, so only an explicit check stops it."""

    @pytest.mark.parametrize("reply", [
        "Maaf, saya tidak dapat menulis ulang pertanyaan tersebut.",
        "Maaf, saya tidak bisa membantu dengan permintaan ini.",
    ])
    def test_a_refusal_is_not_used_as_the_query(self, reply):
        assert followup.check(reply) is None

    def test_a_refusal_falls_back_instead_of_being_searched(self):
        qp = _processor(_Rewriter("Maaf, saya tidak dapat menulis ulang pertanyaan tersebut."))
        _, counts = qp.candidates("Berapa target pertumbuhannya tahun depan?", Filters(), TODAY, OJK)
        assert counts["rewrite"] == "fallback-thread", qp.faiss_ds.search_l2.call_args.args[0]

    @pytest.mark.parametrize("reply, expected", [
        ('Pertanyaan: "Apa itu Danantara?"', "Apa itu Danantara?"),
        ("“Berapa target kredit OJK?”", "Berapa target kredit OJK?"),
        ("Berapa target kredit OJK?\n", "Berapa target kredit OJK?"),
    ])
    def test_labels_quotes_and_a_trailing_newline_are_stripped(self, reply, expected):
        assert followup.check(reply) == expected

    def test_an_unusable_reply_is_still_counted_against_the_cap(self):
        """ADR-010 decision 7: the call is counted. A reply that fails the check was still paid for."""
        qp = _processor(_Rewriter("satu\ndua"))
        _, counts = qp.candidates("Apa dampaknya ke kredit?", Filters(), TODAY, OJK)
        assert counts["rewrite"] == "fallback-thread"
        qp.usage.increment_api_call_count.assert_called_once()
        assert qp.usage.increment_api_call_count.call_args.kwargs["input_tokens"] == 150

    def test_a_reply_over_300_chars_is_not_used(self):
        assert followup.check("a" * 301) is None
        assert followup.check("a" * 300) == "a" * 300


class TestSys104FallbackNamesItsOwnSubject:
    """QA's amended Done-when: 'a follow-up that names its own subject retrieves on its own words'.
    On the fallback path (no key, cap, timeout: the SumoPod key was blocked 10-08..10-12) the rule is
    a '-nya' word. Common Indonesian adverbs end in -nya without pointing back."""

    @pytest.mark.parametrize("question", [
        "Apa yang sebenarnya terjadi pada Garuda Indonesia?",
        "Bagaimana nasib Sritex selanjutnya?",
        "Apakah harga emas biasanya naik menjelang Lebaran?",
        "Siapa saja tersangka korupsi timah, misalnya?",
        "Apakah Danantara akhirnya membeli saham Garuda?",
    ])
    def test_an_adverb_ending_in_nya_is_not_a_back_reference(self, question):
        assert not followup.refers_back(question)

    @pytest.mark.parametrize("question", [
        "Berapa target pertumbuhannya tahun depan?", "Apa dampaknya ke kredit?",
        "Siapa yang menunjuk dia?", "Kapan aturan tersebut berlaku?",
    ])
    def test_a_real_back_reference_still_is(self, question):
        assert followup.refers_back(question)


class TestSys140TicketExample:
    """Done-when: 'the example above gives names == []' (df values from the ticket, production)."""

    DF = {"targetnya": 0.0006, "depan": 0.0487, "kebijakan": 0.0481, "subsidi": 0.0091, "energi": 0.036,
          "pemerintah": 0.1348, "tahun": 0.2}

    def test_the_threads_first_word_is_not_a_name(self):
        ts = keywords.terms("Berapa targetnya tahun depan?", "Kebijakan subsidi energi pemerintah")
        kq = keywords.KeywordQuery.build(ts, self.DF)
        assert kq.names == []
        assert "kebijakan" not in kq.anchors

    def test_a_real_name_in_the_thread_stays_a_name(self):
        ts = keywords.terms("Berapa targetnya tahun depan?", "Apa kata OJK soal kredit?")
        assert {t.word for t in ts if t.name} == {"ojk"}

    def test_a_name_past_the_first_word_of_a_later_question_is_still_a_name(self):
        ts = keywords.terms("Apa dampaknya?", "Bagaimana sikap Purbaya soal cukai?")
        assert {t.word for t in ts if t.name} == {"purbaya"}


# ── SYS-141 (#323) ────────────────────────────────────────────────────────────────────────────────

class TestSys141ReloadDuringTheEmbedding:
    """The dev's test swaps the index inside the position lookup. The slowest step of similarity()
    is the query embedding (~25 ms), so a reload is likeliest there; both reads must still come from
    the index the call started with."""

    def test_a_reload_while_the_query_is_embedded(self):
        from langchain_community.vectorstores import FAISS
        sys.path.insert(0, os.path.join(ROOT, "tests", "unit"))
        from test_faiss_search_score import TestSimilarityOfKeywordOnlyParagraphs
        ds, emb = TestSimilarityOfKeywordOnlyParagraphs()._ds()
        reloaded = FAISS.from_texts(["far", "near"], emb, ids=["id-far", "id-near"])
        embed_query = emb.embed_query

        def embed_then_reload(text):
            ds.vs_l2 = reloaded
            return embed_query(text)
        emb.embed_query = embed_then_reload
        ds.__dict__.pop("_positions", None)
        assert ds.similarity("q", ["near"], ["id-near"]) == [pytest.approx(0.6 ** 0.5)]

    def test_the_docstring_no_longer_states_the_removed_formula(self):
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource)
        doc = ChunkFAISSDatasource.similarity.__doc__
        assert "d^2/2" not in doc and "1 - d/2" in doc


# ── SYS-138 (#317), ADR-012 ───────────────────────────────────────────────────────────────────────

def _dated(sid, days_old, semantic):
    d = TODAY - timedelta(days=days_old)
    return _hit(sid, semantic=semantic, posted_at=d.strftime("%Y%m%d"), posted_date=d)


class TestSys138WeekWindow:
    def test_the_tickets_unit_test(self):
        """'with a "minggu ini" cue, a 3-day-old paragraph at semantic 0.70 outranks a 20-day-old one
        at 0.80'."""
        qp = _qp(semantic=[_dated(1, 20, 0.80), _dated(2, 3, 0.70)])
        assert [h["sitemap_id"] for h in qp.retrieve("KPK minggu ini?", Filters(), TODAY)][:2] == [2, 1]

    @pytest.mark.parametrize("filters", [Filters(date_from=date(2026, 9, 1)),
                                         Filters(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)),
                                         Filters(date_to=date(2026, 9, 30))])
    def test_a_readers_picked_date_wins_over_the_window(self, filters):
        qp = _qp(semantic=[_dated(1, 24, 0.85), _dated(2, 4, 0.70)])
        _, counts = qp.candidates("Apa perkembangan kasus KPK minggu ini?", filters, TODAY)
        assert counts["window"] is None

    def test_a_thin_week_leads_and_older_articles_fill_without_duplicates(self):
        qp = _qp(semantic=[_dated(1, 2, 0.70), _dated(2, 30, 0.90), _dated(3, 40, 0.88)])
        hits = qp.retrieve("Bagaimana kinerja IHSG pekan ini?", Filters(), TODAY)
        ids = [h["sitemap_id"] for h in hits]
        assert ids[0] == 1 and sorted(ids) == [1, 2, 3] and len(ids) == len(set(ids))

    def test_a_week_with_nothing_relevant_falls_back_to_the_whole_corpus(self):
        """A this-week paragraph below the floor must not lead: the window only prefers what passes."""
        qp = _qp(semantic=[_dated(1, 2, 0.05), _dated(2, 30, 0.90)])
        hits = qp.retrieve("Bagaimana kinerja IHSG pekan ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [2]

    def test_below_floor_week_hits_do_not_count_toward_a_full_week(self):
        """Five this-week hits, four of them below the floor: the week is thin, so older ones fill."""
        week = [_dated(1, 1, 0.70)] + [_dated(i, i, 0.05) for i in range(2, 6)]
        qp = _qp(semantic=week + [_dated(9, 20, 0.90)])
        hits = qp.retrieve("Bagaimana kinerja IHSG pekan ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits] == [1, 9]

    def test_a_keywordless_week_paragraph_does_not_lead_a_relevant_older_one(self):
        """QA's send-back (production 2026-10-12, 'Apa kabar Danantara pekan ini?'): a Primbon piece of
        6 Oct (semantic 0.558, coverage 0) led the Danantara articles (semantic 0.25, coverage 1.0)."""
        week = _dated(1, 6, 0.558)
        older = dict(_dated(2, 11, 0.249), keyword_score=1.0)
        qp = _qp(semantic=[week, older])
        hits = qp.retrieve("Apa kabar Danantara pekan ini?", Filters(), TODAY)
        assert [h["sitemap_id"] for h in hits][0] == 2

    @pytest.mark.parametrize("question", ["Apa kabar IHSG pekan lalu?", "Apa yang terjadi minggu lalu?",
                                          "Bagaimana IHSG bulan ini?"])
    def test_other_periods_get_no_week_window(self, question):
        qp = _qp(semantic=[_dated(1, 24, 0.85)])
        _, counts = qp.candidates(question, Filters(), TODAY)
        assert counts["window"] is None
