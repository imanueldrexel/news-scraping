"""
SRC-09 (#57): TribunCrawler never implemented _get_reporter_from_text, so it
silently inherited the base Crawler's no-op (returns None -- Crawler is not an
ABC, so nothing enforced the override). Every article's reporter=None then crashed
NewsDetailsModel construction inside save_newsdetails's per-row try/except, forever
-- the identical bug SYS-08 found and fixed for VIVA.
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.tribun.tribun_crawler import (
    TribunCrawler,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class TestTribunReporterExtraction:
    def test_byline_extracted_from_penulis_div(self):
        html = """
        <div class="f20 credit mt10">
            <div class="fbo f13">
                <div id="penulis">
                    Penulis:
                    <a href="https://www.tribunnews.com/penulis/rizki-sandi-saputra">Rizki Sandi Saputra</a>
                </div>
                <div id="editor">
                    Editor:
                    <a href="https://www.tribunnews.com/editor/choirul-arifin">Choirul Arifin</a>
                </div>
            </div>
        </div>
        """
        assert TribunCrawler()._get_reporter_from_text(_soup(html)) == ["Rizki Sandi Saputra"]

    def test_never_returns_none_even_without_a_link(self):
        """Falls back to stripping the 'Penulis:' label from the div's own text
        if the name isn't wrapped in an <a> tag."""
        html = '<div id="penulis">Penulis: Tim Redaksi</div>'
        assert TribunCrawler()._get_reporter_from_text(_soup(html)) == ["Tim Redaksi"]

    def test_missing_penulis_element_returns_empty_list_not_none(self):
        """Syndicated/wire content (e.g. TRIBUN's new-economy market-price feed)
        has no individual byline at all -- must return [], never crash."""
        html = "<div class='txt-article'><p>No byline here.</p></div>"
        result = TribunCrawler()._get_reporter_from_text(_soup(html))
        assert result == []
        assert result is not None

    def test_blank_name_is_not_included(self):
        html = '<div id="penulis"><a href="/penulis/x">   </a></div>'
        assert TribunCrawler()._get_reporter_from_text(_soup(html)) == []
