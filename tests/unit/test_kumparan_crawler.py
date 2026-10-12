"""
SRC-11 (#68): KumparanCrawler parsed the page's JSON-LD byline block with
eval() -- code execution from third-party page content, and a NameError (swallowed,
byline silently dropped) on any true/false/null literal, which Python does not
know but schema.org NewsArticle markup routinely carries
("isAccessibleForFree": true). Now json.loads, reading `author` as a Person
object, a list of them, or a bare string.

Fixture shape mirrors the live page (2026-09-20): two data-rh="true" ld+json
blocks, a NewsArticle with a Person author and a BreadcrumbList without one.
"""
import pytest
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.kumparan.kumparan_crawler import (
    KumparanCrawler,
)


def _page(*ld_blocks: str) -> BeautifulSoup:
    scripts = "".join(
        f'<script data-rh="true" type="application/ld+json">{block}</script>'
        for block in ld_blocks
    )
    return BeautifulSoup(f"<html><head>{scripts}</head><body></body></html>", "html.parser")


_BREADCRUMB = '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}'

_NEWS_ARTICLE_WITH_LITERALS = """{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "NasDem Pede Ajukan PT 7%",
  "isAccessibleForFree": true,
  "isPartOf": null,
  "hasPart": {"@type": "WebPageElement", "isAccessibleForFree": false},
  "author": {"@type": "Person", "name": "Abid Raihan", "url": "https://kumparan.com/abid-raihan"}
}"""


class TestKumparanReporterFromJsonLd:
    def test_true_false_null_literals_do_not_break_the_byline(self):
        # The exact failure eval() had: `true` is a NameError in Python.
        page = _page(_BREADCRUMB, _NEWS_ARTICLE_WITH_LITERALS)
        assert KumparanCrawler()._get_reporter_from_text(page) == ["Abid Raihan"]

    def test_breadcrumb_block_without_author_is_skipped(self):
        page = _page(_BREADCRUMB, '{"@type":"NewsArticle","author":{"@type":"Person","name":"Pojok Informasi"}}')
        assert KumparanCrawler()._get_reporter_from_text(page) == ["Pojok Informasi"]

    def test_author_list_yields_every_name(self):
        page = _page('{"@type":"NewsArticle","author":[{"@type":"Person","name":"A"},{"@type":"Person","name":"B"}]}')
        assert KumparanCrawler()._get_reporter_from_text(page) == ["A", "B"]

    def test_author_as_bare_string(self):
        page = _page('{"@type":"NewsArticle","author":"Redaksi kumparan"}')
        assert KumparanCrawler()._get_reporter_from_text(page) == ["Redaksi kumparan"]

    def test_no_ld_json_returns_empty_list_not_none(self):
        result = KumparanCrawler()._get_reporter_from_text(_page())
        assert result == []
        assert result is not None

    def test_malformed_json_is_skipped_not_raised(self):
        page = _page('{"@type": "NewsArticle", "author": {', _NEWS_ARTICLE_WITH_LITERALS)
        assert KumparanCrawler()._get_reporter_from_text(page) == ["Abid Raihan"]

    def test_python_code_in_the_block_is_never_executed(self):
        # eval() would have run this; json.loads rejects it.
        page = _page('__import__("os").system("echo pwned")')
        assert KumparanCrawler()._get_reporter_from_text(page) == []

    def test_blank_and_missing_names_are_dropped(self):
        page = _page('{"@type":"NewsArticle","author":[{"@type":"Person","name":"  "},{"@type":"Person"},{"@type":"Person","name":"C"}]}')
        assert KumparanCrawler()._get_reporter_from_text(page) == ["C"]


