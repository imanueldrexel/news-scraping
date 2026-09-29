"""SRC-16 (#95): TIRTO's live sitemap is a two-level, lastmod-only structure
(sitemap/news.xml -> insider/ekonomi.xml + insider/bisnis.xml -> one monthly
leaf per <sitemap>), not a single leaf -- URL.TIRTO used to point at a 404'd
path, and _get_branches handed the (would-be) index URL itself to _scrape as
the only branch (same defect as SRC-15's MERDEKA). Depends on SYS-32 (#94)'s
lastmod fallback in the base crawler for the leaf sitemaps themselves.
"""
from datetime import datetime
from unittest.mock import MagicMock

from bs4 import BeautifulSoup

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.datasource.scrapers.tirto.tirto_crawler import TirtoCrawler

_TOP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://tirto.id/sitemap/flash-news/politik.xml</loc></sitemap>
  <sitemap><loc>https://tirto.id/sitemap/insider/ekonomi.xml</loc></sitemap>
  <sitemap><loc>https://tirto.id/sitemap/insider/bisnis.xml</loc></sitemap>
  <sitemap><loc>https://tirto.id/sitemap/diajeng/binar.xml</loc></sitemap>
</sitemapindex>"""


def _monthly_leaves_xml(entries):
    """entries: list of (url, lastmod) newest-to-oldest or any order."""
    body = "\n".join(f"<sitemap><loc>{u}</loc><lastmod>{lm}</lastmod></sitemap>" for u, lm in entries)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>"""


SEPT = "https://tirto.id/sitemap/ekonomi/sitemap-ekonomi-post-september-2026.xml"
AUG = "https://tirto.id/sitemap/ekonomi/sitemap-ekonomi-post-august-2026.xml"
JUL = "https://tirto.id/sitemap/ekonomi/sitemap-ekonomi-post-july-2026.xml"
EKONOMI_INDEX = "https://tirto.id/sitemap/insider/ekonomi.xml"
BISNIS_INDEX = "https://tirto.id/sitemap/insider/bisnis.xml"


def _urlset(*links):
    body = "".join(f"<url><loc>{u}</loc><lastmod>2026-09-01T09:00:00+07:00</lastmod></url>" for u in links)
    return BeautifulSoup(f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>', "xml")


def _crawler(soups, now="2026-10-02T08:00:00+07:00"):
    crawler = TirtoCrawler()
    crawler.page_loader = MagicMock()
    crawler.page_loader.get_soup = lambda url: soups.get(url)
    crawler._now = lambda: datetime.fromisoformat(now)
    return crawler


class TestTirtoGetBranches:
    def test_a_branch_is_the_section_keyed_by_name_linking_its_sub_index(self):
        """SRC-32: the section, not one monthly leaf -- `_scrape` picks the leaves."""
        branches = TirtoCrawler()._get_branches(BeautifulSoup(_TOP_INDEX_XML, "html.parser"))
        assert branches == {"ekonomi": EKONOMI_INDEX, "bisnis": BISNIS_INDEX}

    def test_other_sections_from_the_top_index_are_ignored(self):
        branches = TirtoCrawler()._get_branches(BeautifulSoup(_TOP_INDEX_XML, "html.parser"))
        assert "flash-news" not in branches and "diajeng" not in branches


class TestTirtoMonthBoundary:
    """SRC-32 (#117): on the 2nd of a month the previous month's leaf, last
    modified on the 31st, must still be read; a newest-only rule never listed
    what it gained after the last crawl of the month."""

    def _index(self, entries):
        return BeautifulSoup(_monthly_leaves_xml(entries), "html.parser")

    def test_on_the_2nd_the_previous_months_leaf_is_read_too(self):
        crawler = _crawler({
            EKONOMI_INDEX: self._index([(AUG, "2026-08-31T19:10:00+07:00"), (SEPT, "2026-09-01T23:00:00+07:00"),
                                        (JUL, "2026-07-31T20:43:00+07:00")]),
        }, now="2026-09-02T08:00:00+07:00")
        assert crawler._recent_monthly_leaves(EKONOMI_INDEX) == [SEPT, AUG]

    def test_later_in_the_month_only_the_newest_leaf_is_read(self):
        crawler = _crawler({
            EKONOMI_INDEX: self._index([(AUG, "2026-08-31T19:10:00+07:00"), (SEPT, "2026-09-19T16:59:00+07:00")]),
        }, now="2026-09-20T08:00:00+07:00")
        assert crawler._recent_monthly_leaves(EKONOMI_INDEX) == [SEPT]

    def test_a_dormant_section_still_reads_its_newest_leaf(self):
        crawler = _crawler({EKONOMI_INDEX: self._index([(JUL, "2026-07-31T20:43:00+07:00")])},
                           now="2026-09-20T08:00:00+07:00")
        assert crawler._recent_monthly_leaves(EKONOMI_INDEX) == [JUL]

    def test_scrape_lists_both_leaves_under_the_section_name(self):
        crawler = _crawler({
            EKONOMI_INDEX: self._index([(AUG, "2026-08-31T19:10:00+07:00"), (SEPT, "2026-09-01T10:00:00+07:00")]),
            SEPT: _urlset("https://tirto.id/sept-article-hAbc"),
            AUG: _urlset("https://tirto.id/aug-31-evening-article-hXyz"),
        }, now="2026-09-02T08:00:00+07:00")
        rows = crawler._scrape(branch_link=EKONOMI_INDEX, branch_name="ekonomi")
        assert [r["link"].split("?")[0] for r in rows] == [
            "https://tirto.id/sept-article-hAbc", "https://tirto.id/aug-31-evening-article-hXyz"]
        assert {r["category"] for r in rows} == {"ekonomi"}

    def test_a_section_index_that_does_not_load_yields_nothing(self):
        crawler = _crawler({})
        assert crawler._scrape(branch_link=EKONOMI_INDEX, branch_name="ekonomi") == []


class TestTirtoUrl:
    def test_points_at_the_live_top_level_index(self):
        assert URL.TIRTO.value == "https://tirto.id/sitemap/news.xml"
