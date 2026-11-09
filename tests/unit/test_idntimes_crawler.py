"""SRC-14 (#92): IDNTIMES was filed under SRC-03 as blocked (HTTP 403), but
only the old configured /sitemap-news.xml path is retired -- /sitemap.xml is
live. _get_branches's re.sub also had a real bug: applied unconditionally, a
non-matching link (sitemap-web.xml, sitemap-image.xml) came back unchanged and
became a branch keyed by its own full URL.

SRC-28 (#110): that fix still kept every /sitemap-news.xml section (16 of
them), unlike every sibling outlet fixed the same session which narrowed to
the finance-relevant branch -- now only "business" is kept.
"""
from bs4 import BeautifulSoup

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.datasource.scrapers.idntimes.idntimes_crawler import (
    IDNTimesCrawler,
)

_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.idntimes.com/news/sitemap-news.xml</loc></sitemap>
  <sitemap><loc>https://www.idntimes.com/business/sitemap-news.xml</loc></sitemap>
  <sitemap><loc>https://www.idntimes.com/business/sitemap-web.xml</loc></sitemap>
  <sitemap><loc>https://www.idntimes.com/business/sitemap-image.xml</loc></sitemap>
  <sitemap><loc>https://www.idntimes.com/sport/sitemap-news.xml</loc></sitemap>
</sitemapindex>"""


class TestIdntimesGetBranches:
    def test_only_business_becomes_a_branch(self):
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = IDNTimesCrawler._get_branches(soup)
        assert branches == {
            "business": "https://www.idntimes.com/business/sitemap-news.xml",
        }

    def test_other_sitemap_news_sections_are_not_branches(self):
        # SRC-28 (#110): every /sitemap-news.xml section used to become a
        # branch (16 of them) -- only the finance-relevant one should now.
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = IDNTimesCrawler._get_branches(soup)
        assert "news" not in branches
        assert "sport" not in branches

    def test_sitemap_web_and_image_entries_are_not_branches(self):
        # Before the fix, re.sub on a non-matching link returned it unchanged,
        # so sitemap-web.xml/sitemap-image.xml became branches keyed by their
        # own full URL (a 1,000-entry, lastmod-only leaf with no news: tags).
        soup = BeautifulSoup(_INDEX_XML, "html.parser")
        branches = IDNTimesCrawler._get_branches(soup)
        assert not any("sitemap-web.xml" in v or "sitemap-image.xml" in v for v in branches.values())
        assert not any("sitemap-web.xml" in k or "sitemap-image.xml" in k for k in branches)

    def test_empty_index_yields_no_branches(self):
        soup = BeautifulSoup(
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>',
            "html.parser",
        )
        assert IDNTimesCrawler._get_branches(soup) == {}


class TestIdntimesUrl:
    def test_points_at_the_live_index_not_the_retired_path(self):
        assert URL.IDNTIMES.value == "https://www.idntimes.com/sitemap.xml"
