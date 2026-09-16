"""
SYS-08: VivaCrawler never implemented _get_reporter_from_text, so it silently
inherited the base Crawler's no-op (returns None -- Crawler is a plain class, not an
ABC, so nothing enforced the override). Every article's reporter=None then crashed
NewsDetailsModel construction, so VIVA saved 0 articles ever despite the extractor
itself working fine (39,262 sitemaps, 37,381 attempted, 0 in articles).
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.viva.viva_crawler import VivaCrawler


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class TestVivaReporterExtraction:
    def test_single_author_extracted(self):
        html = """
        <div class="main-content-author">
            <span>Oleh :</span>
            <ul><li><a href="/author/1">Mohammad Yudha Prasetya</a></li></ul>
        </div>
        """
        assert VivaCrawler._get_reporter_from_text(_soup(html)) == ["Mohammad Yudha Prasetya"]

    def test_multiple_authors_extracted(self):
        html = """
        <div class="main-content-author">
            <ul>
                <li><a href="/author/1">Author One</a></li>
                <li><a href="/author/2">Author Two</a></li>
            </ul>
        </div>
        """
        assert VivaCrawler._get_reporter_from_text(_soup(html)) == ["Author One", "Author Two"]

    def test_missing_author_element_returns_empty_list_not_none(self):
        html = "<div class='main-content-detail'><p>No author here.</p></div>"
        result = VivaCrawler._get_reporter_from_text(_soup(html))
        assert result == []
        assert result is not None

    def test_author_element_present_but_no_link_returns_empty_list(self):
        html = "<div class='main-content-author'><span>Oleh :</span></div>"
        assert VivaCrawler._get_reporter_from_text(_soup(html)) == []

    def test_blank_author_name_is_not_included(self):
        html = """
        <div class="main-content-author">
            <ul><li><a href="/author/1">   </a></li></ul>
        </div>
        """
        assert VivaCrawler._get_reporter_from_text(_soup(html)) == []
