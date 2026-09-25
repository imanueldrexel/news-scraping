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



# -- SRC-33 (#119): branch keys --------------------------------------------------
from bs4 import BeautifulSoup as _BS  # noqa: E402

from newscrawler.core.crawler_dict_list import CRAWLER_DICT as _CD  # noqa: E402
from newscrawler.core.importance_filter import category_gate as _gate  # noqa: E402
from newscrawler.infrastructure.datasource.scrapers.viva.viva_crawler import VivaCrawler as _V  # noqa: E402

_VIVA_INDEX = _BS(
    '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
        "<sitemap><loc>%s</loc></sitemap>" % l for l in (
            "https://www.viva.co.id/sitemap/news/news-sitemap.xml",   # aggregate: skipped
            "https://www.viva.co.id/sitemap/web/news-sitemap.xml",    # web: skipped
            "https://www.viva.co.id/sitemap/photo/news-sitemap.xml",  # media: skipped
            "https://www.viva.co.id/sitemap/video/video.xml",
            "https://www.viva.co.id/sitemap/news/bisnis.xml",
            "https://www.viva.co.id/sitemap/web/bisnis.xml",          # lastmod-only duplicate
            "https://www.viva.co.id/sitemap/news/bola.xml",
            "https://www.viva.co.id/sitemap/tag/sitemap.xml",
            "https://jogja.viva.co.id/sitemap/news/news-sitemap.xml",
            "https://olret.viva.co.id/sitemap/news/news-sitemap.xml",
        )) + "</sitemapindex>", "xml")


def test_branch_keys_are_names_never_urls():
    assert _V._get_branches(_VIVA_INDEX) == {
        "bisnis": "https://www.viva.co.id/sitemap/news/bisnis.xml",
        "bola": "https://www.viva.co.id/sitemap/news/bola.xml",
        "jogja": "https://jogja.viva.co.id/sitemap/news/news-sitemap.xml",
        "olret": "https://olret.viva.co.id/sitemap/news/news-sitemap.xml",
    }


def test_the_soft_drop_keeps_bisnis_and_jogja():
    kept = _CD["VIVA"].drop_soft_branches(_V._get_branches(_VIVA_INDEX))
    assert set(kept) == {"bisnis", "jogja"}


def test_stored_url_shaped_categories_map_to_todays_key():
    assert _V.branch_name_from_url("https://jogja.viva.co.id/sitemap/news/news-sitemap.xml") == "jogja"
    assert _V.branch_name_from_url("https://www.viva.co.id/sitemap/news/bisnis.xml") == "bisnis"
    assert _V.branch_name_from_url("https://www.viva.co.id/sitemap/news/news-sitemap.xml") is None
    assert _V.branch_name_from_url("https://www.viva.co.id/sitemap/web/bisnis.xml") is None
    assert _V.branch_name_from_url("bisnis") is None


def test_viva_soft_leaves_are_denied_for_viva_only():
    for leaf in ("olret", "mindset", "otomotif", "vbuzz", "surat", "bandung"):
        assert _CD["VIVA"].is_soft_branch(leaf), leaf
        assert _gate(leaf, "VIVA") == "deny", leaf
    assert _gate("bandung", "KOMPAS") != "deny"   # KOMPAS's bandung desk is news
