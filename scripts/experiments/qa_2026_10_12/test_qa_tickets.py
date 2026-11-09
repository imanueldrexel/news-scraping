"""QA 2026-10-12: QA's own tests for the 2026-10-08/09 ready-for-qa tickets, written from each
ticket's description rather than from the dev's tests. Offline (no DB, no network) except
TestSys110RealEncoder, which loads the cached MiniLM.

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_12 -q -p no:cacheprovider

Expected: TestSys111DeadlineResolvedOnce fails on 1c45a65 (SYS-111 sent back); everything else passes.
"""
import os
import sys
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))


# --- SYS-111: --until is one deadline for the whole run ---------------------------------------

class _Clock:
    """A fake `datetime` for the repair module: now() returns the next scripted time."""
    def __init__(self, times):
        self.times = list(times)
        self.last = self.times[0]

    def now(self, tz=None):
        if self.times:
            self.last = self.times.pop(0)
        return self.last


class TestSys111DeadlineResolvedOnce:
    """The ticket: 'parse_until resolves to the next occurrence of HH:MM'. A run started at 06:00
    with --until 06:20 must stop starting blocks at 06:20 today, however long its backup, deletes
    and rewrite take. The deadline is resolved again after them (repair_boilerplate_bodies
    _apply_locked: once for too_close, once for rechunk): if the rewrite ends at 06:25, '06:20'
    then means tomorrow and the re-chunk runs on under the run lock."""

    def test_the_rechunk_gets_the_deadline_the_run_started_with(self, monkeypatch):
        import repair_boilerplate_bodies as rb
        real_datetime = rb.datetime
        start = datetime(2026, 10, 12, 6, 0)
        after_rewrite = datetime(2026, 10, 12, 6, 25)

        class FakeDT(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.now(tz) if tz is None else real_datetime.now(tz)
        clock = _Clock([start, start, after_rewrite])  # parse_until + too_close at the start
        monkeypatch.setattr(rb, "datetime", FakeDT)

        seen = {}
        monkeypatch.setattr(rb, "_faiss_dirs", lambda: {})
        monkeypatch.setattr(rb, "_crawl_running", lambda s: 0)
        monkeypatch.setattr(rb, "select_targets", lambda rows: [(1, "body")])
        monkeypatch.setattr(rb, "backup", lambda *a, **k: "b")
        monkeypatch.setattr(rb, "delete_vectors", lambda *a, **k: {})
        monkeypatch.setattr(rb, "rewrite_rows", lambda s, t: (0, 0, 0, 1))
        monkeypatch.setattr(rb, "_notify", lambda m: None)

        def fake_rechunk(client, source, block, deadline, make_repo=None, **k):
            seen["deadline"] = deadline
            return 1, 0, 0, 0
        monkeypatch.setattr(rb, "rechunk", fake_rechunk)

        class _Sess:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, *a, **k):
                return SimpleNamespace(scalar=lambda: "newsaggregator_test", fetchall=lambda: [])
        client = SimpleNamespace(get_session=lambda: _Sess())
        args = SimpleNamespace(rechunk_only=False, until="06:20", block=1000)
        rb._apply_locked(args, "X", client, None)
        assert seen["deadline"] == datetime(2026, 10, 12, 6, 20), (
            "the re-chunk's deadline moved to %s: the run would not stop at 06:20" % seen["deadline"])

    @pytest.mark.parametrize("value", ["24:00", "6:60", "06:15:00", "0615", "-1:00"])
    def test_a_malformed_until_fails_before_any_write(self, value, monkeypatch):
        import repair_boilerplate_bodies as rb
        monkeypatch.setattr(rb, "_faiss_dirs", lambda: {})
        wrote = []
        monkeypatch.setattr(rb, "backup", lambda *a, **k: wrote.append("backup"))
        monkeypatch.setattr(rb, "delete_vectors", lambda *a, **k: wrote.append("vectors"))
        with pytest.raises(ValueError):
            rb._apply_locked(SimpleNamespace(rechunk_only=False, until=value, block=1), "X", None, None)
        assert wrote == []

    def test_midnight_and_the_current_minute(self):
        from repair_boilerplate_bodies import parse_until
        now = datetime(2026, 10, 12, 23, 59, 30)
        assert parse_until("00:00", now) == datetime(2026, 10, 13, 0, 0)
        assert parse_until("23:59", now) == datetime(2026, 10, 13, 23, 59)  # this minute is gone


