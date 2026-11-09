"""
SRC-10 (#65): IdxChannelCrawler's byline selector matched the publication-date
<div class="text-body--2"> instead of the actual byline, which is an
<a class="text-body--2 creator"> tag sharing that same "text-body--2" class --
`soup.find("div", ...)` only ever considered <div>s, so it always landed on the
date. `articles.writer` was `["16"]`/`["17"]` (a bare day-of-month) on all 615
IDXCHANNEL rows. Fixed by targeting the "creator" class directly, verified against
a live fetch across 5 categories (banking, economics, news, syariah, milenomic).
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.idx_channel.idxchannel_crawler import (
    IdxChannelCrawler,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# Shape mirrors the real page: both the byline <a> and the date <div> share the
# "text-body--2" class, and the byline appears after the date in document order --
# a selector keyed on "text-body--2" alone would pick the date either way this is
# ordered, so this is the actual regression shape, not a convenient simplification.
_REAL_SHAPE_HTML = """
<div class="article--creator">
    <span class="category">Market news</span>
    <a href="/author/desi-angriani" class="text-body--2 creator">Desi Angriani</a>
    <div class="text-body--2">16/09/2026 17:54 WIB</div>
</div>
"""


class TestIdxChannelReporterExtraction:
    def test_byline_extracted_not_the_publication_date(self):
        assert IdxChannelCrawler()._get_reporter_from_text(_soup(_REAL_SHAPE_HTML)) == ["Desi Angriani"]

    def test_missing_byline_element_returns_empty_list_not_none(self):
        html = '<div class="text-body--2">16/09/2026 17:54 WIB</div>'
        result = IdxChannelCrawler()._get_reporter_from_text(_soup(html))
        assert result == []
        assert result is not None

    def test_blank_byline_is_not_included(self):
        html = '<a class="text-body--2 creator">   </a>'
        assert IdxChannelCrawler()._get_reporter_from_text(_soup(html)) == []
