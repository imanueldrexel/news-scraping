"""SRC-13 (#91): ANTARANEWS's liveness-probe URL (an English sports RSS feed on
a subdomain with no sitemap) 404s, but the crawler's real branch list is 60
hardcoded Indonesian feeds that were never affected by that -- _get_branches
never read the fetched index at all. Restricts the branch list to the four
ekonomi* feeds (55 of the 60 are off-topic per SYS-31) and fixes the category
label, which used to be the fixed string "ANTARA News" for every branch.

SRC-21 (#101): _get_reporter_from_text must return [] (not fall through to an
implicit None) when no byline paragraph is found.
"""
from bs4 import BeautifulSoup

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.datasource.scrapers.antara_news.antara_news_crawler import (
    AntaraNewsCrawler,
)


class TestAntaraNewsGetBranches:
    def test_restricted_to_ekonomi_feeds(self):
        branches = AntaraNewsCrawler._get_branches(None)
        assert branches == {
            "Ekonomi": "https://www.antaranews.com/rss/ekonomi.xml",
            "Finansial": "https://www.antaranews.com/rss/ekonomi-finansial.xml",
            "Bisnis": "https://www.antaranews.com/rss/ekonomi-bisnis.xml",
            "Bursa": "https://www.antaranews.com/rss/ekonomi-bursa.xml",
        }

    def test_dead_bumn_feed_and_offtopic_feeds_excluded(self):
        branches = AntaraNewsCrawler._get_branches(None)
        assert "BUMNUntukNegeri" not in branches
        assert "Olahraga" not in branches
        assert "Hiburan" not in branches
        assert "Lifestyle" not in branches


class TestAntaraNewsUrlIsLivenessProbeOnRealHost:
    def test_url_points_at_the_real_host_not_the_dead_english_sports_feed(self):
        assert URL.ANTARANEWS.value == "https://www.antaranews.com/rss/ekonomi.xml"
        assert "en.antaranews.com" not in URL.ANTARANEWS.value


class TestAntaraNewsScrapeUsesBranchNameAsCategory:
    _RSS = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
      <item>
        <title>Test Headline</title>
        <guid>https://www.antaranews.com/berita/123/test</guid>
        <pubDate>Fri, 19 Sep 2026 10:50:29 +0700</pubDate>
      </item>
    </channel></rss>"""

    def test_category_is_the_branch_name_not_a_fixed_string(self):
        crawler = AntaraNewsCrawler()
        crawler.page_loader = type("P", (), {"get_soup": staticmethod(
            lambda url: BeautifulSoup(TestAntaraNewsScrapeUsesBranchNameAsCategory._RSS, "xml")
        )})()
        rows = crawler._scrape(branch_link="https://x", branch_name="Bursa")
        assert len(rows) == 1
        assert rows[0]["category"] == "Bursa"


class TestReporterFromTextReturnsEmptyListNotNone:
    def _crawler(self):
        return AntaraNewsCrawler()

    def test_no_layer_returns_empty_list(self):
        soup = BeautifulSoup("<html><body><p>no post-content here</p></body></html>", "html.parser")
        assert self._crawler()._get_reporter_from_text(soup) == []

    def test_layer_present_but_no_byline_paragraph_returns_empty_list(self):
        soup = BeautifulSoup(
            '<div class="post-content clearfix"><p>Article text with no byline paragraph.</p></div>',
            "html.parser",
        )
        # Before SRC-21 this fell off the end and returned None.
        assert self._crawler()._get_reporter_from_text(soup) == []

    def test_byline_paragraph_still_parsed(self):
        soup = BeautifulSoup(
            '<div class="post-content clearfix">'
            '<p class="text-muted small mt10">Pewarta: Budi Santoso</p>'
            "</div>",
            "html.parser",
        )
        result = self._crawler()._get_reporter_from_text(soup)
        assert result == ["Budi Santoso"]
