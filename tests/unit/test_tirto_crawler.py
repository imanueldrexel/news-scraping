"""SRC-16 (#95): TIRTO's live sitemap is a two-level, lastmod-only structure
(sitemap/news.xml -> insider/ekonomi.xml + insider/bisnis.xml -> one monthly
leaf per <sitemap>), not a single leaf -- URL.TIRTO used to point at a 404'd
path, and _get_branches handed the (would-be) index URL itself to _scrape as
the only branch (same defect as SRC-15's MERDEKA). Depends on SYS-32 (#94)'s
lastmod fallback in the base crawler for the leaf sitemaps themselves.
"""
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


class TestTirtoGetBranches:
    def _crawler_with_section_indexes(self, ekonomi_entries, bisnis_entries):
        crawler = TirtoCrawler()
        soups = {
            "https://tirto.id/sitemap/insider/ekonomi.xml": BeautifulSoup(
                _monthly_leaves_xml(ekonomi_entries), "html.parser"
            ),
            "https://tirto.id/sitemap/insider/bisnis.xml": BeautifulSoup(
                _monthly_leaves_xml(bisnis_entries), "html.parser"
            ),
        }
        crawler.page_loader = MagicMock()
        crawler.page_loader.get_soup = lambda url: soups.get(url)
        return crawler

    def test_picks_newest_monthly_leaf_per_section_by_lastmod(self):
        crawler = self._crawler_with_section_indexes(
            ekonomi_entries=[
                ("https://tirto.id/sitemap/ekonomi/sitemap-ekonomi-post-august-2026.xml", "2026-08-31T19:10:00+07:00"),
                ("https://tirto.id/sitemap/ekonomi/sitemap-ekonomi-post-september-2026.xml", "2026-09-19T16:59:00+07:00"),
            ],
            bisnis_entries=[
                ("https://tirto.id/sitemap/bisnis/sitemap-bisnis-post-september-2026.xml", "2026-09-18T13:27:00+07:00"),
                ("https://tirto.id/sitemap/bisnis/sitemap-bisnis-post-july-2026.xml", "2026-07-31T20:43:00+07:00"),
            ],
        )
        top_soup = BeautifulSoup(_TOP_INDEX_XML, "html.parser")
        branches = crawler._get_branches(top_soup)
        assert branches == {
            "ekonomi": "https://tirto.id/sitemap/ekonomi/sitemap-ekonomi-post-september-2026.xml",
            "bisnis": "https://tirto.id/sitemap/bisnis/sitemap-bisnis-post-september-2026.xml",
        }

    def test_other_sections_from_the_top_index_are_ignored(self):
        crawler = self._crawler_with_section_indexes(
            ekonomi_entries=[("https://tirto.id/sitemap/ekonomi/sitemap-ekonomi-post-september-2026.xml",
                               "2026-09-19T16:59:00+07:00")],
            bisnis_entries=[("https://tirto.id/sitemap/bisnis/sitemap-bisnis-post-september-2026.xml",
                              "2026-09-18T13:27:00+07:00")],
        )
        top_soup = BeautifulSoup(_TOP_INDEX_XML, "html.parser")
        branches = crawler._get_branches(top_soup)
        assert "flash-news" not in branches and "diajeng" not in branches
        assert len(branches) == 2

    def test_section_index_fetch_failure_is_skipped_not_fatal(self):
        crawler = TirtoCrawler()
        crawler.page_loader = MagicMock()
        crawler.page_loader.get_soup = MagicMock(return_value=None)
        top_soup = BeautifulSoup(_TOP_INDEX_XML, "html.parser")
        assert crawler._get_branches(top_soup) == {}


class TestTirtoUrl:
    def test_points_at_the_live_top_level_index(self):
        assert URL.TIRTO.value == "https://tirto.id/sitemap/news.xml"
