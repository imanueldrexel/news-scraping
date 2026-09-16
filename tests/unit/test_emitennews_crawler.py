"""
SRC-01: EMITENNEWS sitemap parsing. Offline -- page_loader is stubbed with the real
shapes observed on 2026-09-16: a <sitemapindex> of sitemap-current-N.xml children, each a
<urlset> of plain <url><loc/><lastmod/></url> entries (no news: tags).
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from bs4 import BeautifulSoup

os.environ.setdefault("PARALLELIZE", "False")

from newscrawler.infrastructure.datasource.scrapers.emitennews.emitennews_crawler import (  # noqa: E402
    EmitennewsCrawler,
)

WIB = timezone(timedelta(hours=7))
INDEX_URL = "https://www.emitennews.com/sitemap.xml"

INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.emitennews.com/sitemap-current-1.xml</loc><lastmod>2026-09-16</lastmod></sitemap>
<sitemap><loc>https://www.emitennews.com/sitemap-current-2.xml</loc><lastmod>2026-09-16</lastmod></sitemap>
<sitemap><loc>https://www.emitennews.com/sitemap-current-3.xml</loc><lastmod>2026-09-16</lastmod></sitemap>
</sitemapindex>"""

CHILD_XML = {
    "https://www.emitennews.com/sitemap-current-1.xml": """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.emitennews.com/news/sp-global-ingatkan-ini-ihsg-lanjut-tertekan</loc><lastmod>2026-09-16</lastmod></url>
<url><loc>https://www.emitennews.com/news/kalbe-farma-klbf-batal-gelar-buyback-saham</loc><lastmod>2026-09-15</lastmod></url>
<url><loc>https://www.emitennews.com/tag/ihsg</loc><lastmod>2026-09-16</lastmod></url>
<url><loc>https://www.emitennews.com/news/tanpa-lastmod</loc></url>
</urlset>""",
    "https://www.emitennews.com/sitemap-current-2.xml": """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.emitennews.com/news/child-two-article</loc><lastmod>2026-08-20</lastmod></url>
</urlset>""",
    "https://www.emitennews.com/sitemap-current-3.xml": """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.emitennews.com/news/child-three-article</loc><lastmod>2026-07-30</lastmod></url>
</urlset>""",
}


def _crawler(max_children=2):
    c = EmitennewsCrawler()
    c.max_child_sitemaps = max_children
    fetched = []

    def get_soup(url):
        fetched.append(url)
        xml = INDEX_XML if url == INDEX_URL else CHILD_XML.get(url)
        # production parses sitemaps with html.parser, so tests must too
        return BeautifulSoup(xml, "html.parser") if xml else None

    c.page_loader = MagicMock()
    c.page_loader.get_soup = get_soup
    return c, fetched


class TestScrape:
    def test_EN01_does_not_raise_and_returns_news_links(self):
        c, _ = _crawler()
        rows = c._scrape(INDEX_URL, "news")
        links = [r["link"] for r in rows]
        assert "https://www.emitennews.com/news/sp-global-ingatkan-ini-ihsg-lanjut-tertekan?page=all" in links
        assert "https://www.emitennews.com/news/child-two-article?page=all" in links

    def test_EN02_non_news_urls_skipped(self):
        c, _ = _crawler()
        links = [r["link"] for r in c._scrape(INDEX_URL, "news")]
        assert not any("/tag/" in l for l in links)

    def test_EN03_only_first_max_child_sitemaps_are_fetched(self):
        c, fetched = _crawler(max_children=2)
        c._scrape(INDEX_URL, "news")
        children = [u for u in fetched if "sitemap-current" in u]
        assert children == [
            "https://www.emitennews.com/sitemap-current-1.xml",
            "https://www.emitennews.com/sitemap-current-2.xml",
        ]

    def test_EN04_none_walks_all_children(self):
        c, fetched = _crawler(max_children=None)
        rows = c._scrape(INDEX_URL, "news")
        assert sum("sitemap-current" in u for u in fetched) == 3
        assert any("child-three-article" in r["link"] for r in rows)

    def test_EN05_timestamp_is_lastmod_midnight_wib_not_now(self):
        c, _ = _crawler()
        rows = {r["link"]: r for r in c._scrape(INDEX_URL, "news")}
        ts = rows["https://www.emitennews.com/news/kalbe-farma-klbf-batal-gelar-buyback-saham?page=all"]["timestamp"]
        assert ts == datetime(2026, 9, 15, 0, 0, tzinfo=WIB)
        # stored day must be the WIB day, not the UTC day (SYS-11 guard)
        assert int(ts.strftime("%Y%m%d")) == 20260915

    def test_EN06_timestamp_is_stable_across_runs(self):
        c, _ = _crawler()
        first = c._scrape(INDEX_URL, "news")[0]["timestamp"]
        second = c._scrape(INDEX_URL, "news")[0]["timestamp"]
        assert first == second  # old code stamped now(): changed the dedup key every run

    def test_EN07_missing_lastmod_gives_none_and_is_dropped_by_get_sitemap(self):
        c, _ = _crawler()
        rows = {r["link"]: r for r in c._scrape(INDEX_URL, "news")}
        row = rows["https://www.emitennews.com/news/tanpa-lastmod?page=all"]
        assert row["timestamp"] is None
        assert EmitennewsCrawler._get_sitemap(row) is None

    def test_EN08_headline_from_slug(self):
        c, _ = _crawler()
        rows = {r["link"]: r for r in c._scrape(INDEX_URL, "news")}
        assert rows["https://www.emitennews.com/news/child-two-article?page=all"]["headline"] == "Child Two Article"

    def test_EN09_index_fetch_failure_returns_empty(self):
        c, _ = _crawler()
        c.page_loader.get_soup = lambda url: None
        assert c._scrape(INDEX_URL, "news") == []

    def test_EN10_full_row_converts_to_sitemap_dto(self):
        c, _ = _crawler()
        row = c._scrape(INDEX_URL, "news")[0]
        dto = EmitennewsCrawler._get_sitemap(row)
        assert dto is not None
        assert dto.sources == "EMITENNEWS"
        assert dto.category == "news"
        assert dto.timestamp == datetime(2026, 9, 16, 0, 0, tzinfo=WIB)
