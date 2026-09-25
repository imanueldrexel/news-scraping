"""SRC-38 (#131): KOMPAS publishes three sitemap indexes, and the crawler lists
all of them -- the finance desk (Kompas Money) had never been listed."""
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.core.importance_filter import category_gate
from newscrawler.infrastructure.datasource.scrapers.kompas.kompas_crawler import KompasCrawler


def _index(*locs):
    return BeautifulSoup(
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join("<sitemap><loc>%s</loc></sitemap>" % l for l in locs) + "</sitemapindex>", "xml")


NEWS = _index("https://nasional.kompas.com/news/sitemap.xml", "https://medan.kompas.com/news/sitemap.xml")
MONEY = _index("https://money.kompas.com/sitemap-basic.xml", "https://money.kompas.com/sitemap-news-money.xml",
               "https://money.kompas.com/sitemap-archive-money.xml")
WWW = _index("https://www.kompas.com/sitemap-basic.xml", "https://www.kompas.com/sitemap-news-global.xml",
             "https://www.kompas.com/sitemap-news-hype.xml", "https://www.kompas.com/sitemap-news-skola.xml",
             "https://www.kompas.com/sitemap-news-properti.xml", "https://www.kompas.com/sitemap-archive-global.xml",
             "https://www.kompas.com/sitemap-news-sulawesi-selatan.xml",
             "https://www.kompas.com/sitemap-news-sulawesi-selatan.xml",  # listed twice, live
             "https://www.kompas.com/something-unexpected.xml")


class TestGetBranches:
    def test_the_news_index_keeps_its_host_keys(self):
        assert KompasCrawler._get_branches(NEWS) == {
            "nasional": "https://nasional.kompas.com/news/sitemap.xml",
            "medan": "https://medan.kompas.com/news/sitemap.xml"}

    def test_the_money_index_yields_money_and_skips_basic_and_archive(self):
        assert KompasCrawler._get_branches(MONEY) == {"money": "https://money.kompas.com/sitemap-news-money.xml"}

    def test_www_sections_are_keyed_by_section_and_nothing_by_url(self):
        keys = set(KompasCrawler._get_branches(WWW))
        assert keys == {"global", "hype", "skola", "properti", "sulawesi-selatan"}
        assert not any(k.startswith("http") for k in keys)


@pytest.fixture
def kompas(monkeypatch):
    c = CRAWLER_DICT["KOMPAS"]
    pages = {c.website_url: NEWS, KompasCrawler.EXTRA_INDEX_URLS[0]: MONEY, KompasCrawler.EXTRA_INDEX_URLS[1]: WWW}
    loader = MagicMock()
    loader.get_soup = lambda url: pages.get(url)
    monkeypatch.setattr(c, "page_loader", loader)
    return c, pages


class TestListBranches:
    def test_all_three_indexes_are_merged(self, kompas):
        c, _ = kompas
        listed = c.list_branches()
        assert {"nasional", "medan", "money", "global", "properti"} <= set(listed)

    def test_the_soft_drop_keeps_money_and_drops_hype_and_skola(self, kompas):
        c, _ = kompas
        kept = c.drop_soft_branches(c.list_branches())
        assert "money" in kept and "global" in kept
        assert "hype" not in kept and "skola" not in kept

    def test_a_failing_extra_index_is_skipped_not_fatal(self, kompas):
        c, pages = kompas
        pages.pop(KompasCrawler.EXTRA_INDEX_URLS[1])
        listed = c.list_branches()
        assert "money" in listed and "global" not in listed

    def test_no_primary_index_is_none(self, kompas):
        c, pages = kompas
        pages.pop(c.website_url)
        assert c.list_branches() is None

    def test_a_single_index_crawler_is_unchanged(self):
        assert CRAWLER_DICT["CNBC"].EXTRA_INDEX_URLS == ()


@pytest.mark.parametrize("leaf", ["badminton", "motogp", "homey", "skola", "sains", "jawa-barat", "banten"])
def test_kompas_soft_leaves_are_denied_for_kompas_only(leaf):
    assert CRAWLER_DICT["KOMPAS"].is_soft_branch(leaf)
    assert category_gate(leaf, "KOMPAS") == "deny"
    assert category_gate(leaf, "DETIK") != "deny"


def test_money_and_properti_are_news_desks():
    assert category_gate("money", "KOMPAS") == "allow"
    assert category_gate("properti", "KOMPAS") == "allow"
