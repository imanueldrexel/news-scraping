"""Tests for Crawler base class static methods. Coverage: GL, KW, GS, ND."""
import os
from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

os.environ.setdefault("VERBOSE", "False")
os.environ.setdefault("PARALLELIZE", "False")
os.environ.setdefault("REQUEST_MAX_RETRIES", "1")

from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.domain.entities.extraction.website_name import WebsiteName


def make_xml_url(link="http://example.com/article", title="Test Title",
                 keywords=None, pub_date="2024-01-01T12:00:00+07:00"):
    kw_tag = f"<news:keywords>{keywords}</news:keywords>" if keywords else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
      <url>
          <loc>{link}</loc>
          <news:title>{title}</news:title>
          {kw_tag}
          <news:publication_date>{pub_date}</news:publication_date>
      </url>
    </urlset>"""
    return BeautifulSoup(xml, "xml").find("url")


class _ConcreteCrawler(Crawler):
    def _get_reporter_from_text(self, soup) -> List[str]:
        return []
    @staticmethod
    def _get_branches(soup):
        return {}


class TestGetLink:
    def setup_method(self):
        self.crawler = _ConcreteCrawler()
        self.crawler.website_name = "KOMPAS"

    def test_GL01_appends_page_all(self):
        soup = make_xml_url(link="http://example.com/article")
        assert self.crawler._get_link(soup) == "http://example.com/article?page=all"

    def test_GL02_no_double_append(self):
        soup = make_xml_url(link="http://example.com/article?page=all")
        result = self.crawler._get_link(soup)
        assert result.count("?page=all") == 1

    def test_GL03_jpnn_no_page_all(self):
        self.crawler.website_name = "JPNN"
        soup = make_xml_url(link="http://jpnn.com/article")
        assert "?page=all" not in self.crawler._get_link(soup)


    def test_GL04_url_with_other_params_gets_page_all_appended(self):
        soup = make_xml_url(link="http://example.com/article?source=home")
        result = self.crawler._get_link(soup)
        assert result.endswith("?page=all")


class TestGetKeywords:
    def test_KW01_space_separated(self):
        soup = make_xml_url(keywords="economy finance")
        assert Crawler._get_keywords(soup) == ["economy", "finance"]

    def test_KW02_single(self):
        soup = make_xml_url(keywords="single")
        assert Crawler._get_keywords(soup) == ["single"]

    def test_KW03_comma_not_split(self):
        # _get_keywords splits on whitespace only: commas stick to tokens
        soup = make_xml_url(keywords="economy, finance")
        result = Crawler._get_keywords(soup)
        assert result == ["economy,", "finance"]

    def test_KW04_extra_whitespace(self):
        soup = make_xml_url(keywords="  economy  finance  ")
        assert Crawler._get_keywords(soup) == ["economy", "finance"]


class TestGetSitemap:
    def _valid(self, **kw):
        base = dict(headline="Title", link="http://ex.com", sources="KOMPAS",
                    category="economy", timestamp=datetime(2024,1,1,tzinfo=timezone.utc),
                    keywords=["k"])
        base.update(kw)
        return base

    def test_GS01_valid_returns_dto(self):
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        assert isinstance(Crawler._get_sitemap(self._valid()), SitemapDTO)

    def test_GS02_missing_headline_returns_none(self):
        assert Crawler._get_sitemap(self._valid(headline=None)) is None

    def test_GS03_missing_link_returns_none(self):
        assert Crawler._get_sitemap(self._valid(link=None)) is None

    def test_GS04_suara_category_no_longer_forced_to_none(self):
        # SRC-12 (#90): SUARA's category used to be forced to None because the
        # branch list was 20 hardcoded stale regional sitemaps with no real
        # section name; now _get_branches reads the real index and category is
        # a genuine section ("bisnis"), same as every other source.
        result = Crawler._get_sitemap(self._valid(sources=WebsiteName.SUARA.name, category="bisnis"))
        assert result is not None and result.category == "bisnis"


    def test_GS05_generic_exception_handler_itself_crashes(self):
        # BUG B7: the except BaseException handler calls articles_data.get('link'),
        # so if articles_data has no .get(), the handler re-raises instead of returning None.
        with pytest.raises(AttributeError):
            Crawler._get_sitemap(object())


class TestGetTimestamp:
    """SYS-11: _get_timestamp must hand back the WIB instant DateTimeReader.convert_date()
    already produced, not re-express it in UTC -- every downstream posted_at is
    int(dt.strftime("%Y%m%d")) on whatever this returns, so a UTC re-expression
    silently shifts 00:00-06:59 WIB articles onto the previous calendar day."""

    def _reader(self):
        from newscrawler.domain.utils.date_time_reader import DateTimeReader
        return DateTimeReader()

    def test_early_morning_wib_timestamp_keeps_its_own_calendar_day(self):
        soup = make_xml_url(pub_date="2026-09-16T03:00:00+07:00")
        dt = Crawler._get_timestamp(soup, self._reader())
        assert dt.strftime("%Y%m%d") == "20260916"
        assert dt.utcoffset() == timedelta(hours=7)

    def test_date_only_lastmod_style_value_keeps_its_own_day(self):
        soup = make_xml_url(pub_date="2026-09-16")
        dt = Crawler._get_timestamp(soup, self._reader())
        assert dt.strftime("%Y%m%d") == "20260916"

    def test_utc_input_that_crosses_midnight_into_wib_still_lands_on_the_wib_day(self):
        # 2026-09-15 17:30 UTC = 2026-09-16 00:30 WIB -- must store the WIB day.
        soup = make_xml_url(pub_date="2026-09-15T17:30:00Z")
        dt = Crawler._get_timestamp(soup, self._reader())
        assert dt.strftime("%Y%m%d") == "20260916"

    def test_no_publication_date_tag_returns_none(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>http://example.com/a</loc></url>
        </urlset>"""
        soup = BeautifulSoup(xml, "xml").find("url")
        assert Crawler._get_timestamp(soup, self._reader()) is None


