"""SYS-147 (#337): a top story's past coverage from NEWS_L1, and DBT-74 (#346):
the newsletter's own composition root and its crawl_log bracket.

The finder retrieves wide (the arc writer decides membership, ADR-016); what it
guarantees is tested here: no peeking past the date, one item per day, the
earliest day kept, headlines from the database, bylines stripped."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import newscrawler.core.thread_finder as tf
from newscrawler.application import newsletter_app
from newscrawler.infrastructure.datasource.dataflow.write.faiss.l1_search import l1_search, posted_at_int

DAY = date(2026, 10, 12)


def _search(hits):
    calls = []

    def search(vector, k):
        calls.append((list(vector), k))
        return list(hits)
    search.calls = calls
    return search


def _lookup(ids_seen=None):
    def lookup(ids):
        ids = list(ids)
        if ids_seen is not None:
            ids_seen.append(sorted(ids))
        return {i: {"headline": f"Judul {i}", "source": "KONTAN", "posted_at": 0, "l1_text": f"Isi berita {i}."}
                for i in ids}
    return lookup


class TestFindThread:
    def test_window_is_the_days_before_the_date_and_never_the_date_or_later(self):
        hits = [(1, 20260912, 0.9),          # exactly 30 days before: in
                (2, 20260911, 0.95),         # 31 days before: out
                (3, 20261012, 0.99),         # the story's own day: out (no peeking)
                (4, 20261013, 0.99),         # later: out (a replay must not see it)
                (5, 20261011, 0.8)]
        items = tf.find_thread([0.1], DAY, [], _search(hits), _lookup(), days=30)
        assert [i.sitemap_id for i in items] == [1, 5]

    def test_items_under_the_floor_are_left_out(self):
        items = tf.find_thread([0.1], DAY, [], _search([(1, 20261005, 0.69), (2, 20261006, 0.70)]), _lookup(),
                               floor=0.70)
        assert [i.sitemap_id for i in items] == [2]

    def test_one_item_per_day_the_nearest_with_the_days_volume(self):
        hits = [(1, 20261005, 0.80), (2, 20261005, 0.90), (3, 20261005, 0.75), (4, 20261006, 0.85)]
        items = tf.find_thread([0.1], DAY, [], _search(hits), _lookup())
        assert [(i.sitemap_id, i.day_volume) for i in items] == [(2, 3), (4, 1)]

    def test_todays_own_articles_and_repeats_are_excluded(self):
        hits = [(1, 20261005, 0.99), (2, 20261005, 0.80), (2, 20261005, 0.80)]
        items = tf.find_thread([0.1], DAY, [1], _search(hits), _lookup())
        assert [(i.sitemap_id, i.day_volume) for i in items] == [(2, 1)]

    def test_the_nearest_days_are_kept_and_the_earliest_day_always(self):
        hits = [(10 + d, 20261000 + d, 0.70 + d / 100) for d in range(1, 11)]   # 1-10 Oct, nearer when later
        items = tf.find_thread([0.1], DAY, [], _search(hits), _lookup(), max_items=3)
        assert [i.day for i in items] == [date(2026, 10, 1), date(2026, 10, 9), date(2026, 10, 10)]

    def test_chronological_with_database_fields(self):
        hits = [(7, 20261008, 0.81234), (3, 20260930, 0.9)]
        items = tf.find_thread([0.1], DAY, [], _search(hits), _lookup())
        assert items == [tf.TimelineItem(3, date(2026, 9, 30), "KONTAN", "Judul 3", "Isi berita 3.", 0.9, 1),
                         tf.TimelineItem(7, date(2026, 10, 8), "KONTAN", "Judul 7", "Isi berita 7.", 0.8123, 1)]

    def test_a_vector_without_an_article_row_is_dropped(self):
        def lookup(ids):
            return {5: {"headline": "Ada", "source": "CNBC", "posted_at": 20261005, "l1_text": "x"}}
        items = tf.find_thread([0.1], DAY, [], _search([(5, 20261005, 0.9), (6, 20261006, 0.9)]), lookup)
        assert [i.sitemap_id for i in items] == [5]

    def test_lookup_is_asked_only_for_the_kept_items(self):
        seen = []
        hits = [(1, 20261005, 0.80), (2, 20261005, 0.90), (3, 20261006, 0.85)]
        tf.find_thread([0.1], DAY, [], _search(hits), _lookup(seen))
        assert seen == [[2, 3]]

    def test_nothing_near(self):
        assert tf.find_thread([0.1], DAY, [], _search([]), _lookup()) == []

    def test_the_search_gets_fetch_k(self):
        search = _search([])
        tf.find_thread([0.5, 0.5], DAY, [], search, _lookup(), fetch_k=123)
        assert search.calls == [([0.5, 0.5], 123)]


class TestOpening:
    def test_a_leading_byline_is_stripped(self):
        text = "Reporter: Vivit Dewi | Editor: Tri Sulistiowati\nKONTAN.CO.ID - JAKARTA. Indeks Harga Saham turun."
        assert tf.opening(text) == "KONTAN.CO.ID - JAKARTA. Indeks Harga Saham turun."

    def test_two_byline_lines(self):
        assert tf.opening("Penulis: A\nEditor: B\nIsi berita.") == "Isi berita."

    def test_a_byline_word_inside_the_text_is_kept(self):
        assert tf.opening("Kata Reporter: dia datang.") == "Kata Reporter: dia datang."

    def test_cut_at_a_word(self):
        out = tf.opening("kata " * 100)
        assert len(out) <= tf.OPENING_CHARS + 1 and out.endswith("kata…")


class TestL1Search:
    def test_cosine_ids_and_dates_from_the_store(self):
        docs = [(SimpleNamespace(metadata={"sitemap_id": "12", "posted_at": 20261005}), 0.4),
                (SimpleNamespace(metadata={"sitemap_id": 13, "posted_at": "20261006"}), 1.0),
                (SimpleNamespace(metadata={}), 0.1),                                   # the "init" dummy
                (SimpleNamespace(metadata={"sitemap_id": 14, "posted_at": ""}), 0.1)]  # no date
        vs = MagicMock()
        vs.similarity_search_with_score_by_vector.return_value = docs
        assert l1_search(vs)([0.1, 0.2], 50) == [(12, 20261005, 0.8), (13, 20261006, 0.5)]
        vs.similarity_search_with_score_by_vector.assert_called_once_with([0.1, 0.2], k=50)

    @pytest.mark.parametrize("value,expected", [(20261005, 20261005), ("20261005", 20261005),
                                                ("2026-10-05", None), (None, None), ("", None)])
    def test_posted_at_int(self, value, expected):
        assert posted_at_int(value) == expected


class TestNewsletterApp:
    def test_run_logged_brackets_a_run_in_crawl_log(self):
        repo = MagicMock()
        repo.log_crawl_start.return_value = 7
        repo.generate_newsletter.return_value = type("P", (str,), {"note": "degraded"})("d.md")
        assert newsletter_app.run_logged(repo, DAY) == "d.md"
        repo.log_crawl_start.assert_called_once_with("ALL", "newsletter")
        repo.log_crawl_complete.assert_called_once_with(7, 1, note="degraded")

    def test_a_failed_run_is_logged_failed_and_reraised(self):
        repo = MagicMock()
        repo.log_crawl_start.return_value = 7
        repo.generate_newsletter.side_effect = RuntimeError("DB down")
        with pytest.raises(RuntimeError):
            newsletter_app.run_logged(repo, DAY)
        repo.log_crawl_failed.assert_called_once_with(7, "DB down")
        repo.log_crawl_complete.assert_not_called()

    def test_the_service_runs_the_bracket_over_its_repo(self):
        generator, crawl_log = MagicMock(), MagicMock()
        generator.generate.return_value = "d.md"
        crawl_log.log_crawl_start.return_value = 3
        service = newsletter_app.NewsletterService(newsletter_app.NewsletterRepo(generator, crawl_log))
        assert service.generate_newsletter(DAY) == "d.md"
        generator.generate.assert_called_once_with(DAY)
        crawl_log.log_crawl_complete.assert_called_once_with(3, 1, note=None)

    def test_the_crawler_service_shares_the_bracket(self, monkeypatch):
        from newscrawler.domain.services import crawler_service_impl
        seen = []
        monkeypatch.setattr(newsletter_app, "run_logged", lambda repo, d: seen.append((repo, d)) or "x")
        fake = SimpleNamespace(data_flow_repo="REPO")
        assert crawler_service_impl.CrawlerServiceImpl.generate_newsletter(fake, DAY) == "x"
        assert seen == [("REPO", DAY)]

    def test_build_loads_no_l2_and_no_news_filter(self, monkeypatch):
        """DBT-74: what the 12:00 job builds -- MiniLM, NEWS_L1 read-only, the light datasources."""
        import langchain_community.embeddings as emb
        import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as cfd
        import newscrawler.core.importance_filter as imf
        monkeypatch.setattr(emb, "HuggingFaceEmbeddings", lambda **kw: SimpleNamespace(embed_documents=lambda t: []))
        monkeypatch.setattr(cfd, "ChunkFAISSDatasource", lambda *a, **k: pytest.fail("loaded NEWS_L1 + NEWS_L2"))
        monkeypatch.setattr(imf, "SemanticImportanceFilter", lambda *a, **k: pytest.fail("loaded the news filter"))
        loaded = []
        monkeypatch.setattr(newsletter_app, "load_l1_search", lambda e: loaded.append(e) or "SEARCH")
        service = newsletter_app.build_newsletter_service(client=MagicMock())
        assert loaded and service.generator._search_l1 == "SEARCH"
        assert newsletter_app.build_newsletter_service(with_l1=False, client=MagicMock()).generator._search_l1 is None
