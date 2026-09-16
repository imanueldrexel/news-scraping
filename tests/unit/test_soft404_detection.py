"""
SYS-14: RequestsPageLoader.get_soup must reject soft-404s -- an HTTP 200 response
that was actually redirected to (or renders in place) an error/home page instead
of the requested article. Previously any status_code == 200 was accepted, so a
307 -> /404 -> 200 chain (or an in-place error page) flowed into the extractor
chain and got saved as an article body.
No network needed: RequestsPageLoader.get_url is patched to return a fake response.
"""
from unittest.mock import MagicMock, patch

from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader


def make_response(status_code=200, url="https://site.test/news/some-article", history=None,
                   html=b"<html><head></head><body>real article text</body></html>"):
    response = MagicMock()
    response.status_code = status_code
    response.url = url
    response.history = history or []
    response.content = html
    return response


class TestSoftDetection:
    def test_redirect_to_404_returns_none(self):
        loader = RequestsPageLoader()
        response = make_response(
            url="https://site.test/404",
            history=[MagicMock(status_code=307)],
        )
        with patch.object(loader, "get_url", return_value=response):
            assert loader.get_soup("https://site.test/news/missing") is None

    def test_redirect_that_lands_on_a_real_article_path_is_not_rejected(self):
        loader = RequestsPageLoader()
        response = make_response(
            url="https://site.test/news/some-article?page=all",
            history=[MagicMock(status_code=301)],
        )
        with patch.object(loader, "get_url", return_value=response):
            assert loader.get_soup("https://site.test/news/some-article") is not None

    def test_no_redirect_no_error_canonical_returns_soup(self):
        loader = RequestsPageLoader()
        html = (
            b"<html><head><link rel='canonical' href='https://site.test/news/some-article'>"
            b"</head><body>real article text</body></html>"
        )
        response = make_response(html=html)
        with patch.object(loader, "get_url", return_value=response):
            assert loader.get_soup("https://site.test/news/some-article") is not None

    def test_canonical_pointing_to_error_page_returns_none(self):
        """Covers the 'error page rendered in place, no redirect' variant of SYS-14."""
        loader = RequestsPageLoader()
        html = (
            b"<html><head><link rel='canonical' href='https://site.test/404'></head>"
            b"<body>IDXINDUST 1.03% IDXINFRA -0.22%</body></html>"
        )
        response = make_response(url="https://site.test/news/not-yet-published", html=html)
        with patch.object(loader, "get_url", return_value=response):
            assert loader.get_soup("https://site.test/news/not-yet-published") is None

    def test_non_200_status_still_returns_none(self):
        loader = RequestsPageLoader()
        response = make_response(status_code=500)
        with patch.object(loader, "get_url", return_value=response):
            assert loader.get_soup("https://site.test/news/some-article") is None

    def test_no_response_returns_none(self):
        loader = RequestsPageLoader()
        with patch.object(loader, "get_url", return_value=None):
            assert loader.get_soup("https://site.test/news/some-article") is None
