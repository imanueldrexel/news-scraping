"""QA 2026-10-19: QA's own held-out tests for the dev's 2026-10-19 queue: SYS-144/145 (ADR-021), SYS-146, SYS-194,
DBT-60, DBT-70, SRC-62. DBT-71 is checked by its two mutants.

Written from the tickets' text and ADR-021, before reading the dev's unit tests. The adverbs below are NOT in
`nya_words.ADVERBS` (colloquial forms a reader types: harusnya, mestinya, kayaknya, memangnya, aslinya), so they test
the claim that "the rule does not rest on the list".

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_19/test_qa_1019_web.py -q -p no:cacheprovider

Run from a tree copy at d2eecf4 (the baseline) to see which tests catch the original defects.
"""
import ast
import glob
import os
import sys
from datetime import datetime
from decimal import Decimal

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from newscrawler.web import followup as fu  # noqa: E402
from newscrawler.web import keywords as kw  # noqa: E402


def _thread(question, previous):
    """True when the follow-up is retrieved with its thread on the no-rewrite (fallback) path."""
    return fu.resolve(question, previous, None).text != question.strip()


# ── SYS-144: a topic switch is its own question, whatever -nya adverb it holds ────────────────────

ANTAM = ["Berapa harga emas Antam hari ini?"]


class TestQaSys144HeldOut:
    @pytest.mark.parametrize("question", [
        "Apa yang harusnya dilakukan pemerintah terhadap Garuda Indonesia?",   # name only in an object phrase
        "Kayaknya ada masalah di Waskita Karya, apa itu?",
        "Apa yang mestinya terjadi pada Sritex?",
        "Memangnya ada apa dengan Sritex?",
        "Memangnya kenapa terjadi PHK di Sritex?",
        "Apa yang aslinya terjadi pada Garuda Indonesia?",
    ])
    def test_a_switch_with_an_unlisted_adverb_stays_alone_on_the_fallback(self, question):
        assert not _thread(question, ANTAM)

    @pytest.mark.parametrize("question", [
        "Apa yang harusnya dilakukan pemerintah terhadap Garuda Indonesia?",
        "Apa yang mestinya terjadi pada Sritex?",
    ])
    def test_the_same_switch_kept_by_the_model_stays_kept(self, question):
        assert fu.resolve(question, ANTAM, question).how == fu.KEPT

    def test_a_lower_case_switch_with_an_unlisted_adverb(self):
        """Readers type lower case; story_words.names sees no name then."""
        assert not _thread("apa yang harusnya terjadi pada garuda indonesia?", ANTAM)

    @pytest.mark.parametrize("previous,question", [
        (["Apa keputusan The Fed terbaru?"], "Apa pengaruhnya terhadap harga emas?"),
        (["Bagaimana kinerja BBCA kuartal III?"], "Berapa labanya?"),
        (["Siapa Gubernur BI sekarang?"], "Apa kata dia soal BI rate?"),
        (["Bagaimana kasus korupsi timah?"], "Siapa saja tersangkanya?"),
    ])
    def test_a_real_back_reference_keeps_the_thread(self, previous, question):
        assert _thread(question, previous)

    def test_an_inner_antecedent_stays_alone(self):
        assert not _thread("Apa yang terjadi pada Waskita Karya dan bagaimana nasib karyawannya?",
                           ["Apa kata OJK soal kredit perbankan?"])


# ── SYS-145: a model-kept follow-up that still points back uses the thread ─────────────────────────

