"""
OPS-15 (#81): the reason a page could not be fetched/extracted must travel from
RequestsPageLoader through Crawler.batch_crawling_details to the service layer,
so sitemaps.last_fetch_error says "HTTP 404" or "ReadTimeout after 5 retries"
instead of one constant string for every row. get_soup/get_url/_get_news_details
keep their old return shapes; the *_with_reason variants carry the extra value,
and batch_crawling_details returns a NewsDetailsBatch (a list) with `.failures`.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from newscrawler.core.page_loader.page_loader import PageLoader
from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler, NewsDetailsBatch

GET = "newscrawler.core.page_loader.requests_page_loader.requests.get"


def _response(status=200, url="http://x/a", content=b"<html><body><p>hi</p></body></html>", history=()):
    return SimpleNamespace(status_code=status, url=url, content=content, history=list(history))


class TestLoaderReasons:
    def test_http_status_is_the_reason(self):
        with patch(GET, return_value=_response(status=404)):
            soup, reason = RequestsPageLoader().get_soup_with_reason("http://x/a")
        assert soup is None
        assert reason == "HTTP 404"

    def test_timeout_after_retries_names_the_exception_and_the_retry_count(self):
        loader = RequestsPageLoader()
        with patch(GET, side_effect=requests.exceptions.ReadTimeout("t")):
            soup, reason = loader.get_soup_with_reason("http://x/a")
        assert soup is None
        assert reason == f"ReadTimeout after {loader.max_retries} retries"

    def test_connection_error_after_retries_is_distinguishable_from_a_timeout(self):
        loader = RequestsPageLoader()
        with patch(GET, side_effect=requests.exceptions.ConnectionError("reset")):
            _, reason = loader.get_soup_with_reason("http://x/a")
        assert reason == f"ConnectionError after {loader.max_retries} retries"

    def test_other_request_exception_is_reported_by_type(self):
        with patch(GET, side_effect=requests.exceptions.InvalidURL("bad")):
            _, reason = RequestsPageLoader().get_soup_with_reason("http://x/a")
        assert reason.startswith("request failed: InvalidURL")

    def test_soft_404_redirect_is_the_reason(self):
        resp = _response(url="http://x/404", history=[object()])
        with patch(GET, return_value=resp):
            soup, reason = RequestsPageLoader().get_soup_with_reason("http://x/a")
        assert soup is None
        assert reason == "soft-404: redirected to http://x/404"

    def test_soft_404_canonical_is_the_reason(self):
        html = b'<html><head><link rel="canonical" href="http://x/not-found"></head><body></body></html>'
        with patch(GET, return_value=_response(content=html)):
            soup, reason = RequestsPageLoader().get_soup_with_reason("http://x/a")
        assert soup is None
        assert reason == "soft-404: canonical http://x/not-found"

    def test_success_has_no_reason_and_get_soup_still_returns_the_soup(self):
        with patch(GET, return_value=_response()):
            loader = RequestsPageLoader()
            soup, reason = loader.get_soup_with_reason("http://x/a")
            plain = loader.get_soup("http://x/a")
        assert reason is None
        assert soup is not None and soup.find("p").text == "hi"
        assert plain is not None

    def test_base_loader_default_reason_for_a_loader_that_only_implements_get_soup(self):
        class Legacy(PageLoader):
            def get_soup(self, url):
                return None
        assert Legacy().get_soup_with_reason("http://x") == (None, "page loader returned no document")


def _sitemap(i):
    return SitemapDTO(headline=f"h{i}", link=f"http://x/{i}", sources="TEST", sitemap_id=i)


class _ScriptedLoader(PageLoader):
    """A real PageLoader (so Crawler._load_page asks it for reasons) whose
    get_soup_with_reason is a MagicMock the test scripts."""

    def __init__(self):
        self.get_soup_with_reason = MagicMock()

    def get_soup(self, url):
        return self.get_soup_with_reason(url)[0]


class TestBatchCarriesFailures:
    @pytest.fixture
    def crawler(self):
        c = Crawler()
        c.website_name = "TEST"
        c.parallelize = False
        c.page_loader = _ScriptedLoader()
        return c

    def test_failed_sitemaps_are_listed_with_their_loader_reason(self, crawler):
        crawler.page_loader.get_soup_with_reason.side_effect = [
            (None, "HTTP 404"),
            (None, "ReadTimeout after 5 retries"),
        ]

        result = crawler.batch_crawling_details([_sitemap(1), _sitemap(2)], "TEST")

        assert isinstance(result, NewsDetailsBatch) and list(result) == []
        assert result.failures == {1: "HTTP 404", 2: "ReadTimeout after 5 retries"}

    def test_an_exception_in_extraction_is_reported_by_type(self, crawler):
        crawler.page_loader.get_soup_with_reason.return_value = (MagicMock(name="soup"), None)
        with patch.object(crawler, "_get_whole_text", side_effect=RuntimeError("layout gone")), \
             patch.object(crawler, "_get_reporter_from_text", return_value=[]), \
             patch.object(crawler, "_trafilatura_fallback", side_effect=KeyError("boom")):
            result = crawler.batch_crawling_details([_sitemap(7)], "TEST")

        assert list(result) == []
        assert result.failures[7].startswith("KeyError")

    def test_successes_are_not_in_failures(self, crawler):
        soup = MagicMock(name="soup")
        soup.__bool__ = lambda self: True
        crawler.page_loader.get_soup_with_reason.side_effect = [(soup, None), (None, "HTTP 500")]
        with patch.object(crawler, "_get_whole_text", return_value=["p " * 200]), \
             patch.object(crawler, "_get_reporter_from_text", return_value=["A"]):
            result = crawler.batch_crawling_details([_sitemap(1), _sitemap(2)], "TEST")

        assert [d.sitemap_id for d in result] == [1]
        assert result.failures == {2: "HTTP 500"}

    def test_parallel_path_keeps_sitemap_to_reason_alignment(self, crawler):
        crawler.parallelize = True
        crawler.max_worker = 4
        crawler.page_loader.get_soup_with_reason.side_effect = lambda url: (None, f"HTTP {url[-1]}00")

        result = crawler.batch_crawling_details([_sitemap(i) for i in range(1, 6)], "TEST")

        assert result.failures == {i: f"HTTP {i}00" for i in range(1, 6)}

    def test_get_news_details_still_returns_a_dto_or_none(self, crawler):
        crawler.page_loader.get_soup_with_reason.return_value = (None, "HTTP 404")
        assert crawler._get_news_details(_sitemap(1)) is None

    def test_a_loader_that_is_not_a_pageloader_gets_the_generic_reason(self, crawler):
        """Test doubles and any custom object with only get_soup keep working."""
        crawler.page_loader = MagicMock()
        crawler.page_loader.get_soup.return_value = None

        result = crawler.batch_crawling_details([_sitemap(1)], "TEST")

        assert result.failures == {1: "page loader returned no document"}
        crawler.page_loader.get_soup.assert_called_once_with("http://x/1")
