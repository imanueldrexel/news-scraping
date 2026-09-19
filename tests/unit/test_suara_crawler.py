"""SRC-12 (#90): SuaraCrawler's branch list was 20 hardcoded regional sitemaps
(SuaraNetwork, deleted), all frozen at 2022-10-23, and _get_branches never read
the fetched index -- it ignored `soup` entirely. Now it parses the real
sitemapindex and keeps bisnis's news leaf."""
from bs4 import BeautifulSoup

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.datasource.scrapers.suara_group.suara_crawler import SuaraCrawler

_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.suara.com/news/sitemap-news.xml</loc></sitemap>
  <sitemap><loc>https://www.suara.com/news/sitemap-web.xml</loc></sitemap>
  <sitemap><loc>https://www.suara.com/bisnis/sitemap-news.xml</loc></sitemap>
  <sitemap><loc>https://www.suara.com/bisnis/sitemap-web.xml</loc></sitemap>
  <sitemap><loc>https://www.suara.com/entertainment/sitemap-news.xml</loc></sitemap>
</sitemapindex>"""


class TestSuaraGetBranches:
    def test_reads_the_fetched_index_not_a_hardcoded_list(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = SuaraCrawler._get_branches(soup)
        assert branches == {"bisnis": "https://www.suara.com/bisnis/sitemap-news.xml"}

    def test_ignores_sitemap_web_and_other_sections(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = SuaraCrawler._get_branches(soup)
        assert "news" not in branches
        assert "entertainment" not in branches
        assert len(branches) == 1

    def test_empty_index_yields_no_branches(self):
        soup = BeautifulSoup(
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>',
            "html.parser",
        )
        assert SuaraCrawler._get_branches(soup) == {}


class TestSuaraWebsiteUrl:
    def test_website_url_is_set_from_the_url_enum(self):
        # Before SRC-12, SuaraCrawler.__init__ never set website_url at all --
        # get_news_in_bulk() fetched None and always returned [].
        assert SuaraCrawler().website_url == URL.SUARA.value

    def test_url_enum_no_longer_empty(self):
        assert URL.SUARA.value == "https://www.suara.com/sitemap.xml"
