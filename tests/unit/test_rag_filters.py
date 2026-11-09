"""SYS-92 (#261) / SYS-100 (#269): the search filters. The topic is `articles.topic` (a
filter_rubric topic), not the outlet's section; the portal is an exact source; dates are
inclusive days. Values are checked against closed sets and reach SQL only as binds."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import newscrawler.web.query_processor as qp_mod
from newscrawler.core.filter_rubric import TOPIC_SOFT, TOPICS
from newscrawler.web import filters as f
from newscrawler.web.query_processor import QueryProcessor

TODAY = date(2026, 10, 7)


class TestTopicChoices:
    def test_every_option_is_a_saved_topic(self):
        assert set(f.TOPIC_CHOICES) == set(TOPICS) - {TOPIC_SOFT}
        assert list(f.TOPIC_CHOICES) == [t for t in TOPICS if t != TOPIC_SOFT], "finance topics first, as the newsletter"

    def test_the_retired_finance_era_values_are_gone(self):
        for old in ("macroeconomics", "capital_market", "banking", "commodities"):
            assert f.parse(topic=old).topic is None


class TestParse:
    def test_valid_values(self):
        got = f.parse(topic="markets", source="kontan", rentang="7")
        assert (got.topic, got.source, got.days) == ("markets", "KONTAN", 7)

    @pytest.mark.parametrize("kwargs", [{"topic": "soft"}, {"topic": "x'; DROP TABLE articles;--"},
                                        {"source": "NOT_AN_OUTLET"}, {"rentang": "365"}])
    def test_unknown_values_are_dropped(self, kwargs):
        assert not f.parse(**kwargs).active

    def test_custom_range_uses_the_dates_and_orders_them(self):
        got = f.parse(rentang="custom", date_from="2026-10-05", date_to="2026-10-01")
        assert (got.date_from, got.date_to) == (date(2026, 10, 1), date(2026, 10, 5))

    def test_all_dates_ignores_hidden_date_inputs(self):
        # the form keeps the date inputs' values while "Semua" is chosen
        assert not f.parse(rentang="", date_from="2026-10-01").active

    def test_json_without_rentang_uses_the_dates(self):
        assert f.parse(date_from="2026-10-01").date_from == date(2026, 10, 1)

    def test_a_bad_date_is_dropped(self):
        assert f.parse(rentang="custom", date_from="01/10/2026").date_from is None

    def test_last_n_days_end_today_inclusive(self):
        assert f.Filters(days=7).bounds(TODAY) == (date(2026, 10, 1), TODAY)

    def test_chips_use_reader_names(self):
        chips = f.parse(topic="law_crime", source="DETIK", rentang="30").chips()
        assert chips == [("topic", "Hukum & Kriminal"), ("source", "detikcom"), ("rentang", "30 hari terakhir")]

    def test_narrow_text(self):
        text = f.parse(topic="commodities_energy", source="TEMPO", rentang="7").narrow_text()
        assert text == "Tidak ada artikel Komoditas & Energi dari Tempo dalam 7 hari terakhir."
        assert f.parse(source="KONTAN").narrow_text() == "Tidak ada artikel dari Kontan."


def _hit(sid, topic, source="KONTAN", day=date(2026, 10, 5)):
    return {"sitemap_id": sid, "topic": topic, "source": source, "posted_date": day, "semantic_score": 0.9,
            "text_content": "Paragraf berita yang cukup panjang untuk menjadi sumber jawaban di halaman pencarian berita Indonesia ini."}


class TestApplyFilters:
    HITS = [_hit(1, "markets"), _hit(2, "law_crime", "DETIK"), _hit(3, "markets", "CNBC", date(2026, 9, 1)),
            _hit(4, None, day=None)]

    def _ids(self, filters):
        return [h["sitemap_id"] for h in QueryProcessor._apply_filters([dict(h) for h in self.HITS], filters, TODAY)]

    def test_topic(self):
        assert self._ids(f.Filters(topic="markets")) == [1, 3]

    def test_portal_is_exact(self):
        assert self._ids(f.Filters(source="KONTAN")) == [1, 4]

    def test_date_range_drops_undated(self):
        assert self._ids(f.Filters(days=7)) == [1, 2]

    def test_combined(self):
        assert self._ids(f.Filters(topic="markets", days=30)) == [1]


def _qp_with_rows(rows):
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = rows
    client = MagicMock()
    client.get_session.return_value.__enter__.return_value = session
    qp = QueryProcessor(MagicMock(), client, summarizer=None, usage=MagicMock())
    qp.keyword_df = MagicMock(get=lambda words: {w: 0.01 for w in words})   # SYS-103: df is its own unit
    return qp, session


class TestFtsSql:
    def test_filters_are_bind_parameters_in_fixed_fragments(self):
        qp, session = _qp_with_rows([])
        qp._fts_search(qp._keyword_query("rupiah"), 20, f.Filters(topic="markets", source="KONTAN", days=7), TODAY)
        sql, params = str(session.execute.call_args.args[0]), session.execute.call_args.args[1]
        assert "a.topic = :topic" in sql and "s.sources = :source" in sql
        assert "s.posted_at >= :from_day" in sql and "s.posted_at <= :to_day" in sql
        assert "LEFT JOIN articles a" in sql
        assert params["topic"] == "markets" and params["source"] == "KONTAN"
        assert (params["from_day"], params["to_day"]) == (20261001, 20261007)
        assert "markets" not in sql and "KONTAN" not in sql

    def test_no_filter_no_join_no_where(self):
        qp, session = _qp_with_rows([])
        qp._fts_search(qp._keyword_query("rupiah"), 20, f.Filters(), TODAY)
        sql, params = str(session.execute.call_args.args[0]), session.execute.call_args.args[1]
        assert "articles" not in sql and ":topic" not in sql
        assert set(params) == {"k", "anchors", "need", "t0", "w0"}

    def test_a_failing_query_returns_no_hits(self):
        qp, session = _qp_with_rows([])
        session.execute.side_effect = RuntimeError("db down")
        assert qp._fts_search(qp._keyword_query("rupiah"), 20, f.Filters(), TODAY) == []


class TestMetadata:
    def test_the_database_decides_title_portal_date_and_topic(self):
        row = SimpleNamespace(sitemap_id=1, headline="Judul DB", link="https://x/a", sources="KONTAN",
                              posted_at=20261005, topic="markets", l1_text="Pembuka.")
        qp, _ = _qp_with_rows([row])
        hits = qp._attach_metadata([{"sitemap_id": 1, "title": "faiss", "posted_at": "19700823", "source": "X"},
                                    {"sitemap_id": 2, "title": "a vector with no article"}])
        assert len(hits) == 1, "a hit whose sitemap has no article is not a source"
        h = hits[0]
        assert (h["title"], h["source"], h["topic"], h["posted_date"]) == ("Judul DB", "KONTAN", "markets",
                                                                            date(2026, 10, 5))
        assert h["l1_text"] == "Pembuka."

    def test_a_failed_metadata_query_keeps_the_index_metadata(self):
        qp, session = _qp_with_rows([])
        session.execute.side_effect = RuntimeError("db down")
        hits = qp._attach_metadata([{"sitemap_id": 1, "posted_at": "20261005", "source": "KONTAN"}])
        assert hits[0]["posted_date"] == date(2026, 10, 5) and hits[0]["topic"] is None


class TestRetrieve:
    def _qp(self):
        qp = QueryProcessor(MagicMock(), MagicMock(), summarizer=None, usage=MagicMock())
        qp.faiss_ds.search_l2.return_value = []
        qp._fts_search = MagicMock(return_value=[])
        qp._attach_metadata = lambda hits: hits
        return qp

    def test_a_filter_over_fetches_the_semantic_search(self):
        qp = self._qp()
        qp.retrieve("q", f.Filters(topic="markets"), TODAY)
        assert qp.faiss_ds.search_l2.call_args.kwargs["k"] == qp_mod.RAG_FILTERED_K

    def test_no_filter_searches_the_default_depth(self):
        qp = self._qp()
        qp.retrieve("q", f.Filters(), TODAY)
        assert qp.faiss_ds.search_l2.call_args.kwargs["k"] == qp_mod.SEMANTIC_K

    def test_only_hits_in_the_topic_are_kept_and_numbered(self):
        qp = self._qp()
        qp.faiss_ds.search_l2.return_value = [_hit(1, "markets"), _hit(2, "law_crime"), _hit(3, "markets")]
        hits = qp.retrieve("q", f.Filters(topic="markets"), TODAY)
        assert sorted(h["sitemap_id"] for h in hits) == [1, 3]
        assert [h["n"] for h in hits] == [1, 2]
