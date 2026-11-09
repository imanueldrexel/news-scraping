"""DBT-32 (#141): `scripts/repair_placeholder_headlines.py` ran once on 486
candidates with nothing but its dry-run as the guard. It will run again
(TEMPO's 74 pending rows, SRC-34's TIRTO/TEMPO widening), so its three
decisions are pinned here: which rows are candidates, what a fetched page
yields, and what the write touches. Offline; the live SQL is in
tests/integration/test_repair_placeholder_headlines_live.py."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

from repair_placeholder_headlines import (  # noqa: E402
    _CANDIDATES_SQL, _UPDATE_ARTICLE_SQL, _UPDATE_SITEMAP_SQL, apply_titles, fetch_title, find_placeholders,
)

TIRTO_SLUG = "https://tirto.id/rupiah-dan-ihsg-menguat-9-september-2026-ini-pergerakannya-hCa5?page=all"
TEMPO_SLUG = "https://www.tempo.co/ekonomi/apa-dampak-kelangkaan-bbm-bersubsidi-2287141?page=all"


def _row(sitemap_id, sources, headline, link, crawl_status="saved", has_article=True, article_title=None):
    return SimpleNamespace(sitemap_id=sitemap_id, sources=sources, headline=headline, link=link,
                           crawl_status=crawl_status, has_article=has_article, article_title=article_title)


class _Session:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((str(sql), params))
        return SimpleNamespace(fetchall=lambda: self._rows, rowcount=1)


class TestCandidateSelection:
    def test_sql_only_offers_rows_that_were_already_fetched(self):
        # The SQL, not Python, keeps `pending` rows out: the crawler fixes
        # those on fetch (SYS-33 live path); re-fetching them here would be
        # a second request for nothing.
        sql = str(_CANDIDATES_SQL)
        assert "a.sitemap_id IS NOT NULL OR s.crawl_status = 'rejected_filter'" in sql
        assert "LEFT JOIN articles" in sql
        assert ":websites" in sql

    def test_only_slug_placeholders_with_an_id_tail_are_candidates(self):
        rows = [
            _row(1, "TIRTO", "Rupiah Dan Ihsg Menguat 9 September 2026 Ini Pergerakannya Hca5", TIRTO_SLUG),
            _row(2, "TEMPO", "Apa Dampak Kelangkaan Bbm Bersubsidi 2287141", TEMPO_SLUG, "rejected_filter", False),
            # Already repaired: real title, not the slug.
            _row(3, "TIRTO", "Rupiah dan IHSG Menguat 9 September 2026, Ini Pergerakannya", TIRTO_SLUG),
            # Slug-equal but no id tail -- a genuine short Title Case headline (the 3,580 false positives of 7da6ced).
            _row(4, "KOMPAS", "Keadilan Terkubur Longsor", "https://kompas.example/keadilan-terkubur-longsor?page=all"),
            _row(5, "TIRTO", "", TIRTO_SLUG),
        ]
        session = _Session(rows)
        out = find_placeholders(session, ["TIRTO", "TEMPO"])
        assert [r.sitemap_id for r in out] == [1, 2]
        assert session.executed[0][1] == {"websites": ["TIRTO", "TEMPO"]}


class TestFetchTitle:
    def _crawler(self, html=None, raises=None):
        crawler = MagicMock()
        if raises:
            crawler.page_loader.get_soup.side_effect = raises
        else:
            crawler.page_loader.get_soup.return_value = None if html is None else BeautifulSoup(html, "html.parser")
        return crawler

    def test_og_title_wins(self):
        html = '<html><head><meta property="og:title" content=" Rupiah dan IHSG Menguat "/><title>x | Tirto</title></head></html>'
        assert fetch_title(self._crawler(html), TIRTO_SLUG) == ("Rupiah dan IHSG Menguat", None)

    def test_title_tag_is_the_fallback(self):
        html = "<html><head><title>Apa Dampak Kelangkaan BBM Bersubsidi</title></head></html>"
        assert fetch_title(self._crawler(html), TEMPO_SLUG) == ("Apa Dampak Kelangkaan BBM Bersubsidi", None)

    def test_no_title_no_document_and_exception_leave_the_row_unchanged(self):
        assert fetch_title(self._crawler("<html><body>nothing</body></html>"), TIRTO_SLUG) == (None, "page has no og:title/<title>")
        assert fetch_title(self._crawler(None), TIRTO_SLUG) == (None, "no document")
        title, err = fetch_title(self._crawler(raises=TimeoutError("read timed out")), TIRTO_SLUG)
        assert title is None and err.startswith("TimeoutError")


class TestApplyTitles:
    def test_writes_sitemap_always_article_only_where_one_exists_and_skips_untitled(self):
        rows = [
            _row(1, "TIRTO", "slug one", TIRTO_SLUG, has_article=True),
            _row(2, "TEMPO", "slug two", TEMPO_SLUG, "rejected_filter", has_article=False),
            _row(3, "TIRTO", "slug three", TIRTO_SLUG, has_article=True),   # fetch failed: no title
        ]
        session = _Session([])
        n_sitemaps, n_articles = apply_titles(session, rows, {1: "Real One", 2: "Real Two"})
        assert (n_sitemaps, n_articles) == (2, 1)
        statements = [(s, p["id"]) for s, p in session.executed]
        assert statements == [
            (str(_UPDATE_SITEMAP_SQL), 1), (str(_UPDATE_ARTICLE_SQL), 1),
            (str(_UPDATE_SITEMAP_SQL), 2),
        ]
        assert all(p["h"] in ("Real One", "Real Two") for _, p in session.executed)

    def test_update_statements_only_touch_rows_whose_value_differs(self):
        assert "IS DISTINCT FROM :h" in str(_UPDATE_SITEMAP_SQL)
        assert "IS DISTINCT FROM :h" in str(_UPDATE_ARTICLE_SQL)
        assert "jsonb_set" in str(_UPDATE_ARTICLE_SQL) and "'{title}'" in str(_UPDATE_ARTICLE_SQL)
