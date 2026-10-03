"""OPS-35 (#207): a source whose sitemap index (or every branch sitemap) did
not load used to be recorded exactly like a healthy source with nothing new:
`get_news_in_bulk` returned [] and `crawl_sitemaps` logged `completed, 0`.
TEMPO's Cloudflare 403 looked healthy in crawl_log for days.
"""
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from newscrawler.core.page_loader.page_loader import PageLoader
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.datasource.scrapers.crawler import (
    Crawler, SitemapIndexUnavailable, SitemapListing,
)

INDEX = "https://example.test/sitemap.xml"
BRANCHES = {"nasional": "https://example.test/nasional.xml", "ekonomi": "https://example.test/ekonomi.xml"}
URLSET = "<urlset><url><loc>https://example.test/a</loc></url></urlset>"


class _Loader(PageLoader):
    """`pages` maps URL -> XML text; any other URL answers `missing`."""

    def __init__(self, pages, missing="HTTP 403"):
        self.pages = pages
        self.missing = missing

    def get_soup_with_reason(self, url):
        if url in self.pages:
            return BeautifulSoup(self.pages[url], "html.parser"), None
        return None, self.missing

    def get_soup(self, url):
        return self.get_soup_with_reason(url)[0]


class _Crawler(Crawler):
    def __init__(self, loader):
        super().__init__()
        self.website_name = "EXAMPLE"
        self.website_url = INDEX
        self.page_loader = loader

    def _get_branches(self, soup):
        return dict(BRANCHES)

    def _get_reporter_from_text(self, soup):
        return []


class TestGetNewsInBulk:
    def test_an_index_that_does_not_load_raises_with_the_loaders_reason(self):
        c = _Crawler(_Loader({}, missing="HTTP 403"))
        with pytest.raises(SitemapIndexUnavailable, match="sitemap index did not load: HTTP 403"):
            c.get_news_in_bulk()

    def test_list_branches_keeps_its_none_contract_for_the_probes(self):
        assert _Crawler(_Loader({})).list_branches() is None

    def test_every_branch_failing_raises(self):
        c = _Crawler(_Loader({INDEX: "<sitemapindex/>"}, missing="HTTP 503"))
        with pytest.raises(SitemapIndexUnavailable, match=r"all 2 branch sitemap\(s\) failed to load, e.g. HTTP 503"):
            c.get_news_in_bulk()

    def test_a_partial_failure_rides_on_the_result(self):
        c = _Crawler(_Loader({INDEX: "<sitemapindex/>", BRANCHES["ekonomi"]: URLSET}, missing="HTTP 404"))
        listing = c.get_news_in_bulk()
        assert isinstance(listing, SitemapListing) and len(listing) == 1
        assert listing.branch_failures == [("nasional", "HTTP 404")]
        assert listing.branches_tried == 2

    def test_a_healthy_source_has_no_failures(self):
        pages = {INDEX: "<sitemapindex/>", **{u: URLSET for u in BRANCHES.values()}}
        listing = _Crawler(_Loader(pages)).get_news_in_bulk()
        assert len(listing) == 2 and listing.branch_failures == []

    def test_failures_do_not_leak_into_the_next_call(self):
        pages = {INDEX: "<sitemapindex/>", BRANCHES["ekonomi"]: URLSET}
        loader = _Loader(pages)
        c = _Crawler(loader)
        assert len(c.get_news_in_bulk().branch_failures) == 1
        loader.pages[BRANCHES["nasional"]] = URLSET
        assert c.get_news_in_bulk().branch_failures == []


def _service(crawler):
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.crawler_dict = {"EXAMPLE": crawler}
    return svc


class TestCrawlSitemaps:
    def test_a_dead_index_is_a_failed_run_with_the_reason(self):
        svc = _service(_Crawler(_Loader({}, missing="HTTP 403")))
        with pytest.raises(SitemapIndexUnavailable):
            svc.crawl_sitemaps("EXAMPLE")
        repo = svc.data_flow_repo
        repo.log_crawl_complete.assert_not_called()
        msg = repo.log_crawl_failed.call_args.args[1]
        assert "sitemap index did not load: HTTP 403" in msg

    def test_a_partial_failure_is_a_completed_run_with_a_note(self):
        crawler = _Crawler(_Loader({INDEX: "<sitemapindex/>", BRANCHES["ekonomi"]: URLSET}, missing="HTTP 404"))
        crawler.batch_crawling_sitemap = MagicMock(return_value=[])
        svc = _service(crawler)

        svc.crawl_sitemaps("EXAMPLE")

        note = svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert note == "1 of 2 branch sitemap(s) did not load: nasional: HTTP 404"
        svc.data_flow_repo.log_crawl_failed.assert_not_called()