class TestQaSys145HeldOut:
    @pytest.mark.parametrize("previous,question", [
        (["Apa keputusan OPEC terbaru?"], "Apa pengaruhnya terhadap harga BBM?"),
        (["Apa keputusan The Fed terbaru?"], "Bagaimana efeknya bagi IHSG?"),
        (["Apa keputusan The Fed terbaru?"], "Bagaimana dampaknya ke saham bank BUMN seperti BBRI?"),  # 5 object words
    ])
    def test_kept_with_an_object_name_uses_the_thread(self, previous, question):
        r = fu.resolve(question, previous, question)
        assert r.how == fu.KEPT_THREAD
        assert previous[0] in r.text

    def test_the_thread_cue_does_not_leak(self):
        r = fu.resolve("Bagaimana dampaknya ke rupiah?", ["Apa keputusan The Fed pekan ini?"], "Bagaimana dampaknya ke rupiah?")
        assert r.cue_text == "Bagaimana dampaknya ke rupiah?"

    def test_a_different_rewrite_is_used_as_is(self):
        r = fu.resolve("Bagaimana dampaknya ke rupiah?", ["Apa keputusan The Fed terbaru?"],
                       "Bagaimana dampak keputusan The Fed ke rupiah?")
        assert r.how == fu.LLM and r.text == "Bagaimana dampak keputusan The Fed ke rupiah?"


# ── SYS-146: a -nya word is its root ───────────────────────────────────────────────────────────────

def _words(q):
    return [t.word for t in kw.terms(q)]


class TestQaSys146HeldOut:
    @pytest.mark.parametrize("a,b", [
        ("Berapa utangnya Garuda?", "Berapa utang Garuda?"),
        ("Berapa labanya BBRI tahun ini?", "Berapa laba BBRI tahun ini?"),
        ("Kapan IPO-nya Danantara?", "Kapan IPO Danantara?"),
        ("Siapa direkturnya Sritex?", "Siapa direktur Sritex?"),
    ])
    def test_the_clitic_and_the_plain_form_give_the_same_terms(self, a, b):
        assert _words(a) == _words(b)

    @pytest.mark.parametrize("q,word", [("Bagaimana ekspor kopi ke Kenya?", "kenya"),
                                        ("Apa kata Sonya Hellen soal APBN?", "sonya"),
                                        ("Apa jawaban Menkeu saat ditanya soal utang?", "ditanya")])
    def test_a_word_that_is_no_clitic_is_kept(self, q, word):
        assert word in _words(q)

    def test_an_adverb_is_no_keyword(self):
        assert "sebenarnya" not in _words("Apa yang sebenarnya terjadi pada Garuda?")

    def test_the_name_stays_a_name(self):
        assert [t for t in kw.terms("Siapa pemimpinnya Danantara?") if t.word == "danantara"][0].name


# ── SYS-194: the keyword half's order ends in a unique key ─────────────────────────────────────────

class TestQaSys194:
    @pytest.mark.parametrize("recent", [False, True])
    def test_the_order_by_ends_in_the_paragraph_id(self, recent):
        """Built for a real one-anchor question ("Apa yang dilakukan BI?", the ticket's repro), both orders."""
        from datetime import date
        from newscrawler.web import query_processor as qp
        from newscrawler.web.filters import Filters
        kq = kw.KeywordQuery.build(kw.terms("Apa yang dilakukan BI?"), {"bi": 0.001, "dilakukan": 0.5})
        sql, _ = qp.QueryProcessor._fts_sql(kq, 20, Filters(), date(2026, 10, 19), recent=recent)
        order = str(sql).rsplit("ORDER BY", 1)[1].rsplit("LIMIT", 1)[0]
        assert order.split(",")[-1].split() == ["c.chunk_id", "DESC"]


# ── DBT-60: every numeric form is a yyyymmdd or refused, never Unix seconds ───────────────────────

def _dto(ts):
    from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
    return SitemapDTO(headline="h", link="https://x.id/a", sources="KOMPAS", timestamp=ts)


