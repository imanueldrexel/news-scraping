"""SRC-58 (#231): branches that can never load are not fetched (a host DNS says does not exist, a
`<loc>` with no host) or are reported apart as gone (HTTP 404/410, a redirect to a malformed URL), so
the OPS-35 note's "did not load" lists only branches that might load next time.

Measured 2026-10-06 (scripts/experiments/probe_dead_branches.py): PIKIRANRAKYAT lists 62 regional
subdomains that answer NXDOMAIN (getaddrinfo 11001); KONTAN `tv`, BERITASATU `b-series` and OKEZONE
`muslim/tausyiah` answer 404; KONTAN `pressrelease` redirects to 'https://.kontan.co.id/...'.
"""
import socket
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from newscrawler.core.page_loader import requests_page_loader
from newscrawler.core.page_loader.page_loader import PageLoader
from newscrawler.core.page_loader.requests_page_loader import host_resolves as real_host_resolves
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.datasource.scrapers.crawler import (
    Crawler, SitemapIndexUnavailable, is_gone_reason,
)

INDEX = "https://www.example.test/sitemap.xml"
URLSET = "<urlset><url><loc>https://www.example.test/a</loc></url></urlset>"
LIVE = "https://www.example.test/live.xml"
FLAKY = "https://jatim.example.test/news.xml"           # a live host whose sitemap answers 500 today
DEAD = "https://bocimiupdate.example.test/sitemap.xml"   # a host DNS says does not exist
MALFORMED = "https://.example.test/sitemap.xml"           # a <loc> with an empty host label
GONE = "https://tv.example.test/news/sitemap.xml"        # answers 404
REDIRECT = "https://pressrelease.example.test/news/sitemap.xml"
BRANCHES = {"live": LIVE, "jatim": FLAKY, "bocimi": DEAD, "pressrelease-bad": MALFORMED, "tv": GONE,
            "pressrelease": REDIRECT}


class _Loader(PageLoader):
    def __init__(self):
        self.requested = []
        self.reasons = {FLAKY: "HTTP 500", GONE: "HTTP 404",
                        REDIRECT: "request failed: LocationParseError: Failed to parse: '.example.test'"}

    def get_soup_with_reason(self, url):
        self.requested.append(url)
        if url in self.reasons:
            return None, self.reasons[url]
        return BeautifulSoup("<sitemapindex/>" if url == INDEX else URLSET, "html.parser"), None

    def get_soup(self, url):
        return self.get_soup_with_reason(url)[0]


class _Crawler(Crawler):
    def __init__(self, branches=None):
        super().__init__()
        self.website_name = "EXAMPLE"
        self.website_url = INDEX
        self.page_loader = _Loader()
        self.branches = dict(BRANCHES if branches is None else branches)

    def _get_branches(self, soup):
        return dict(self.branches)

    def _get_reporter_from_text(self, soup):
        return []


@pytest.fixture
def dns(monkeypatch):
    """Hosts DNS knows: everything but bocimiupdate. Records every lookup."""
    asked = []

    def resolves(host):
        asked.append(host)
        return host != "bocimiupdate.example.test"
    monkeypatch.setattr(requests_page_loader, "host_resolves", resolves)
    return asked


