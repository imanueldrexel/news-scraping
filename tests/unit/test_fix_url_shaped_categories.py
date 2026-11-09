"""SRC-36 (#129) / SRC-41 (#135): the category repair maps each stored URL
through the crawler's own branch_name_from_url -- the same function
_get_branches uses -- and leaves anything that function cannot name alone."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

from fix_url_shaped_categories import plan  # noqa: E402
from newscrawler.infrastructure.datasource.scrapers.cnn.cnn_crawler import CNNCrawler  # noqa: E402
from newscrawler.infrastructure.datasource.scrapers.jpnn.jpnn_crawler import JPNNCrawler  # noqa: E402


class _Session:
    def __init__(self, rows):
        self._rows = rows
        self.params = None

    def execute(self, _sql, params=None):
        self.params = params
        return SimpleNamespace(fetchall=lambda: self._rows)


def _row(category, n, rejected=0):
    return SimpleNamespace(category=category, n=n, rejected=rejected)


class TestPlan:
    def test_cnn_urls_map_to_section_names_via_the_crawler(self):
        session = _Session([
            _row("https://www.cnnindonesia.com/gaya-hidup/sitemap_news.xml", 65, 49),
            _row("https://www.cnnindonesia.com/nasional/sitemap_news.xml", 160, 68),
        ])
        mapped, unmappable = plan(session, "CNN", CNNCrawler.branch_name_from_url)
        assert mapped == [
            ("https://www.cnnindonesia.com/gaya-hidup/sitemap_news.xml", "gaya-hidup", 65, 49),
            ("https://www.cnnindonesia.com/nasional/sitemap_news.xml", "nasional", 160, 68),
        ]
        assert unmappable == []
        assert session.params == {"src": "CNN"}

    def test_jpnn_regional_urls_keep_the_host_in_the_key(self):
        session = _Session([
            _row("https://bali.jpnn.com/sitemap_post_sport.xml", 92, 48),
            _row("https://www.jpnn.com/sitemap_post_politik.xml", 3),
        ])
        mapped, _ = plan(session, "JPNN", JPNNCrawler.branch_name_from_url)
        assert [(old, new) for old, new, _, _ in mapped] == [
            ("https://bali.jpnn.com/sitemap_post_sport.xml", "bali/sport"),
            ("https://www.jpnn.com/sitemap_post_politik.xml", "politik"),
        ]

    def test_a_url_the_crawler_cannot_name_is_reported_not_guessed(self):
        session = _Session([
            _row("https://www.cnnindonesia.com/nasional/politik/sitemap_news.xml", 7),
            _row("https://www.cnnindonesia.com/longform/sitemap_news.xml", 2),
            _row("https://www.cnnindonesia.com/ekonomi/sitemap_news.xml", 78),
        ])
        mapped, unmappable = plan(session, "CNN", CNNCrawler.branch_name_from_url)
        assert [new for _, new, _, _ in mapped] == ["ekonomi"]
        assert unmappable == [
            ("https://www.cnnindonesia.com/nasional/politik/sitemap_news.xml", 7),
            ("https://www.cnnindonesia.com/longform/sitemap_news.xml", 2),
        ]

    def test_a_namer_that_hands_back_a_url_is_treated_as_unmappable(self):
        # Belt and braces: a future crawler whose namer returns its input on
        # no match (the re.sub bug itself) must not be able to "repair" a URL
        # into the same URL.
        session = _Session([_row("https://x.example/sitemap_news.xml", 5)])
        mapped, unmappable = plan(session, "X", lambda link: link)
        assert mapped == []
        assert unmappable == [("https://x.example/sitemap_news.xml", 5)]
