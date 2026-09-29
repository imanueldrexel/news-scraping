"""DBT-05 (#24): a source's extractor is declared, not discovered by failure.

Measured 2026-09-29 (EXPERIMENTS.md "DBT-05: extractor order"): 13 sources'
site selectors had been dead for months and trafilatura produced every saved
article; on the 15 whose selectors work, the selector is as good or more
precise. So `Crawler.PRIMARY_EXTRACTOR` says which one a source uses, the dead
selectors are gone, and the health check's FALLBACK means "the declared
extractor failed", not "this source has no selector".
"""
import importlib.util
import os
import sys

import pytest
from bs4 import BeautifulSoup

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

TRAFILATURA_FIRST = {"ANTARANEWS", "CNBC", "CNN", "IDNTIMES", "INEWS", "KONTAN", "KUMPARAN", "MERDEKA",
                     "OKEZONE", "PIKIRANRAKYAT", "SUARA", "TEMPO", "TIRTO"}
BODY = "Bank Indonesia menahan suku bunga acuan di level enam persen pada rapat bulan ini. " * 5


class _Loader:
    def get_soup(self, url):
        return BeautifulSoup(f"<html><body><article><p>{BODY}</p></article></body></html>", "html.parser")


def _crawler(primary, site_text=None, traf=BODY, newspaper=None):
    class C(Crawler):
        PRIMARY_EXTRACTOR = primary
        site_calls = 0

        def _get_whole_text(self_, soup):
            # Recorded, not raised: the crawler catches a site extractor's exceptions.
            type(self_).site_calls += 1
            return site_text

        def _get_reporter_from_text(self_, soup):
            return []
    c = C()
    c.website_name = "TEST"
    c.page_loader = _Loader()
    c._trafilatura_fallback = lambda soup: [traf] if traf else None
    c._newspaper_fallback = lambda url: [newspaper] if newspaper else None
    return c


def _fetch(crawler):
    dto, reason = crawler._fetch_news_details(SitemapDTO(headline="h", link="http://x/1", sources="TEST", sitemap_id=1))
    assert reason is None, reason
    return dto


class TestDeclaredPrimary:
    def test_trafilatura_first_never_runs_the_site_extractor(self):
        crawler = _crawler("trafilatura", site_text=[BODY + " from the site"])
        dto = _fetch(crawler)
        assert crawler.site_calls == 0, "the site extractor must not run for a trafilatura-first source"
        assert dto.meta_data["extractor"] == "trafilatura"
        assert dto.extracted_text == [BODY]

    def test_trafilatura_first_falls_back_to_newspaper(self):
        dto = _fetch(_crawler("trafilatura", site_text=None, traf=None, newspaper=BODY))
        assert dto.meta_data["extractor"] == "newspaper"

    def test_site_first_is_unchanged(self):
        assert _fetch(_crawler("site", site_text=[BODY])).meta_data["extractor"] == "site"
        assert _fetch(_crawler("site", site_text=None)).meta_data["extractor"] == "trafilatura"


class TestFleetDeclarations:
    def test_the_measured_sources_are_trafilatura_first(self):
        declared = {name for name, c in CRAWLER_DICT.items() if c.PRIMARY_EXTRACTOR == "trafilatura"}
        assert declared == TRAFILATURA_FIRST

    @pytest.mark.parametrize("name", sorted(CRAWLER_DICT))
    def test_a_declaration_matches_the_code(self, name):
        """A trafilatura-first crawler carries no selector (it would never run);
        a site-first crawler has one (the base returns None: every article a
        silent fallback)."""
        cls = type(CRAWLER_DICT[name])
        assert cls.PRIMARY_EXTRACTOR in ("site", "trafilatura")
        own_selector = "_get_whole_text" in vars(cls)
        assert own_selector == (cls.PRIMARY_EXTRACTOR == "site"), name


def _check_crawlers():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "scripts", "check_crawlers.py")
    spec = importlib.util.spec_from_file_location("check_crawlers_dbt05", path)
    mod = importlib.util.module_from_spec(spec)
    saved, sys.argv = sys.argv, ["check_crawlers.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


class TestHealthCheck:
    cc = _check_crawlers()

    def test_trafilatura_by_design_is_ok(self):
        assert self.cc.classify(10, 2, ["trafilatura", "trafilatura"], primary="trafilatura") == self.cc.STATUS_OK

    def test_the_declared_extractor_failing_is_fallback(self):
        assert self.cc.classify(10, 2, ["newspaper"], primary="trafilatura") == self.cc.STATUS_FALLBACK
        assert self.cc.classify(10, 2, ["trafilatura"], primary="site") == self.cc.STATUS_FALLBACK
