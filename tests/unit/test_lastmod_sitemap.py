"""SYS-32 (#94): the base Crawler only understood Google-news sitemaps
(news:title/news:publication_date). A lastmod-only leaf (TIRTO, TEMPO,
BATAMPOS) must still produce a savable row: _get_timestamp falls back to
<lastmod>, _get_sitemap derives a placeholder headline from the URL when
news:title is absent, a row with no date at all is dropped up front (one
summary WARNING per branch, not a per-row exception), and _get_news_details
prefers a real page title over an empty sitemap headline.
"""
import os
from datetime import timedelta
from typing import List
from unittest.mock import MagicMock

os.environ.setdefault("VERBOSE", "False")
os.environ.setdefault("PARALLELIZE", "False")
os.environ.setdefault("REQUEST_MAX_RETRIES", "1")

from bs4 import BeautifulSoup

from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.utils.date_time_reader import DateTimeReader
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler, SitemapScrapeBatch


class _ConcreteCrawler(Crawler):
    def _get_reporter_from_text(self, soup) -> List[str]:
        return []

    @staticmethod
    def _get_branches(soup):
        return {}


def _lastmod_only_urlset(urls):
    """urls: list of (loc, lastmod) tuples, no news: namespace at all."""
    entries = "\n".join(
        f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>" for loc, lastmod in urls
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    {entries}
    </urlset>"""
    return BeautifulSoup(xml, "xml")


class TestScrapeOnLastmodOnlySitemap:
    def setup_method(self):
        self.crawler = _ConcreteCrawler()
        self.crawler.website_name = "TIRTO"
        self.crawler.page_loader = MagicMock()

    def test_rows_get_wib_timestamp_and_headline_none(self):
        soup = _lastmod_only_urlset(
            [("https://tirto.id/daftar-lengkap-harga-bbm-hB7q", "2026-09-01T09:32:00+07:00")]
        )
        self.crawler.page_loader.get_soup = MagicMock(return_value=soup)
        rows = self.crawler._scrape(branch_link="https://tirto.id/sitemap/ekonomi.xml", branch_name="ekonomi")
        assert len(rows) == 1
        assert rows[0]["headline"] is None
        assert rows[0]["timestamp"].strftime("%Y%m%d") == "20260901"
        assert rows[0]["timestamp"].utcoffset() == timedelta(hours=7)

    def test_no_lastmod_and_no_news_title_yields_no_timestamp(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://tirto.id/a</loc></url>
        </urlset>"""
        self.crawler.page_loader.get_soup = MagicMock(return_value=BeautifulSoup(xml, "xml"))
        rows = self.crawler._scrape(branch_link="https://tirto.id/x.xml", branch_name="ekonomi")
        assert rows[0]["timestamp"] is None


class TestGetSitemapHeadlineFallback:
    def _base(self, **kw):
        base = dict(headline=None, link="https://tirto.id/daftar-lengkap-harga-bbm-per-1-september-2026-hB7q",
                    sources="TIRTO", category="ekonomi",
                    timestamp=DateTimeReader().convert_date("2026-09-01T09:32:00+07:00"), keywords=None)
        base.update(kw)
        return base

    def test_derives_headline_from_url_slug_when_no_news_title(self):
        dto = Crawler._get_sitemap(self._base())
        assert dto is not None
        # str.title() capitalizes after any non-letter, incl. digits -- "Hb7Q"
        # not "Hb7q". Cosmetic only: a placeholder, not the real headline.
        assert dto.headline == "Daftar Lengkap Harga Bbm Per 1 September 2026 Hb7Q"

    def test_real_news_title_is_kept_as_is(self):
        dto = Crawler._get_sitemap(self._base(headline="Real Title From Sitemap"))
        assert dto.headline == "Real Title From Sitemap"

    def test_no_timestamp_returns_none_without_raising(self):
        assert Crawler._get_sitemap(self._base(timestamp=None)) is None

    def test_no_link_and_no_headline_still_returns_none_gracefully(self):
        assert Crawler._get_sitemap(self._base(link=None)) is None


class TestBatchCrawlingSitemapSkipsNoDate:
    def test_skipped_no_date_counted_and_returned(self):
        crawler = _ConcreteCrawler()
        crawler.parallelize = False
        news = [
            {"headline": None, "link": "https://tirto.id/a", "sources": "TIRTO",
             "category": "ekonomi", "timestamp": None},
            {"headline": None, "link": "https://tirto.id/b", "sources": "TIRTO",
             "category": "ekonomi", "timestamp": DateTimeReader().convert_date("2026-09-01T09:32:00+07:00")},
        ]
        result = crawler.batch_crawling_sitemap(news, website_name="TIRTO")
        assert isinstance(result, SitemapScrapeBatch)
        assert len(result) == 1
        assert result.skipped_no_date == 1

    def test_per_branch_warning_logged(self, caplog):
        import logging
        crawler = _ConcreteCrawler()
        crawler.parallelize = False
        news = [
            {"headline": None, "link": "https://tirto.id/a", "sources": "TIRTO",
             "category": "ekonomi", "timestamp": None},
        ]
        with caplog.at_level(logging.WARNING, logger="newscrawler.infrastructure.datasource.scrapers.crawler"):
            crawler.batch_crawling_sitemap(news, website_name="TIRTO")
        assert any("TIRTO/ekonomi" in r.message and "1 entries had no usable" in r.message for r in caplog.records)


class TestFetchNewsDetailsTitleFallback:
    def setup_method(self):
        self.crawler = _ConcreteCrawler()
        self.crawler.website_name = "TIRTO"

    def _sitemap(self, headline):
        # SitemapDTO.headline is a required `str` (pydantic-validated) -- a real
        # DTO can never actually carry headline=None (_get_sitemap either fills
        # it via the URL-slug fallback or returns None entirely, never a DTO
        # with a None headline). An empty string is the realistic "no title"
        # shape for a hand-built DTO reaching this method any other way.
        return SitemapDTO(headline=headline, link="https://tirto.id/a", sources="TIRTO", sitemap_id=1)

    def test_og_title_used_when_sitemap_headline_is_empty(self):
        soup = BeautifulSoup(
            '<html><head><meta property="og:title" content="Real Page Title"/></head>'
            '<body><p>Some article body text that is long enough to be usable content here.</p></body></html>',
            "html.parser",
        )
        self.crawler.page_loader = MagicMock()
        self.crawler.page_loader.get_soup = MagicMock(return_value=soup)
        dto = self.crawler._get_news_details(self._sitemap(headline=""))
        assert dto.meta_data["title"] == "Real Page Title"

    def test_title_tag_used_when_no_og_title(self):
        soup = BeautifulSoup(
            "<html><head><title>Plain Title Tag</title></head>"
            "<body><p>Some article body text that is long enough to be usable content here.</p></body></html>",
            "html.parser",
        )
        self.crawler.page_loader = MagicMock()
        self.crawler.page_loader.get_soup = MagicMock(return_value=soup)
        dto = self.crawler._get_news_details(self._sitemap(headline=""))
        assert dto.meta_data["title"] == "Plain Title Tag"

    def test_real_sitemap_headline_is_not_overridden(self):
        soup = BeautifulSoup(
            '<html><head><meta property="og:title" content="Page Title"/></head>'
            "<body><p>Some article body text that is long enough to be usable content here.</p></body></html>",
            "html.parser",
        )
        self.crawler.page_loader = MagicMock()
        self.crawler.page_loader.get_soup = MagicMock(return_value=soup)
        dto = self.crawler._get_news_details(self._sitemap(headline="Sitemap Headline"))
        assert dto.meta_data["title"] == "Sitemap Headline"
