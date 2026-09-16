"""
SYS-07 (reopened): CrawlerAPI.crawl_website("all") used to pass crawl_sitemaps' own
return value into crawl_newsdetails(specific_sitemaps=...) -- but that list is every
sitemap the site currently lists (existing rows included, since save_sitemaps' dedup
returns their ids too, not just newly-inserted ones), so it bypassed
load_all_sitemaps' "no articles row yet AND cooldown elapsed" filter entirely and
re-fetched every URL a site lists on every run. crawl_website("all") must now call
crawl_newsdetails with no specific_sitemaps, so it loads the filtered set from the DB
instead (the same path task="full_text" already uses).
"""
from unittest.mock import MagicMock

from newscrawler.application.api.crawler_api import CrawlerAPI


class TestAllTaskDoesNotBypassTheDbFilter:
    def test_all_task_calls_crawl_newsdetails_with_no_specific_sitemaps(self):
        svc = MagicMock()
        svc.crawl_sitemaps.return_value = [MagicMock(sitemap_id=1), MagicMock(sitemap_id=2)]
        api = CrawlerAPI(svc)

        api.crawl_website(website_name="KOMPAS", task="all")

        svc.crawl_sitemaps.assert_called_once_with(website_name="KOMPAS")
        svc.crawl_newsdetails.assert_called_once_with(website_name="KOMPAS")
        # The regression: specific_sitemaps must not be passed at all (not even as
        # crawl_sitemaps' return value) so crawl_newsdetails falls through to its own
        # load_sitemap_data(website, n_limit) branch.
        _, kwargs = svc.crawl_newsdetails.call_args
        assert "specific_sitemaps" not in kwargs

    def test_all_task_ignores_crawl_sitemaps_return_value_even_when_non_empty(self):
        """Even if crawl_sitemaps returns a huge list (every listed URL), it must not
        flow into crawl_newsdetails -- that was exactly the bypass."""
        svc = MagicMock()
        huge_list = [MagicMock(sitemap_id=i) for i in range(5000)]
        svc.crawl_sitemaps.return_value = huge_list
        api = CrawlerAPI(svc)

        api.crawl_website(website_name="EMITENNEWS", task="all")

        args, kwargs = svc.crawl_newsdetails.call_args
        assert huge_list not in args
        assert kwargs.get("specific_sitemaps") is None
