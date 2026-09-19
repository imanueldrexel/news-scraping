"""SRC-06 (#17), TEMPO half: _get_branches used to fetch all 28 -sitemap.xml
leaves up front (~155s, blowing check_crawlers.py's 60s budget) and mis-read
each fetched leaf's first <loc> (an article URL) as the branch link itself --
collapsing 28 entries into a handful of garbage keys. Targets
ekonomi-sitemap.xml directly with no extra fetch. TEMPO's leaf sitemap is
lastmod-only (SYS-32, #94), already handled in the base crawler.
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.tempo.tempo_crawler import TempoCrawler

_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.tempo.co/politik-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.tempo.co/ekonomi-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.tempo.co/hiburan-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.tempo.co/olahraga-sitemap.xml</loc></sitemap>
</sitemapindex>"""


class TestTempoGetBranches:
    def test_targets_ekonomi_sitemap_directly(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = TempoCrawler._get_branches(soup)
        assert branches == {"ekonomi": "https://www.tempo.co/ekonomi-sitemap.xml"}

    def test_other_sections_excluded(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = TempoCrawler._get_branches(soup)
        assert "politik" not in branches
        assert "hiburan" not in branches
        assert "olahraga" not in branches

    def test_does_not_fetch_any_leaf(self):
        # Regression check for the old bug: _get_branches must not call
        # self.page_loader.get_soup at all -- it's a @staticmethod now with no
        # `self`, so it structurally cannot make the extra fetch.
        assert isinstance(TempoCrawler.__dict__["_get_branches"], staticmethod)

    def test_empty_index_yields_no_branches(self):
        soup = BeautifulSoup(
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>',
            "html.parser",
        )
        assert TempoCrawler._get_branches(soup) == {}