class TestGetNewsDetails:
    def setup_method(self):
        self.crawler = _ConcreteCrawler()
        self.crawler.website_name = "KOMPAS"

    def _make_sitemap(self, link, website_name="KOMPAS"):
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        return SitemapDTO(headline="Test", link=link, sources=website_name)

    def test_ND01_jpnn_strips_page_all(self):
        called = []
        self.crawler.page_loader = MagicMock()
        self.crawler.page_loader.get_soup = lambda url: called.append(url) or None
        self.crawler.website_name = "JPNN"
        self.crawler._get_news_details(self._make_sitemap("http://jpnn.com/article?page=all"))
        assert called[0] == "http://jpnn.com/article"

    def test_ND02_non_jpnn_url_unchanged(self):
        called = []
        self.crawler.page_loader = MagicMock()
        self.crawler.page_loader.get_soup = lambda url: called.append(url) or None
        self.crawler._get_news_details(self._make_sitemap("http://kompas.com/article?page=all"))
        assert called[0] == "http://kompas.com/article?page=all"

    def test_ND03_none_soup_returns_none(self):
        self.crawler.page_loader = MagicMock()
        self.crawler.page_loader.get_soup = MagicMock(return_value=None)
        assert self.crawler._get_news_details(self._make_sitemap("http://ex.com")) is None


class TestLooksLikeAName:
    """SRC-10 (#65): a shared guard so a reporter selector that drifts onto a
    timestamp or numeric id (like IDXCHANNEL's did) can't silently produce a
    plausible-looking wrong value for any crawler."""

    def test_plain_digits_rejected(self):
        assert Crawler._looks_like_a_name("16") is False

    def test_date_with_time_rejected(self):
        assert Crawler._looks_like_a_name("16/09/2026 17:54 WIB") is False

    def test_iso_date_rejected(self):
        assert Crawler._looks_like_a_name("2026-09-16") is False

    def test_dotted_date_rejected(self):
        assert Crawler._looks_like_a_name("16.09.2026") is False

    def test_real_name_accepted(self):
        assert Crawler._looks_like_a_name("Desi Angriani") is True

    def test_blank_rejected(self):
        assert Crawler._looks_like_a_name("   ") is False

    def test_none_rejected(self):
        assert Crawler._looks_like_a_name(None) is False

    def test_name_containing_a_digit_is_still_accepted(self):
        """The guard rejects candidates that ARE a number/date, not ones that
        merely contain a digit somewhere (e.g. a name with a suffix)."""
        assert Crawler._looks_like_a_name("Tim Redaksi 2") is True


