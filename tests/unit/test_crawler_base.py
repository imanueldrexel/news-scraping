"""Tests for Crawler base class static methods. Coverage: GL, KW, GS, ND."""
import os
from datetime import datetime, timezone
from typing import List
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

os.environ.setdefault("VERBOSE", "False")
os.environ.setdefault("PARALLELIZE", "False")
os.environ.setdefault("REQUEST_MAX_RETRIES", "1")

from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.domain.entities.extraction.website_name import WebsiteName


def make_xml_url(link="http://example.com/article", title="Test Title",
                 keywords=None, pub_date="2024-01-01T12:00:00+07:00"):
    kw_tag = f"<news:keywords>{keywords}</news:keywords>" if keywords else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
      <url>
          <loc>{link}</loc>
          <news:title>{title}</news:title>
          {kw_tag}
          <news:publication_date>{pub_date}</news:publication_date>
      </url>
    </urlset>"""
    return BeautifulSoup(xml, "xml").find("url")


class _ConcreteCrawler(Crawler):
    def _get_reporter_from_text(self, soup) -> List[str]:
        return []
    @staticmethod
    def _get_branches(soup):
        return {}


class TestGetLink:
    def setup_method(self):
        self.crawler = _ConcreteCrawler()
        self.crawler.website_name = "KOMPAS"

    def test_GL01_appends_page_all(self):
        soup = make_xml_url(link="http://example.com/article")
        assert self.crawler._get_link(soup) == "http://example.com/article?page=all"

    def test_GL02_no_double_append(self):
        soup = make_xml_url(link="http://example.com/article?page=all")
        result = self.crawler._get_link(soup)
        assert result.count("?page=all") == 1

    def test_GL03_jpnn_no_page_all(self):
        self.crawler.website_name = "JPNN"
        soup = make_xml_url(link="http://jpnn.com/article")
        assert "?page=all" not in self.crawler._get_link(soup)


    def test_GL04_url_with_other_params_gets_page_all_appended(self):
        soup = make_xml_url(link="http://example.com/article?source=home")
        result = self.crawler._get_link(soup)
        assert result.endswith("?page=all")


class TestGetKeywords:
    def test_KW01_space_separated(self):
        soup = make_xml_url(keywords="economy finance")
        assert Crawler._get_keywords(soup) == ["economy", "finance"]

    def test_KW02_single(self):
        soup = make_xml_url(keywords="single")
        assert Crawler._get_keywords(soup) == ["single"]

    def test_KW03_comma_not_split(self):
        # _get_keywords splits on whitespace only: commas stick to tokens
        soup = make_xml_url(keywords="economy, finance")
        result = Crawler._get_keywords(soup)
        assert result == ["economy,", "finance"]

    def test_KW04_extra_whitespace(self):
        soup = make_xml_url(keywords="  economy  finance  ")
        assert Crawler._get_keywords(soup) == ["economy", "finance"]


class TestGetSitemap:
    def _valid(self, **kw):
        base = dict(headline="Title", link="http://ex.com", sources="KOMPAS",
                    category="economy", timestamp=datetime(2024,1,1,tzinfo=timezone.utc),
                    keywords=["k"])
        base.update(kw)
        return base

    def test_GS01_valid_returns_dto(self):
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        assert isinstance(Crawler._get_sitemap(self._valid()), SitemapDTO)

    def test_GS02_missing_headline_returns_none(self):
        assert Crawler._get_sitemap(self._valid(headline=None)) is None

    def test_GS03_missing_link_returns_none(self):
        assert Crawler._get_sitemap(self._valid(link=None)) is None

    def test_GS04_suara_category_forced_to_none(self):
        result = Crawler._get_sitemap(self._valid(sources=WebsiteName.SUARA.name, category="x"))
        assert result is not None and result.category is None


    def test_GS05_generic_exception_handler_itself_crashes(self):
        # BUG B7: the except BaseException handler calls articles_data.get('link'),
        # so if articles_data has no .get(), the handler re-raises instead of returning None.
        with pytest.raises(AttributeError):
            Crawler._get_sitemap(object())


class TestGetNewsDetails:
    def setup_method(self):
        self.crawler = _ConcreteCrawler()
        self.crawler.website_name = "KOMPAS"

    def _make_sitemap(self, link, website_name="KOMPAS"):
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        return SitemapDTO(headline="Test", link=link, sources=website_name)

    def test_ND01_jpnn_strips_page_all(self):
        called = []
        self.crawler.page_loader = MagicMock()
        self.crawler.page_loader.get_soup = lambda url: called.append(url) or None
        self.crawler.website_name = "JPNN"
        self.crawler._get_news_details(self._make_sitemap("http://jpnn.com/article?page=all"))
        assert called[0] == "http://jpnn.com/article"

    def test_ND02_non_jpnn_url_unchanged(self):
        called = []
        self.crawler.page_loader = MagicMock()
        self.crawler.page_loader.get_soup = lambda url: called.append(url) or None
        self.crawler._get_news_details(self._make_sitemap("http://kompas.com/article?page=all"))
        assert called[0] == "http://kompas.com/article?page=all"

    def test_ND03_none_soup_returns_none(self):
        self.crawler.page_loader = MagicMock()
        self.crawler.page_loader.get_soup = MagicMock(return_value=None)
        assert self.crawler._get_news_details(self._make_sitemap("http://ex.com")) is None


class TestParallelizationGuard:
    def test_PAR01_mediaindonesia_always_sequential(self):
        crawler = _ConcreteCrawler()
        crawler.parallelize = True
        call_log = []
        def fake_get_sitemap(data):
            call_log.append(data)
            return None
        import unittest.mock as _mock
        with _mock.patch.object(_ConcreteCrawler, '_get_sitemap', staticmethod(fake_get_sitemap)):
            crawler.batch_crawling_sitemap(
                [{"headline": "x", "link": "http://a.com", "sources": "MEDIAINDONESIA"}],
                website_name=WebsiteName.MEDIAINDONESIA.value,
            )
        assert len(call_log) == 1

    def test_PAR02_non_mediaindonesia_with_parallelize_uses_executor(self):
        import unittest.mock as _mock
        crawler = _ConcreteCrawler()
        crawler.parallelize = True
        with _mock.patch(
            "newscrawler.infrastructure.datasource.scrapers.crawler.ThreadPoolExecutor"
        ) as mock_tpe:
            mock_tpe.return_value.__enter__ = _mock.MagicMock(
                return_value=_mock.MagicMock(map=lambda f, items: iter([]))
            )
            mock_tpe.return_value.__exit__ = _mock.MagicMock(return_value=False)
            crawler.batch_crawling_sitemap(
                [{"headline": "x", "link": "http://k.com", "sources": "KOMPAS"}],
                website_name="KOMPAS",
            )
        mock_tpe.assert_called_once()