# --- SYS-107: recency cues ---------------------------------------------------------------------

class TestSys107RecencyCue:
    @pytest.mark.parametrize("q", [
        "Bagaimana kinerja IHSG?",                   # 'kini' inside 'kinerja'
        "Apa kabar energi terbarukan?",              # 'terbaru' inside 'terbarukan'
        "Berapa harga sehari-hari beras?",
        "Kapan hari raya Idul Adha?",
        "Siapa yang menang pada Minggu (11/10)?",
    ])
    def test_no_cue_inside_other_words(self, q):
        from newscrawler.web.keywords import recency_cue
        assert recency_cue(q) is None

    @pytest.mark.parametrize("q,days", [
        ("BERAPA HARGA EMAS HARI INI?", 1),
        ("Harga emas hari  ini berapa?", 1),
        ("Siapa Menkeu saat ini", 1),
        ("Apa yang terjadi minggu ini di DPR?", 3),
        ("Berita terkini soal banjir", 7),
        ("Berapa harga emas hari ini dan pekan ini?", 1),   # the most precise cue wins
    ])
    def test_cues(self, q, days):
        from newscrawler.web.keywords import recency_cue
        assert recency_cue(q).days == days

    def test_recency_is_one_today_and_halves_at_the_horizon(self):
        from newscrawler.web.query_processor import recency
        today = date(2026, 10, 12)
        assert recency(today, today, 1) == 1.0
        assert recency(today - timedelta(days=1), today, 1) == 0.5
        assert recency(today - timedelta(days=3), today, 3) == 0.5
        assert 0.0 <= recency(today - timedelta(days=400), today) <= 1.0


# --- SRC-60: KUMPARAN newsroom accounts --------------------------------------------------------

class TestSrc60Accounts:
    @pytest.fixture(scope="class")
    def crawler(self):
        from newscrawler.infrastructure.datasource.scrapers.kumparan.kumparan_crawler import KumparanCrawler
        return KumparanCrawler()

    @pytest.mark.parametrize("link", [
        "https://kumparan.com/kumparannews/prabowo-x-1abc",
        "https://kumparan.com/kumparanbisnis/ihsg-x",
        "https://m.kumparan.com/kumparantech/x",
        "http://kumparan.com/kumparanoto/x?utm=1",
        "https://kumparan.com/KumparanNews/x",
        "https://kumparan.com/pandangan-jogja/x",
    ])
    def test_newsroom_kept(self, crawler, link):
        assert crawler.out_of_scope_reason(link) is None

    @pytest.mark.parametrize("link", [
        "https://kumparan.com/tasya-anggun/reshuffle-x",
        "https://kumparan.com/user-13082024092310/reforma-x",
        "https://kumparan.com/rizki-ramadhan-1748509645358112336/strategi-x",
        "https://kumparan.com/TDA/x",
        "https://kumparan.com/daily-tech-science/x",
        "https://kumparan.com/kumparan2/x",
        "",
        None,
    ])
    def test_reader_and_partner_posts_dropped(self, crawler, link):
        assert crawler.out_of_scope_reason(link)

    def test_other_crawlers_drop_nothing_by_url(self):
        from newscrawler.core.crawler_dict_list import CRAWLER_DICT
        kept = [n for n, c in CRAWLER_DICT.items()
                if n != "KUMPARAN" and c.out_of_scope_reason("https://example.com/user-1/x") is not None]
        assert kept == [] or all(n in ("KUMPARAN",) for n in kept), kept


# --- SYS-108: a zero document frequency is counted again ----------------------------------------

class TestSys108ZeroNotCached:
    def _df(self, counts_by_call):
        from newscrawler.web import keywords
        df = keywords.DocFrequency(client=None, ttl_s=86400, clock=lambda: 0.0)
        df._loaded_at, df._total, df._common = 0.0, 1000, {}
        calls = []

        def count(words):
            calls.append(tuple(words))
            return {w: counts_by_call[len(calls) - 1].get(w, 0.0) for w in words}
        df._count = count
        return df, calls

    def test_zero_then_present_then_cached(self):
        df, calls = self._df([{"danantara": 0.0}, {"danantara": 0.025}, {}])
        assert df.get(["danantara"]) == {"danantara": 0.0}
        assert df.get(["danantara"]) == {"danantara": 0.025}
        assert df.get(["danantara"]) == {"danantara": 0.025}
        assert len(calls) == 2, "the non-zero count is cached"

    def test_a_mixed_question_recounts_only_the_zero(self):
        df, calls = self._df([{"ojk": 0.01, "purbayax": 0.0}, {"purbayax": 0.0}])
        df.get(["ojk", "purbayax"])
        df.get(["ojk", "purbayax"])
        assert calls == [("ojk", "purbayax"), ("purbayax",)]


