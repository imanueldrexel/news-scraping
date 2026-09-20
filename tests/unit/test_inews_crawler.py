"""SRC-27 (#109): _get_branches kept every entry from the real 129-branch
index -- www.inews.id's own topical sections (finance, sport, lifestyle, ...)
plus 113 regional subdomains (bogor.inews.id, etc.). A real task=all run
ingested 24,861 sitemaps in one crawl, 90% from those regional subdomains,
98% of which 404 (dead mirrors). Now only the finance leaf is kept.
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.inews.inews_crawler import (
    INewsCrawler,
)

_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.inews.id/finance/bisnis/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.inews.id/sport/all-sport/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.inews.id/lifestyle/muslim/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://bogor.inews.id/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://subang.inews.id/sitemap.xml</loc></sitemap>
</sitemapindex>"""


class TestInewsGetBranches:
    def test_only_finance_becomes_a_branch(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = INewsCrawler._get_branches(soup)
        assert branches == {"finance": "https://www.inews.id/finance/bisnis/sitemap.xml"}

    def test_other_www_sections_are_not_branches(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = INewsCrawler._get_branches(soup)
        assert "sport" not in branches
        assert "lifestyle" not in branches

    def test_regional_subdomains_are_not_branches(self):
        # These are 90% of the real index and ~98% dead (HTTP 404).
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = INewsCrawler._get_branches(soup)
        assert not any("bogor.inews.id" in v or "subang.inews.id" in v for v in branches.values())

    def test_empty_index_yields_no_branches(self):
        soup = BeautifulSoup(
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>',
            "html.parser",
        )
        assert INewsCrawler._get_branches(soup) == {}