class _NumericReporterCrawler(_ConcreteCrawler):
    def _get_reporter_from_text(self, soup) -> List[str]:
        return ["16", "Desi Angriani", "16/09/2026 17:54 WIB"]


class TestReporterGuardWiredIntoGetNewsDetails:
    def test_non_name_candidates_are_filtered_out_of_the_dto(self):
        crawler = _NumericReporterCrawler()
        crawler.website_name = "TEST"
        crawler.page_loader = MagicMock()
        crawler.page_loader.get_soup = MagicMock(
            return_value=BeautifulSoup("<html><body><p>x</p></body></html>", "html.parser")
        )
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        dto = crawler._get_news_details(SitemapDTO(headline="t", link="http://ex.com/a", sources="TEST", sitemap_id=1))
        assert dto.reporter == ["Desi Angriani"]


_LONG = "Bank Indonesia mempertahankan suku bunga acuan di level 5,75 persen pada rapat dewan gubernur. " * 3
_CRAWLER_MOD = "newscrawler.infrastructure.datasource.scrapers.crawler"


class _FixedTextCrawler(Crawler):
    """Crawler whose site extractor returns a fixed value, to drive the fallback chain."""
    def __init__(self, site_text):
        super().__init__()
        self.website_name = "TEST"
        self._site_text = site_text
        self.page_loader = MagicMock()
        self.page_loader.get_soup = MagicMock(
            return_value=BeautifulSoup("<html><body><p>x</p></body></html>", "html.parser")
        )

    def _get_whole_text(self, soup):
        return self._site_text

    def _get_reporter_from_text(self, soup) -> List[str]:
        return []

    @staticmethod
    def _get_branches(soup):
        return {}


class TestExtractionFallback:
    """Issue #2 (SYS-01): [] and too-short text must reach the fallback extractors."""

    def _sitemap(self):
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        return SitemapDTO(headline="t", link="http://ex.com/a", sources="TEST", sitemap_id=1)

    def _run(self, site_text, trafilatura_text=_LONG, newspaper_text="", min_chars=200):
        import unittest.mock as _mock
        crawler = _FixedTextCrawler(site_text)
        with _mock.patch(f"{_CRAWLER_MOD}.MIN_ARTICLE_CHARS", min_chars), \
             _mock.patch("trafilatura.extract", return_value=trafilatura_text) as traf, \
             _mock.patch(f"{_CRAWLER_MOD}.Article") as art:
            art.return_value.text = newspaper_text
            dto = crawler._get_news_details(self._sitemap())
        return dto, traf, art

    def test_FB01_empty_list_from_site_extractor_falls_back_to_trafilatura(self):
        dto, traf, _ = self._run(site_text=[])
        traf.assert_called_once()
        assert dto.extracted_text == _LONG.split("\n\n")

    def test_FB02_none_from_site_extractor_falls_back_to_trafilatura(self):
        dto, traf, _ = self._run(site_text=None)
        traf.assert_called_once()
        assert dto.extracted_text == _LONG.split("\n\n")

    def test_FB03_short_site_text_below_min_chars_falls_back(self):
        dto, traf, _ = self._run(site_text=["Baca juga:"])
        traf.assert_called_once()
        assert dto.extracted_text == _LONG.split("\n\n")

    def test_FB04_usable_site_text_skips_fallbacks(self):
        site = [_LONG]
        dto, traf, art = self._run(site_text=site)
        traf.assert_not_called()
        art.assert_not_called()
        assert dto.extracted_text == site

    def test_FB05_trafilatura_empty_falls_through_to_newspaper(self):
        dto, _, art = self._run(site_text=[], trafilatura_text=None, newspaper_text=_LONG)
        art.assert_called_once()
        assert dto.extracted_text == _LONG.split("\n\n")

    def test_FB06_trafilatura_exception_falls_through_to_newspaper(self):
        import unittest.mock as _mock
        crawler = _FixedTextCrawler([])
        with _mock.patch("trafilatura.extract", side_effect=RuntimeError("boom")), \
             _mock.patch(f"{_CRAWLER_MOD}.Article") as art:
            art.return_value.text = _LONG
            dto = crawler._get_news_details(self._sitemap())
        assert dto.extracted_text == _LONG.split("\n\n")

    def test_FB07_all_extractors_empty_still_returns_dto_with_no_text(self):
        dto, _, _ = self._run(site_text=[], trafilatura_text=None, newspaper_text="")
        assert dto is not None
        assert not dto.extracted_text

    def test_FB08_failed_fallback_never_replaces_short_real_text(self):
        short = ["Kalimat pendek yang nyata."]
        dto, _, _ = self._run(site_text=short, trafilatura_text=None, newspaper_text="")
        assert dto.extracted_text == short

    def test_FB09_min_chars_zero_disables_length_check_but_not_empty_check(self):
        dto, traf, _ = self._run(site_text=["ok"], min_chars=0)
        traf.assert_not_called()
        assert dto.extracted_text == ["ok"]
        dto, traf, _ = self._run(site_text=[], min_chars=0)
        traf.assert_called_once()


