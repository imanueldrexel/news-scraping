"""SYS-103 (#273, ADR-006): the search page's keyword half.

The question's content words, weighted by rarity; the paragraphs must hold its rare
words; the score is the IDF-weighted coverage; df from the planner statistics for
common words and an exact count for the rest, cached.
"""
import math
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from newscrawler.web import keywords
from newscrawler.web.filters import Filters
from newscrawler.web.keywords import DocFrequency, KeywordQuery, Term, terms
from newscrawler.web.query_processor import QueryProcessor

BI = "Apa keputusan Bank Indonesia soal BI-Rate?"
# The exact L2 shares measured 2026-10-07 (EXPERIMENTS.md).
BI_DF = {"keputusan": 0.0414, "bank": 0.0453, "indonesia": 0.222, "bi-rate": 0.0009}


class TestTerms:
    def test_bi_question_drops_function_words_and_keeps_content_words(self):
        """The ticket's Done-when: 'apa' and 'soal' go, the content words stay."""
        assert terms(BI) == [Term("keputusan", False), Term("bank", True), Term("indonesia", True),
                             Term("bi-rate", True)]

    @pytest.mark.parametrize("question, words", [
        ("Kenapa rupiah melemah pekan ini?", ["rupiah", "melemah"]),
        ("Bagaimana harga minyak dunia terbaru?", ["harga", "minyak", "dunia"]),
        ("Di mana terjadi banjir atau longsor dalam sepekan terakhir?", ["terjadi", "banjir", "longsor"]),
    ])
    def test_replay_questions(self, question, words):
        assert [t.word for t in terms(question)] == words

    def test_names(self):
        got = {t.word: t.name for t in terms("Bagaimana kinerja IHSG 2026 dan saham Telkom?")}
        assert got == {"kinerja": False, "ihsg": True, "2026": True, "saham": False, "telkom": True}

    def test_a_capitalised_first_word_is_not_a_name(self):
        assert terms("Inflasi naik lagi?")[0] == Term("inflasi", False)

    def test_duplicates_once_case_insensitive(self):
        assert [t.word for t in terms("KPK kpk Kpk korupsi")] == ["kpk", "korupsi"]

    def test_at_most_max_terms(self):
        q = " ".join(f"kata{i}x" for i in range(30))
        assert len(terms(q)) == keywords.MAX_TERMS

    @pytest.mark.parametrize("question", ["", "apa itu?", "yang dan di ke", "a b c", "___ ? !"])
    def test_nothing_to_search(self, question):
        assert terms(question) == []

    def test_punctuation_trimmed_number_kept(self):
        assert [t.word for t in terms("BI-Rate 5,75%?")] == ["bi-rate", "5,75"]


class TestLexeme:
    def test_quoted_operand(self):
        assert keywords.lexeme("bi-rate") == "'bi-rate'"

    def test_quote_and_backslash_cannot_escape(self):
        assert keywords.lexeme("a'b\\c") == "'abc'"


class TestKeywordQueryBuild:
    def test_bi_question(self):
        kq = KeywordQuery.build(terms(BI), BI_DF)
        assert kq.words == ["keputusan", "bank", "indonesia", "bi-rate"]
        # 'bank' is a name under NAME_DF; 'keputusan' is over ANCHOR_DF; 'indonesia' over NAME_DF
        assert kq.anchors == ["bank", "bi-rate"]
        assert kq.names == ["bank", "bi-rate"]
        assert kq.need == 2

    def test_weights_are_normalised_idf(self):
        kq = KeywordQuery.build(terms(BI), BI_DF)
        assert sum(kq.weights.values()) == pytest.approx(1.0)
        idf = {w: math.log(1 / d) for w, d in BI_DF.items()}
        assert kq.weights["bi-rate"] == pytest.approx(idf["bi-rate"] / sum(idf.values()))
        assert kq.weights["bi-rate"] > kq.weights["bank"] > kq.weights["indonesia"]

    def test_a_word_found_nowhere_is_dropped(self):
        """A typo must neither become an anchor nobody holds nor dilute the coverage."""
        kq = KeywordQuery.build([Term("rupiah", False), Term("melemha", False)], {"rupiah": 0.02, "melemha": 0.0})
        assert kq.words == ["rupiah"] and kq.anchors == ["rupiah"] and kq.need == 1
        assert kq.weights == {"rupiah": pytest.approx(1.0)}

    def test_no_word_found_anywhere_is_none(self):
        assert KeywordQuery.build([Term("xyzzy", False)], {"xyzzy": 0.0}) is None
        assert KeywordQuery.build([], {}) is None

    def test_all_common_falls_back_to_the_rarest(self):
        kq = KeywordQuery.build([Term("harga", False), Term("dunia", False)], {"harga": 0.078, "dunia": 0.062})
        assert kq.anchors == ["dunia"] and kq.need == 1 and kq.names == []

    def test_anchor_threshold_is_strict(self):
        at = keywords.ANCHOR_DF
        kq = KeywordQuery.build([Term("a1", False), Term("b2", False)], {"a1": at, "b2": at - 0.001})
        assert kq.anchors == ["b2"]

    def test_name_threshold_wider_than_word_threshold(self):
        df = {"iran": 0.031, "konflik": 0.021, "perkembangan": 0.039}
        kq = KeywordQuery.build([Term("perkembangan", False), Term("konflik", False), Term("iran", True)], df)
        assert kq.anchors == ["konflik", "iran"] and kq.names == ["iran"] and kq.need == 2

    def test_a_common_name_is_not_required(self):
        df = {"indonesia": 0.22, "longsor": 0.003}
        kq = KeywordQuery.build([Term("longsor", False), Term("indonesia", True)], df)
        assert kq.anchors == ["longsor"] and kq.names == []

    def test_word_in_every_paragraph_gets_equal_weights(self):
        kq = KeywordQuery.build([Term("aa", False), Term("bb", False)], {"aa": 1.0, "bb": 1.0})
        assert kq.weights == {"aa": 0.5, "bb": 0.5}


