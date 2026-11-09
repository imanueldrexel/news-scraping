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


class TestBranchNameFromUrl:
    """SRC-53 (#173): names for the iNews TV rows stored under their sitemap URL."""

    def test_a_www_section_is_named_by_its_path(self):
        from newscrawler.infrastructure.datasource.scrapers.inews.inews_crawler import INewsCrawler
        name = INewsCrawler.branch_name_from_url
        assert name("https://www.inews.id/inews-tv/talkshow/sitemap.xml") == "inews-tv/talkshow"
        assert name("https://www.inews.id/inews-tv/sitemap.xml") == "inews-tv"
        assert name(" https://www.inews.id/finance/bisnis/sitemap.xml ") == "finance/bisnis"

    def test_what_it_cannot_name_is_none_never_the_url(self):
        from newscrawler.infrastructure.datasource.scrapers.inews.inews_crawler import INewsCrawler
        name = INewsCrawler.branch_name_from_url
        assert name("https://ambon.inews.id/sitemap.xml") is None      # retired regional mirror (SRC-29)
        assert name("https://www.inews.id/sitemap.xml") is None        # the index itself
        assert name("https://www.inews.id/inews-tv/talkshow/feed.xml") is None
        assert name("") is None and name(None) is None

    def test_talkshow_is_denied_for_inews_only_and_eksklusif_is_left_to_the_probe(self):
        from newscrawler.core.importance_filter import category_gate
        from newscrawler.core.crawler_dict_list import CRAWLER_DICT
        assert category_gate("inews-tv/talkshow", "INEWS") == "deny"
        assert category_gate("inews-tv/talkshow", "DETIK") is None
        assert category_gate("inews-tv/eksklusif", "INEWS") is None
        assert category_gate("inews-tv", "INEWS") is None
        assert CRAWLER_DICT["INEWS"].is_soft_branch("inews-tv/talkshow")
