"""
SRC-11 (#68): KumparanCrawler parsed the page's JSON-LD byline block with
eval() -- code execution from third-party page content, and a NameError (swallowed,
byline silently dropped) on any true/false/null literal, which Python does not
know but schema.org NewsArticle markup routinely carries
("isAccessibleForFree": true). Now json.loads, reading `author` as a Person
object, a list of them, or a bare string.

Fixture shape mirrors the live page (2026-09-20): two data-rh="true" ld+json
blocks, a NewsArticle with a Person author and a BreadcrumbList without one.
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.kumparan.kumparan_crawler import (
    KumparanCrawler,
)


def _page(*ld_blocks: str) -> BeautifulSoup:
    scripts = "".join(
        f'<script data-rh="true" type="application/ld+json">{block}</script>'
        for block in ld_blocks
    )
    return BeautifulSoup(f"<html><head>{scripts}</head><body></body></html>", "html.parser")


_BREADCRUMB = '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}'

_NEWS_ARTICLE_WITH_LITERALS = """{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "NasDem Pede Ajukan PT 7%",
  "isAccessibleForFree": true,
  "isPartOf": null,
  "hasPart": {"@type": "WebPageElement", "isAccessibleForFree": false},
  "author": {"@type": "Person", "name": "Abid Raihan", "url": "https://kumparan.com/abid-raihan"}
}"""


class TestKumparanReporterFromJsonLd:
    def test_true_false_null_literals_do_not_break_the_byline(self):
        # The exact failure eval() had: `true` is a NameError in Python.
        page = _page(_BREADCRUMB, _NEWS_ARTICLE_WITH_LITERALS)
        assert KumparanCrawler()._get_reporter_from_text(page) == ["Abid Raihan"]

    def test_breadcrumb_block_without_author_is_skipped(self):
        page = _page(_BREADCRUMB, '{"@type":"NewsArticle","author":{"@type":"Person","name":"Pojok Informasi"}}')
        assert KumparanCrawler()._get_reporter_from_text(page) == ["Pojok Informasi"]

    def test_author_list_yields_every_name(self):
        page = _page('{"@type":"NewsArticle","author":[{"@type":"Person","name":"A"},{"@type":"Person","name":"B"}]}')
        assert KumparanCrawler()._get_reporter_from_text(page) == ["A", "B"]

    def test_author_as_bare_string(self):
        page = _page('{"@type":"NewsArticle","author":"Redaksi kumparan"}')
        assert KumparanCrawler()._get_reporter_from_text(page) == ["Redaksi kumparan"]

    def test_no_ld_json_returns_empty_list_not_none(self):
        result = KumparanCrawler()._get_reporter_from_text(_page())
        assert result == []
        assert result is not None

    def test_malformed_json_is_skipped_not_raised(self):
        page = _page('{"@type": "NewsArticle", "author": {', _NEWS_ARTICLE_WITH_LITERALS)
        assert KumparanCrawler()._get_reporter_from_text(page) == ["Abid Raihan"]

    def test_python_code_in_the_block_is_never_executed(self):
        # eval() would have run this; json.loads rejects it.
        page = _page('__import__("os").system("echo pwned")')
        assert KumparanCrawler()._get_reporter_from_text(page) == []

    def test_blank_and_missing_names_are_dropped(self):
        page = _page('{"@type":"NewsArticle","author":[{"@type":"Person","name":"  "},{"@type":"Person"},{"@type":"Person","name":"C"}]}')
        assert KumparanCrawler()._get_reporter_from_text(page) == ["C"]


def test_no_eval_anywhere_in_newscrawler():
    """Done-when: `grep -rn "eval(" newscrawler/` is empty. Kept as a test so a
    future scraper can't reintroduce it unnoticed."""
    import os
    import re

    import newscrawler

    root = os.path.dirname(newscrawler.__file__)
    offenders = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    code = line.split("#", 1)[0]
                    if re.search(r"(?<![\w.])eval\(", code):
                        offenders.append(f"{os.path.relpath(path, root)}:{lineno}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)
