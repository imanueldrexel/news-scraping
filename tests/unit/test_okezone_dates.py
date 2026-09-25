"""SRC-51 (#163): OKEZONE's posted_at is the article's date from its URL, never
the sitemap's render-time stamp.

The recorded <urlset> below has OKEZONE's real shape: every <url> in the file
carries the SAME news:publication_date (the render time), while the URLs span
several days. The tests drive `_scrape`, the function that stores the date,
not just the helper (DBT-39's lesson: a regression test must call the code that
regressed).
"""
import importlib.util
import os
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.domain.utils.date_time_reader import DateTimeReader
from newscrawler.infrastructure.datasource.scrapers.okezone.okezone_crawler import OkezoneCrawler

RENDER_TIME = "2026-09-25T13:40:00+07:00"


def _url(loc, title="Judul"):
    return (f"<url><loc>{loc}</loc><news:news><news:publication>"
            f"<news:name>Okezone</news:name><news:language>id</news:language></news:publication>"
            f"<news:publication_date>{RENDER_TIME}</news:publication_date>"
            f"<news:title>{title}</news:title></news:news><lastmod>{RENDER_TIME}</lastmod></url>")


URLSET = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
    'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
    + _url("https://news.okezone.com/read/2026/09/22/337/3243001/satgas-tangkap-anggota-kkb")
    + _url("https://news.okezone.com/read/2026/08/14/337/3230000/sidang-lanjutan")
    + _url("https://video.okezone.com/play/2026/09/23/2/189509/veda-ega-pratama")
    + _url("https://foto.okezone.com/view/2026/09/24/1/12345/banjir-bekasi")
    + "</urlset>"
)


@pytest.fixture
def okezone(monkeypatch):
    """The registered crawler with its page loader stubbed -- restored after the
    test, since CRAWLER_DICT's instances are shared by the whole suite."""
    c = CRAWLER_DICT["OKEZONE"]
    loader = MagicMock()
    loader.get_soup = lambda url: BeautifulSoup(URLSET, "xml")
    monkeypatch.setattr(c, "page_loader", loader)
    return c


class TestScrapeStoresTheUrlDate:
    def test_every_row_gets_its_own_urls_date_not_the_render_time(self, okezone):
        rows = okezone._scrape("https://news.okezone.com/nasional/sitemap.xml", "news/nasional")
        days = [r["timestamp"].strftime("%Y%m%d") for r in rows]
        assert days == ["20260922", "20260814", "20260923", "20260924"]
        assert "20260925" not in days, "the render time leaked through"

    def test_the_day_is_in_wib_so_it_cannot_slip_a_day(self, okezone):
        """SYS-11: posted_at is int(dt.strftime('%Y%m%d')) on whatever tz this
        returns; a UTC midnight would already be the previous WIB day's 07:00."""
        rows = okezone._scrape("https://news.okezone.com/nasional/sitemap.xml", "news/nasional")
        assert all(r["timestamp"].utcoffset() == timedelta(hours=7) for r in rows)

    def test_a_row_survives_into_a_sitemap_dto_with_that_date(self, okezone):
        row = okezone._scrape("https://news.okezone.com/nasional/sitemap.xml", "news/nasional")[1]
        dto = OkezoneCrawler._get_sitemap(row)
        assert dto is not None
        assert dto.timestamp.strftime("%Y%m%d") == "20260814"


class TestDateFromUrl:
    @pytest.mark.parametrize("link,day", [
        ("https://economy.okezone.com/read/2026/09/22/320/3243001/harga-emas", "20260922"),
        ("https://video.okezone.com/play/2026/09/23/2/189509/x", "20260923"),
        ("https://foto.okezone.com/view/2026/09/24/1/12345/x", "20260924"),
        ("https://news.okezone.com/read/2026/9/5/337/1/x", "20260905"),
        ("  https://news.okezone.com/read/2026/09/22/337/1/x?page=all  ", "20260922"),
    ])
    def test_dated_shapes(self, link, day):
        assert OkezoneCrawler.date_from_url(link).strftime("%Y%m%d") == day

    @pytest.mark.parametrize("link", [
        "https://news.okezone.com/read/2026/02/30/337/1/x",       # not a date
        "https://news.okezone.com/tag/banjir",                    # no date
        "https://www.detik.com/read/2026/09/22/x",                # not OKEZONE
        "https://news.okezone.com/archive/2026/09/22/x",          # a path we have not verified
        "",
        None,
    ])
    def test_undated_is_none_never_a_guess(self, link):
        assert OkezoneCrawler.date_from_url(link) is None

    def test_no_loc_is_none(self):
        soup = BeautifulSoup(f"<url><news:publication_date>{RENDER_TIME}</news:publication_date></url>", "xml")
        assert OkezoneCrawler._get_timestamp(soup.find("url"), DateTimeReader()) is None


class TestOtherCrawlersUnchanged:
    def test_the_base_timestamp_still_trusts_publication_date(self):
        """The override is OKEZONE's, not a fleet change: the base reads the
        publication date as before."""
        soup = BeautifulSoup(_url("https://www.kompas.com/read/2026/09/22/x"), "xml")
        ts = CRAWLER_DICT["KOMPAS"]._get_timestamp(soup.find("url"), DateTimeReader())
        assert ts.strftime("%Y%m%d") == "20260925"
        assert ts.tzinfo is not None and ts.utcoffset() == timezone(timedelta(hours=7)).utcoffset(None)


# ── the stored-row repair ────────────────────────────────────────────────────
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "repair_posted_at_from_url.py",
)
_spec = importlib.util.spec_from_file_location("repair_posted_at_from_url", _SCRIPT)
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)


def _row(sid, link, posted_at, has_article=False):
    return SimpleNamespace(sitemap_id=sid, link=link, posted_at=posted_at, has_article=has_article)


class TestRepairPlan:
    def test_rewrites_only_rows_whose_url_date_differs(self):
        rows = [
            _row(1, "https://news.okezone.com/read/2026/09/22/337/1/x", 20260925),
            _row(2, "https://news.okezone.com/read/2026/09/25/337/2/x", 20260925),   # already right
            _row(3, "https://news.okezone.com/tag/x", 20260925),                     # undatable
        ]
        changes, undatable = repair.plan(rows, OkezoneCrawler.date_from_url)
        assert changes == [(1, 20260925, 20260922, False)]
        assert undatable == [(3, "https://news.okezone.com/tag/x")]

    def test_a_row_with_an_article_is_flagged_so_main_can_refuse(self):
        rows = [_row(1, "https://news.okezone.com/read/2026/09/22/337/1/x", 20260925, has_article=True)]
        changes, _ = repair.plan(rows, OkezoneCrawler.date_from_url)
        assert changes[0][3] is True
