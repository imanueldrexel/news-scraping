"""SRC-05 (#16): liputan6.com's index moved from <section>/sitemap_news.xml to
<section>/sitemap.xml; the old "sitemap_news" in link filter matched nothing.
Also: article pages 404 with ?page=all appended (unlike most other outlets),
and _get_reporter_from_text (SRC-25, #105) was a bare `pass` (implicit None).
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.liputan_enam.liputan_enam_crawler import (
    LiputanEnamCrawler,
)

_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.liputan6.com/news/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.liputan6.com/bisnis/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.liputan6.com/showbiz/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.liputan6.com/bola/sitemap.xml</loc></sitemap>
</sitemapindex>"""


class TestLiputan6GetBranches:
    def test_matches_the_new_section_sitemap_xml_format(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = LiputanEnamCrawler._get_branches(soup)
        assert branches == {"bisnis": "https://www.liputan6.com/bisnis/sitemap.xml"}

    def test_old_sitemap_news_format_would_have_matched_nothing(self):
        # Regression check: none of these entries contain "sitemap_news" --
        # the old filter's premise no longer holds on the live index.
        assert "sitemap_news" not in _INDEX_XML

    def test_other_sections_excluded(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = LiputanEnamCrawler._get_branches(soup)
        assert "news" not in branches
        assert "showbiz" not in branches
        assert "bola" not in branches


class TestLiputan6GetLinkNoPageAllSuffix:
    def test_link_is_not_suffixed_with_page_all(self):
        xml = "<url><loc>https://www.liputan6.com/bisnis/read/1/test</loc></url>"
        soup = BeautifulSoup(xml, "xml").find("url")
        link = LiputanEnamCrawler._get_link(soup)
        assert link == "https://www.liputan6.com/bisnis/read/1/test"
        assert "?page=all" not in link


class TestLiputan6ReporterReturnsEmptyList:
    def test_returns_empty_list_not_none(self):
        crawler = LiputanEnamCrawler()
        soup = BeautifulSoup("<html><body><p>no byline info</p></body></html>", "html.parser")
        assert crawler._get_reporter_from_text(soup) == []