class TestExtractorMetadata:
    """OPS-02: meta_data["extractor"] must record which extractor's output actually
    won, so check_crawlers.py (and articles.meta_data->>'extractor' in production)
    can tell "site selector works" apart from "a fallback is quietly doing all the
    work" -- both currently look identical as plain "OK"."""

    def _sitemap(self):
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        return SitemapDTO(headline="t", link="http://ex.com/a", sources="TEST", sitemap_id=1)

    def _run(self, site_text, trafilatura_text=_LONG, newspaper_text="", min_chars=200):
        import unittest.mock as _mock
        crawler = _FixedTextCrawler(site_text)
        with _mock.patch(f"{_CRAWLER_MOD}.MIN_ARTICLE_CHARS", min_chars), \
             _mock.patch("trafilatura.extract", return_value=trafilatura_text), \
             _mock.patch(f"{_CRAWLER_MOD}.Article") as art:
            art.return_value.text = newspaper_text
            return crawler._get_news_details(self._sitemap())

    def test_usable_site_text_is_labeled_site(self):
        dto = self._run(site_text=[_LONG])
        assert dto.meta_data["extractor"] == "site"

    def test_trafilatura_rescue_is_labeled_trafilatura(self):
        dto = self._run(site_text=[], trafilatura_text=_LONG)
        assert dto.meta_data["extractor"] == "trafilatura"

    def test_newspaper_rescue_is_labeled_newspaper(self):
        dto = self._run(site_text=[], trafilatura_text=None, newspaper_text=_LONG)
        assert dto.meta_data["extractor"] == "newspaper"

    def test_all_extractors_failing_labels_none(self):
        dto = self._run(site_text=[], trafilatura_text=None, newspaper_text="")
        assert dto.meta_data["extractor"] is None

    def test_nothing_usable_labels_none_even_if_a_short_candidate_won_best_of(self):
        """_best_of keeps the current (site) text when the fallback is even
        shorter, but neither is "usable" -- the final label is None (nothing usable
        came out of this article at all), not a misleading "site" for text too
        short to actually be useful."""
        dto = self._run(site_text=["short"], trafilatura_text="x", newspaper_text="")
        assert dto.meta_data["extractor"] is None


class _RaisingCrawler(_FixedTextCrawler):
    """Site extractors that blow up the way OKEZONE's do on a missing container."""
    def __init__(self, site_text=None, raise_body=False, raise_reporter=False):
        super().__init__(site_text)
        self._raise_body = raise_body
        self._raise_reporter = raise_reporter

    def _get_whole_text(self, soup):
        if self._raise_body:
            return soup.find("div", attrs={"class": "does-not-exist"}).find("p")  # AttributeError
        return self._site_text

    def _get_reporter_from_text(self, soup) -> List[str]:
        if self._raise_reporter:
            raise AttributeError("'NoneType' object has no attribute 'find'")
        return ["Reporter A"]