def _session_factory(script):
    """A client whose sessions answer `execute` from `script(sql_text, params)`."""
    calls = []

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            calls.append((str(sql), dict(params or {})))
            return script(str(sql), dict(params or {}))

    client = MagicMock()
    client.get_session.side_effect = lambda: _Session()
    return client, calls


def _db(total=1000, elems=("indonesia", "harga"), freqs=(0.22, 0.08), counts=None):
    counts = counts or {}

    def script(sql, params):
        if "pg_stats" in sql:
            row = None if elems is None else SimpleNamespace(elems=list(elems), freqs=list(freqs) + [0.01, 0.3, 0.0])
            return MagicMock(fetchone=MagicMock(return_value=row))
        if sql.startswith("SELECT COUNT(*) FROM chunks"):
            return MagicMock(scalar=MagicMock(return_value=total))
        keys = sorted((k for k in params if k.startswith("t")), key=lambda k: int(k[1:]))
        words = [params[k].strip("'") for k in keys]
        return MagicMock(fetchone=MagicMock(return_value=tuple(counts.get(w, 0) for w in words)))
    return _session_factory(script)


class TestDocFrequency:
    def test_common_words_from_stats_rare_words_counted(self):
        client, calls = _db(counts={"bi-rate": 9})
        df = DocFrequency(client).get(["indonesia", "bi-rate"])
        assert df == {"indonesia": 0.22, "bi-rate": pytest.approx(0.009)}
        counted = [p for s, p in calls if "to_tsquery" in s]
        assert len(counted) == 1 and counted[0]["t0"] == "'bi-rate'", "only the rare word is counted"

    def test_trailing_stats_values_are_not_words(self):
        """most_common_elem_freqs carries min, max and the null share after the words' shares."""
        client, _ = _db()
        dfq = DocFrequency(client)
        dfq.get(["harga"])
        assert dfq._common == {"indonesia": 0.22, "harga": 0.08}

    def test_cached_within_ttl(self):
        now = [0.0]
        client, calls = _db(counts={"ojk": 15})
        dfq = DocFrequency(client, ttl_s=100, clock=lambda: now[0])
        dfq.get(["ojk", "harga"])
        n = len(calls)
        now[0] = 99
        assert dfq.get(["ojk", "harga"]) == {"ojk": 0.015, "harga": 0.08}
        assert len(calls) == n, "a cached word costs no query"

    def test_reloaded_after_ttl(self):
        now = [0.0]
        client, calls = _db(counts={"ojk": 15})
        dfq = DocFrequency(client, ttl_s=100, clock=lambda: now[0])
        dfq.get(["ojk"])
        n = len(calls)
        now[0] = 100
        dfq.get(["ojk"])
        assert len(calls) == n + 3, "total + stats + the recount"

    def test_without_stats_every_word_is_counted(self):
        client, calls = _db(elems=None, counts={"indonesia": 220, "harga": 80})
        assert DocFrequency(client).get(["indonesia", "harga"]) == {"indonesia": 0.22, "harga": 0.08}

    def test_count_is_capped(self):
        client, calls = _db(total=1000, elems=None)
        DocFrequency(client).get(["zz"])
        counted = [p for s, p in calls if "to_tsquery" in s][0]
        assert counted["cap"] == int(1000 * keywords.COUNT_CAP_DF)
        assert "LIMIT :cap" in [s for s, p in calls if "to_tsquery" in s][0]

    def test_empty_corpus(self):
        client, _ = _db(total=0, elems=None)
        assert DocFrequency(client).get(["zz"]) == {"zz": 0.0}

    def test_one_round_trip_for_several_rare_words(self):
        client, calls = _db(counts={"aa": 1, "bb": 2, "cc": 3})
        DocFrequency(client).get(["aa", "bb", "cc"])
        assert len([s for s, _ in calls if "to_tsquery" in s]) == 1

    def test_failure_raises(self):
        client = MagicMock()
        client.get_session.side_effect = RuntimeError("db down")
        with pytest.raises(RuntimeError):
            DocFrequency(client).get(["aa"])


