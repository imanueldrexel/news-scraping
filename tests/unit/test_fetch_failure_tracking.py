"""
SYS-09: a sitemap whose fetch/extraction fails (soup was None, or _get_news_details
raised) was never marked in any way -- mark_sitemaps_attempted only covers the
sitemaps that made it into batch_crawling_details' return value, so a permanently
dead URL stayed at the front of the "no article yet" queue (posted_at DESC) and
consumed a retry slot on every single run, forever.

_crawl_newsdetails_inner must now call increment_fetch_failures with exactly the
sitemap_ids from `batch` that have no matching NewsDetailsDTO -- computed from the
DB-facing side (what came back), not from anything _get_news_details itself needs to
change about its return type.
"""
from unittest.mock import MagicMock, patch

import pytest

from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl


@pytest.fixture
def service():
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.crawler_dict = {"TEST_SITE": MagicMock()}
    svc.data_flow_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=i) for i in (1, 2, 3)]
    svc.data_flow_repo.save_newsdetails_data.side_effect = lambda dtos: [d.sitemap_id for d in dtos]
    svc.semantic_filter.is_important.return_value = True
    return svc


def article(sitemap_id, text="Berita ekonomi tentang suku bunga.", title="Title"):
    return NewsDetailsDTO(sitemap_id=sitemap_id, extracted_text=[text], meta_data={"title": title}, reporter=[])


def _all_failed_ids(mock_call):
    """With 3 sitemaps and the service's batch_size = max(1, ceil(n/10)), 3 items
    become 3 batches of 1 -- so increment_fetch_failures can be called once per
    batch rather than once for the whole run. Flatten every call's ids together."""
    ids = []
    for call in mock_call.call_args_list:
        ids.extend(call.args[0] if call.args else call.kwargs.get("sitemap_ids"))
    return ids


class TestFetchFailureDetection:
    def test_sitemap_missing_from_batch_result_is_counted_as_a_fetch_failure(self, service):
        # 3 sitemaps requested (ids 1,2,3), only 2 came back -- id 3's fetch/extraction failed.
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [article(1), article(2)]

        service.crawl_newsdetails("TEST_SITE")

        assert _all_failed_ids(service.data_flow_repo.increment_fetch_failures) == [3]

    def test_all_sitemaps_extracted_means_no_fetch_failures_recorded(self, service):
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(1), article(2), article(3)
        ]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.increment_fetch_failures.assert_not_called()

    def test_entire_batch_failing_is_still_recorded_even_though_the_batch_is_then_skipped(self, service):
        """batch_crawling_details returning [] (everything failed) used to `continue`
        immediately, with nothing else in the loop ever seeing those sitemap_ids --
        the exact case that let a source's queue fill up entirely with dead links."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = []

        service.crawl_newsdetails("TEST_SITE")

        assert sorted(_all_failed_ids(service.data_flow_repo.increment_fetch_failures)) == [1, 2, 3]
        # And the early `continue` still means no mark_sitemaps_attempted for them.
        service.data_flow_repo.mark_sitemaps_attempted.assert_not_called()

    def test_successful_sitemaps_are_not_also_counted_as_failures(self, service):
        """A mixed batch: only the genuinely-missing id must reach
        increment_fetch_failures, never one that has a real NewsDetailsDTO."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [article(1)]

        service.crawl_newsdetails("TEST_SITE")

        failed_ids = _all_failed_ids(service.data_flow_repo.increment_fetch_failures)
        assert 1 not in failed_ids
        assert sorted(failed_ids) == [2, 3]