class TestExtractorCrashFallsThrough:
    """SYS-02: a crash inside a site extractor must not discard the article."""

    def _sitemap(self):
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        return SitemapDTO(headline="t", link="http://ex.com/a", sources="TEST", sitemap_id=1)

    def _run(self, crawler, trafilatura_text=_LONG):
        import unittest.mock as _mock
        with _mock.patch(f"{_CRAWLER_MOD}.MIN_ARTICLE_CHARS", 200), \
             _mock.patch("trafilatura.extract", return_value=trafilatura_text) as traf, \
             _mock.patch(f"{_CRAWLER_MOD}.Article") as art:
            art.return_value.text = ""
            dto = crawler._get_news_details(self._sitemap())
        return dto, traf

    def test_XC01_body_extractor_raises_uses_trafilatura(self):
        dto, traf = self._run(_RaisingCrawler(raise_body=True))
        assert dto is not None
        traf.assert_called_once()
        assert dto.extracted_text == _LONG.split("\n\n")
        assert dto.reporter == ["Reporter A"]

    def test_XC02_reporter_extractor_raises_keeps_site_text_and_empty_reporter(self):
        dto, traf = self._run(_RaisingCrawler(site_text=[_LONG], raise_reporter=True))
        assert dto is not None
        traf.assert_not_called()
        assert dto.extracted_text == [_LONG]
        assert dto.reporter == []

    def test_XC03_both_raise_still_yields_dto_via_fallback(self):
        dto, traf = self._run(_RaisingCrawler(raise_body=True, raise_reporter=True))
        assert dto is not None
        traf.assert_called_once()
        assert dto.extracted_text == _LONG.split("\n\n")
        assert dto.reporter == []
        assert dto.sitemap_id == 1  # so mark_sitemaps_attempted can stamp it

    def test_XC04_crash_is_logged_as_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger=_CRAWLER_MOD):
            self._run(_RaisingCrawler(raise_body=True))
        assert any("Site extractor raised" in r.message for r in caplog.records)

    def test_XC05_crash_plus_all_fallbacks_empty_still_yields_dto(self):
        """Re-audit gap: None text failed DTO validation -> returned None -> never marked."""
        dto, _ = self._run(_RaisingCrawler(raise_body=True), trafilatura_text=None)
        assert dto is not None
        assert dto.extracted_text == []
        assert dto.sitemap_id == 1

    def test_XC06_none_from_extractor_plus_all_fallbacks_empty_still_yields_dto(self):
        dto, _ = self._run(_RaisingCrawler(site_text=None), trafilatura_text=None)
        assert dto is not None
        assert dto.extracted_text == []


class TestHasUsableText:
    def test_UT01_none_empty_string_empty_list_are_unusable(self):
        for v in (None, "", [], [""], ["  "]):
            assert Crawler._has_usable_text(v) is False

    def test_UT02_length_counts_all_paragraphs(self):
        assert Crawler._text_length(["ab", "cd", ""]) == 4
        assert Crawler._text_length("  abc ") == 3

    def test_UT03_best_of_prefers_longer(self):
        assert Crawler._best_of(["short"], ["much longer text"]) == ["much longer text"]
        assert Crawler._best_of(["kept"], None) == ["kept"]
        assert Crawler._best_of(None, []) is None


class TestParallelizationGuard:
    def test_PAR01_mediaindonesia_always_sequential(self):
        crawler = _ConcreteCrawler()
        crawler.parallelize = True
        call_log = []
        def fake_get_sitemap(data):
            call_log.append(data)
            return None
        import unittest.mock as _mock
        with _mock.patch.object(_ConcreteCrawler, '_get_sitemap', staticmethod(fake_get_sitemap)):
            crawler.batch_crawling_sitemap(
                [{"headline": "x", "link": "http://a.com", "sources": "MEDIAINDONESIA"}],
                website_name=WebsiteName.MEDIAINDONESIA.value,
            )
        assert len(call_log) == 1

    def test_PAR02_non_mediaindonesia_with_parallelize_uses_executor(self):
        import unittest.mock as _mock
        crawler = _ConcreteCrawler()
        crawler.parallelize = True
        with _mock.patch(
            "newscrawler.infrastructure.datasource.scrapers.crawler.ThreadPoolExecutor"
        ) as mock_tpe:
            mock_tpe.return_value.__enter__ = _mock.MagicMock(
                return_value=_mock.MagicMock(map=lambda f, items: iter([]))
            )
            mock_tpe.return_value.__exit__ = _mock.MagicMock(return_value=False)
            crawler.batch_crawling_sitemap(
                [{"headline": "x", "link": "http://k.com", "sources": "KOMPAS"}],
                website_name="KOMPAS",
            )
        mock_tpe.assert_called_once()