# --- SYS-104: the follow-up's retrieval text ----------------------------------------------------

class TestSys104RetrievalText:
    def test_own_words_first_then_newest_two(self):
        from newscrawler.web.query_processor import retrieval_text
        h = [{"question": "q1"}, {"question": "q2"}, {"question": "q3"}]
        assert retrieval_text("f", h) == "f q3 q2"

    def test_blank_questions_in_the_thread_are_skipped(self):
        from newscrawler.web.query_processor import retrieval_text
        assert retrieval_text(" f ", [{"question": "  "}, {"question": None}, {}, {"question": "q"}]) == "f q"

    def test_the_search_box_retrieves_on_its_own_text(self):
        from newscrawler.web.query_processor import retrieval_text
        assert retrieval_text("Apa itu Danantara?") == "Apa itu Danantara?"

    def test_sessions_do_not_share_a_thread(self):
        from newscrawler.web.session_manager import SessionManager
        sm = SessionManager()
        a, b = sm.new_session_id(), sm.new_session_id()
        sm.record_question(a, "OJK kredit")
        assert sm.get_questions(b) == [] and sm.get_questions(None) == []


# --- SYS-105: the trailing sign-off under SYS-109's windows --------------------------------------

def _l2(paragraphs):
    from newscrawler.core.chunker import HierarchicalChunker
    from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
    news = NewsDetailsDTO(sitemap_id=1, extracted_text=paragraphs, reporter=[], meta_data={"title": "t"})
    return [c for c in HierarchicalChunker().chunk(news) if c.chunk_level == 2]


def _w(n, p="w"):
    return " ".join(f"{p}{i}" for i in range(n))


class TestSys105And109Chunks:
    @pytest.mark.parametrize("paras", [
        [_w(80), "(jon)"], [_w(79), _w(9, "t")], [_w(200), "Editor: Theresa Sandra"],
        [_w(150), _w(39, "t")], [_w(45), _w(45, "b"), "( )"], [_w(100), "Baca", _w(100, "b")],
    ])
    def test_no_sign_off_chunk_no_window_over_80_nothing_lost(self, paras):
        cs = _l2(paras)
        assert all(c.token_count <= 80 for c in cs)
        assert all(c.token_count >= 15 for c in cs), [c.token_count for c in cs]
        assert set(" ".join(paras).split()) <= set(" ".join(c.text_content for c in cs).split())

    def test_a_one_paragraph_article_keeps_its_short_chunk(self):
        assert [c.token_count for c in _l2(["Singkat saja."])] == [2]


# --- SYS-110: the score is the cosine, on the real encoder ---------------------------------------

class TestSys110RealEncoder:
    def test_search_l2_score_equals_the_dot_product_of_the_real_embeddings(self):
        import numpy as np
        from langchain_community.vectorstores import FAISS
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource)
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from newscrawler.core.constants import EMBEDDING_MODEL_HF
        emb = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_HF, encode_kwargs={"normalize_embeddings": True})
        texts = ["Bank Indonesia menahan BI-Rate di 5,75 persen.", "Harga emas Antam naik Rp10.000 hari ini.",
                 "Timnas Indonesia menang 2-0 atas Vietnam."]
        ds = ChunkFAISSDatasource.__new__(ChunkFAISSDatasource)
        ds.vs_l2 = FAISS.from_texts(texts, emb, metadatas=[{"sitemap_id": i} for i in range(3)])
        q = "Apa keputusan BI soal suku bunga?"
        qv = np.array(emb.embed_query(q))
        for hit in ds.search_l2(q, k=3):
            tv = np.array(emb.embed_documents([hit["text_content"]])[0])
            # the ticket's formula is max(0, cosine): an unrelated text (cos -0.06) reads 0
            assert abs(hit["semantic_score"] - max(0.0, float(qv @ tv))) < 1e-4, hit