def _qp(df=None, rows=()):
    qp = QueryProcessor.__new__(QueryProcessor)
    qp.keyword_df = MagicMock()
    qp.keyword_df.get.side_effect = lambda words: {w: (df or BI_DF).get(w, 0.0) for w in words}
    calls = []

    def script(sql, params):
        calls.append((sql, params))
        return MagicMock(fetchall=MagicMock(return_value=list(rows)))
    qp.client, _ = _session_factory(script)
    return qp, calls


class TestFtsSearch:
    def test_question_words_are_bind_values_never_sql(self):
        qp, calls = _qp()
        qp._fts_search(BI, 20, Filters(), date(2026, 10, 7))
        sql, params = calls[0]
        for word in ("keputusan", "bank", "indonesia", "bi-rate", "Apa", "soal"):
            assert word not in sql
        assert params["anchors"] == "'bank' | 'bi-rate'"
        assert params["need"] == 2 and params["k"] == 20
        assert sorted(v for k, v in params.items() if k.startswith("t")) == sorted(
            ["'keputusan'", "'bank'", "'indonesia'", "'bi-rate'"])
        assert sum(v for k, v in params.items() if k.startswith("w")) == pytest.approx(1.0)

    def test_sql_shape(self):
        qp, calls = _qp()
        qp._fts_search(BI, 20, Filters(), date(2026, 10, 7))
        sql = " ".join(calls[0][0].split())
        assert "plainto_tsquery" not in sql
        assert "c.fts_vector @@ to_tsquery('simple', :anchors)" in sql
        assert ">= :need" in sql
        assert "ORDER BY keyword_score DESC, ts_rank_cd(c.fts_vector, to_tsquery('simple', :anchors)) DESC" in sql
        # the name rule: one of the names must be present
        assert sql.count(">= 1") == 1

    def test_no_name_rule_without_names(self):
        qp, calls = _qp(df={"rupiah": 0.023, "melemah": 0.013})
        qp._fts_search("kenapa rupiah melemah?", 20, Filters(), date(2026, 10, 7))
        assert ">= 1" not in calls[0][0]

    def test_filters_still_bound(self):
        qp, calls = _qp()
        qp._fts_search(BI, 20, Filters(topic="ekonomi_makro", source="KOMPAS", days=7), date(2026, 10, 7))
        sql, params = calls[0]
        assert "AND a.topic = :topic" in sql and "AND s.sources = :source" in sql
        assert params["topic"] == "ekonomi_makro" and params["source"] == "KOMPAS"
        assert params["from_day"] == 20261001 and params["to_day"] == 20261007

    def test_rows_become_hits_with_keyword_score(self):
        row = SimpleNamespace(chunk_id=1, text_content="BI-Rate ditahan", sitemap_id=7, keyword_score=0.83)
        qp, _ = _qp(rows=[row])
        hits = qp._fts_search(BI, 20, Filters(), date(2026, 10, 7))
        assert hits == [{"chunk_id": 1, "text_content": "BI-Rate ditahan", "sitemap_id": 7,
                         "keyword_score": 0.83, "semantic_score": 0.0}]

    def test_only_stop_words_no_query(self):
        qp, calls = _qp()
        assert qp._fts_search("apa itu yang ini?", 20, Filters(), date(2026, 10, 7)) == []
        assert calls == [] and not qp.keyword_df.get.called

    def test_no_word_occurs_no_query(self):
        qp, calls = _qp(df={})
        assert qp._fts_search("xyzzy qwrtp", 20, Filters(), date(2026, 10, 7)) == []
        assert calls == []

    def test_df_failure_drops_the_keyword_half(self, caplog):
        qp, calls = _qp()
        qp.keyword_df.get.side_effect = RuntimeError("db down")
        assert qp._fts_search(BI, 20, Filters(), date(2026, 10, 7)) == []
        assert "FTS search failed" in caplog.text