class TestQaDbt60HeldOut:
    @pytest.mark.parametrize("ts", ["20260918", 20260918.0, Decimal("20260918"), "20260918.00", "\t20260918 ",
                                    Decimal("20260918.000")])
    def test_a_yyyymmdd_in_any_form_is_that_day(self, ts):
        assert _dto(ts).timestamp.date() == datetime(2026, 9, 18).date()

    @pytest.mark.parametrize("ts", ["1726617600", 1726617600, 1726617600.0, Decimal("1726617600"), "20261318",
                                    "20260931", 20260918.5, "-20260918", "2026091", 0, "0", float("inf"), "NaN"])
    def test_anything_else_numeric_is_refused(self, ts):
        with pytest.raises(Exception):
            _dto(ts)

    def test_an_iso_string_still_parses(self):
        assert _dto("2026-09-18T07:30:00").timestamp == datetime(2026, 9, 18, 7, 30)

    def test_a_datetime_passes_through(self):
        assert _dto(datetime(2026, 9, 18, 1, 2)).timestamp == datetime(2026, 9, 18, 1, 2)

    def test_numpy_forms(self):
        np = pytest.importorskip("numpy")
        assert _dto(np.int64(20260918)).timestamp.date() == datetime(2026, 9, 18).date()
        with pytest.raises(Exception):
            _dto(np.int64(1726617600))


# ── DBT-70: no script imports a store-repair script; one definition of "terminal" ──────────────────

class TestQaDbt70:
    def test_check_store_consistency_imports_no_script(self):
        src = open(os.path.join(ROOT, "scripts", "check_store_consistency.py"), encoding="utf-8").read()
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
        scripts = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "scripts", "*.py"))}
        assert not (mods & (scripts - {"notify_telegram"})), mods & scripts

    def test_no_script_defines_its_own_terminal_rule(self):
        hits = [p for p in glob.glob(os.path.join(ROOT, "scripts", "*.py"))
                if "def _load_state" in open(p, encoding="utf-8", errors="replace").read()]
        assert hits == []

    def test_sitemap_state_classifies(self):
        from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES as CAP
        from newscrawler.tools.store_repair import sitemap_state

        class Row:
            def __init__(self, sid, status, fails):
                self.sitemap_id, self.crawl_status, self.fetch_failures = sid, status, fails

            def __getitem__(self, i):
                return self.sitemap_id

        rows = [Row(1, "saved", 0), Row(2, "rejected_filter", 0), Row(3, "pending", CAP), Row(4, "pending", CAP - 1),
                Row(5, "empty_extraction", 0)]

        class Session:
            def execute(self, stmt, params):
                sql = str(stmt)
                if "FROM articles" in sql:
                    return [Row(1, None, 0)]
                return [r for r in rows if r.sitemap_id in params["i"]]

        assert sitemap_state(Session(), [1, 2, 3, 4, 5, 6]) == {1: "article", 2: "terminal", 3: "terminal",
                                                                4: "queued", 5: "queued"}


# ── SRC-62: INVESTORID's section from the URL ──────────────────────────────────────────────────────

class TestQaSrc62:
    @pytest.fixture
    def crawler(self):
        from newscrawler.infrastructure.datasource.scrapers.investor_id.investorid_crawler import InvestorIDCrawler
        return InvestorIDCrawler

    @pytest.mark.parametrize("url,section", [
        ("https://investor.id/money-lab/457694/raffi-ahmad-cari-berkah-dulu-kaya-kemudian", "money-lab"),
        ("https://investor.id/market/412345/ihsg-dibuka-menguat", "market"),
        ("https://investor.id/national/1/x", "national"),
    ])
    def test_the_section(self, crawler, url, section):
        assert crawler._get_branch_name_from_url(url) == section

    @pytest.mark.parametrize("url", ["https://investor.id/money-lab/", "https://investor.id.evil.com/market/1/x",
                                     "https://example.com/market/1/x", "", None,
                                     "https://investor.id/https://investor.id/market/1/x"])
    def test_no_section_never_a_url(self, crawler, url):
        out = crawler._get_branch_name_from_url(url)
        assert out is None or ("/" not in out and "." not in out)

    def test_money_lab_is_denied_for_investorid_only(self):
        from newscrawler.core.importance_filter import category_gate
        assert category_gate("money-lab", "INVESTORID") == "deny"
        assert category_gate("money-lab", "KONTAN") != "deny"

    def test_market_is_not_denied(self):
        from newscrawler.core.importance_filter import category_gate
        assert category_gate("market", "INVESTORID") != "deny"