def test_no_eval_anywhere_in_newscrawler():
    """Done-when: `grep -rn "eval(" newscrawler/` is empty. Kept as a test so a
    future scraper can't reintroduce it unnoticed."""
    import os
    import re

    import newscrawler

    root = os.path.dirname(newscrawler.__file__)
    offenders = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    code = line.split("#", 1)[0]
                    if re.search(r"(?<![\w.])eval\(", code):
                        offenders.append(f"{os.path.relpath(path, root)}:{lineno}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)


class TestReaderPostsAreNotNews:
    """SRC-60 (#279): KUMPARAN's news sitemaps list readers' blog posts next to the newsroom's
    articles; 314 of 1,825 stored articles were "Tulisan dari ... tidak mewakili pandangan dari
    redaksi kumparan", and two held ranks 1-2 of the BI-Rate search."""

    @pytest.mark.parametrize("link", [
        "https://kumparan.com/kumparannews/komjak-minta-ruu-perampasan-aset-28KSwanHaCI?page=all",
        "https://kumparan.com/kumparanbisnis/airlangga-usul-simpanan-di-koperasi-dijamin-lps-28FOK7Uf7nA",
        "https://kumparan.com/kumparanoto/x-1", "https://kumparan.com/kumparantekno/x-2",
        "https://kumparan.com/pandangan-jogja/kodam-xxvi-mataram-akan-bermarkas-di-godean-28Je6HKu9oG",
    ])
    def test_newsroom_accounts_are_kept(self, link):
        assert KumparanCrawler().out_of_scope_reason(link) is None

    @pytest.mark.parametrize("link", [
        "https://kumparan.com/KumparanNews/komjak-minta-ruu-perampasan-aset-28KSwanHaCI",
        "https://kumparan.com/kumparanBISNIS/x-1",
        "https://kumparan.com/Pandangan-Jogja/x-2",
    ])
    def test_a_capitalised_newsroom_account_is_kept(self, link):
        """DBT-66 (#319): an account is matched case-insensitively; a capitalised desk is the newsroom."""
        assert KumparanCrawler().out_of_scope_reason(link) is None

    @pytest.mark.parametrize("link", [
        "https://kumparan.com/tyasafira031/menjaga-pertumbuhan-ekonomi-indonesia-28K?page=all",
        "https://kumparan.com/halizasalda24/kredit-umkm-terus-didorong-28K",
        "https://kumparan.com/user-13082024092310/reforma-agraria-28K",
        "https://kumparan.com/TDA/tda-jakarta-selatan-9-0-28H0e29YSD2?page=all",
        "https://kumparan.com/daily-tech-science/prospektus-ipo-anthropic-28HQiTauPn6",
        "https://kumparan.com/kumparan-fan/x", "", None,
    ])
    def test_reader_and_other_accounts_are_not(self, link):
        assert KumparanCrawler().out_of_scope_reason(link) == "not a kumparan newsroom account (reader post)"

    @staticmethod
    def _crawler(monkeypatch):
        crawler = KumparanCrawler()
        sitemap = BeautifulSoup(
            "<urlset>"
            "<url><loc>https://kumparan.com/kumparanbisnis/bi-tahan-suku-bunga-28A</loc>"
            "<news:publication_date>2026-10-07T10:00:00+07:00</news:publication_date>"
            "<news:title>BI Tahan Suku Bunga</news:title></url>"
            "<url><loc>https://kumparan.com/tyasafira031/menjaga-pertumbuhan-ekonomi-28B</loc>"
            "<news:publication_date>2026-10-07T11:00:00+07:00</news:publication_date>"
            "<news:title>Menjaga Pertumbuhan Ekonomi</news:title></url>"
            "</urlset>", "html.parser")
        monkeypatch.setattr(crawler, "list_branches",
                            lambda: {"news": "https://kumparan.com/sitemap_channel_news.xml"})
        monkeypatch.setattr(crawler, "_load_page", lambda url: (sitemap, None))
        return crawler

    def test_a_sitemap_with_a_desk_and_a_reader_url_keeps_the_desk_url(self, monkeypatch):
        listing = self._crawler(monkeypatch).get_news_in_bulk()
        assert [e["link"] for e in listing] == ["https://kumparan.com/kumparanbisnis/bi-tahan-suku-bunga-28A?page=all"]
        assert listing.urls_out_of_scope == {"not a kumparan newsroom account (reader post)": 1}

    def test_the_skips_are_counted_in_the_run_note(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
        with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
            svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
        crawler = self._crawler(monkeypatch)
        crawler.batch_crawling_sitemap = MagicMock(return_value=[])
        svc.crawler_dict = {"KUMPARAN": crawler}
        svc.crawl_sitemaps("KUMPARAN")
        note = svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert note == "1 URL(s) out of scope: not a kumparan newsroom account (reader post) 1"

    def test_other_crawlers_keep_every_url(self):
        from newscrawler.core.crawler_dict_list import CRAWLER_DICT
        for name, crawler in CRAWLER_DICT.items():
            if name != "KUMPARAN":
                assert crawler.out_of_scope_reason("https://example.test/anything") is None, name