class TestDeadBranches:
    def test_a_dead_host_and_a_malformed_loc_are_never_requested(self, dns):
        c = _Crawler()
        listing = c.get_news_in_bulk()
        assert DEAD not in c.page_loader.requested and MALFORMED not in c.page_loader.requested
        assert sorted(listing.branches_skipped) == [
            ("bocimi", "host does not resolve: bocimiupdate.example.test"),
            ("pressrelease-bad", "malformed URL: 'https://.example.test/sitemap.xml'")]

    def test_a_live_branch_that_answers_500_is_still_fetched_and_reported(self, dns):
        listing = _Crawler().get_news_in_bulk()
        assert listing.branch_failures == [("jatim", "HTTP 500")]       # might load next time
        assert listing.branches_tried == 4 and len(listing) == 1

    def test_a_404_and_a_bad_redirect_are_gone_not_failures(self, dns):
        listing = _Crawler().get_news_in_bulk()
        assert [name for name, _ in listing.branches_gone] == ["tv", "pressrelease"]

    def test_each_host_is_looked_up_once_and_the_index_host_first(self, dns):
        _Crawler(dict(BRANCHES, live2="https://www.example.test/live2.xml")).get_news_in_bulk()
        assert dns[0] == "www.example.test"
        assert sorted(dns[1:]) == sorted({"www.example.test", "jatim.example.test", "bocimiupdate.example.test",
                                          "tv.example.test", "pressrelease.example.test"})

    def test_nothing_is_skipped_by_dns_while_the_index_host_does_not_resolve(self, monkeypatch):
        """No verdict on the index's own host (an outage): a "does not exist" is not trusted."""
        monkeypatch.setattr(requests_page_loader, "host_resolves", lambda host: None if host == "www.example.test"
                            else host != "bocimiupdate.example.test")
        c = _Crawler()
        listing = c.get_news_in_bulk()
        assert DEAD in c.page_loader.requested
        assert [name for name, _ in listing.branches_skipped] == ["pressrelease-bad"]   # malformed needs no DNS

    def test_a_lookup_without_a_verdict_does_not_skip(self, monkeypatch):
        monkeypatch.setattr(requests_page_loader, "host_resolves",
                            lambda host: None if host == "bocimiupdate.example.test" else True)
        c = _Crawler()
        c.get_news_in_bulk()
        assert DEAD in c.page_loader.requested

    def test_a_source_whose_every_branch_is_dead_still_fails(self, dns):
        with pytest.raises(SitemapIndexUnavailable, match=r"all 3 branch sitemap\(s\) failed to load"):
            _Crawler({"bocimi": DEAD, "tv": GONE, "pressrelease": REDIRECT}).get_news_in_bulk()


@pytest.mark.parametrize("reason,gone", [
    ("HTTP 404", True), ("HTTP 410", True), ("soft-404: redirected to https://x/404", True),
    ("request failed: LocationParseError: Failed to parse: '.kontan.co.id'", True),
    ("request failed: InvalidURL: bad", True),
    ("HTTP 500", False), ("HTTP 503", False), ("HTTP 403", False), ("ReadTimeout after 3 retries", False),
    ("NameResolutionError after 3 retries", False), (None, False),
])
def test_is_gone_reason(reason, gone):
    assert is_gone_reason(reason) is gone


@pytest.mark.parametrize("error,verdict", [
    (None, True),
    (socket.gaierror(socket.EAI_NONAME, "no such host"), False),
    (socket.gaierror(11001, "getaddrinfo failed"), False),            # Windows: WSAHOST_NOT_FOUND
    (socket.gaierror(11002, "temporary failure"), None),              # Windows: WSATRY_AGAIN
    (socket.gaierror(getattr(socket, "EAI_AGAIN", -3), "try again"), None),
    (UnicodeError("label too long"), None),
])
def test_host_resolves(monkeypatch, error, verdict):
    def getaddrinfo(host, port):
        if error is not None:
            raise error
        return [("addr",)]
    monkeypatch.setattr(requests_page_loader.socket, "getaddrinfo", getaddrinfo)
    assert real_host_resolves("x.example.test") is verdict


def test_the_crawl_note_lists_only_what_might_load_and_counts_the_rest_apart(dns):
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    crawler = _Crawler()
    crawler.batch_crawling_sitemap = MagicMock(return_value=[])
    svc.crawler_dict = {"EXAMPLE": crawler}
    svc.crawl_sitemaps("EXAMPLE")
    note = svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
    assert note == ("1 of 4 branch sitemap(s) did not load: jatim: HTTP 500 | "
                    "2 gone: tv: HTTP 404; pressrelease: request failed: LocationParseError: Failed to parse: "
                    "'.example.test' | 2 skipped, cannot load: bocimi, pressrelease-bad")
