"""SRC-15 (#93): _get_branches used to hand the index URL itself to _scrape as
the only branch ({"news": URL.MERDEKA.value}) -- _scrape looks for <url>
elements, an index has <sitemap> elements, so it always found 0 links. Has
nothing to do with the site changing; the branch files are textbook
Google-news sitemaps once you actually fetch one.
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.merdeka.merdeka_crawler import (
    MerdekaCrawler,
)

_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.merdeka.com/peristiwa/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.merdeka.com/politik/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.merdeka.com/uang/sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.merdeka.com/artis/sitemap.xml</loc></sitemap>
</sitemapindex>"""


class TestMerdekaGetBranches:
    def test_parses_the_index_and_keeps_uang(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = MerdekaCrawler._get_branches(soup)
        assert branches == {"uang": "https://www.merdeka.com/uang/sitemap.xml"}

    def test_other_sections_excluded(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = MerdekaCrawler._get_branches(soup)
        assert "peristiwa" not in branches
        assert "politik" not in branches
        assert "artis" not in branches

    def test_no_longer_hands_the_index_url_itself_as_the_branch(self):
        # The bug this fixes: _get_branches used to ignore `soup` entirely and
        # return {"news": URL.MERDEKA.value} -- the index URL, not a leaf.
        from newscrawler.domain.entities.extraction.url_data import URL
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = MerdekaCrawler._get_branches(soup)
        assert URL.MERDEKA.value not in branches.values()

    def test_empty_index_yields_no_branches(self):
        soup = BeautifulSoup(
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>',
            "html.parser",
        )
        assert MerdekaCrawler._get_branches(soup) == {}
