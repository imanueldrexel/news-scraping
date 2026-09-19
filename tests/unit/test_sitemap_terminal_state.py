"""
SYS-16: a sitemap rejected by the semantic filter and a sitemap whose extraction
came back empty both used to look identical to load_all_sitemaps -- last_crawl_attempt
set, no articles row -- so both were re-selected forever on the normal cooldown. A
filter rejection is deterministic (same headline/text, same INTERESTS list will
reject it again), so it should stop being re-queued; an empty extraction is transient
(a layout fix, or a later fetch, could still produce something), so it keeps the
normal cooldown retry.
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
    # SYS-04: the 'saved' stamp is now driven by what save_newsdetails_data reports
    # as actually committed, not by what was handed to it -- default to "everything
    # handed in commits" so this file's classification tests (not about persistence
    # failure) don't also have to restate the persistence layer's behavior.
    svc.data_flow_repo.save_newsdetails_data.side_effect = (
        lambda dtos: [d.sitemap_id for d in dtos]
    )
    return svc


def article(sitemap_id, text, title="Title"):
    return NewsDetailsDTO(sitemap_id=sitemap_id, extracted_text=text, meta_data={"title": title}, reporter=[])


class TestTerminalStateClassification:
    def test_off_topic_article_with_real_text_is_marked_rejected_filter(self, service):
        service.semantic_filter.is_important.return_value = False
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(1, ["Celebrity gossip about a wedding."])
        ]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_any_call([1], "rejected_filter")

    def test_empty_extraction_is_marked_empty_extraction_not_rejected_filter(self, service):
        service.semantic_filter.is_important.return_value = False
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(2, [])  # all extractors returned nothing usable
        ]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_any_call([2], "empty_extraction")
        calls = [c.args for c in service.data_flow_repo.mark_sitemaps_status.call_args_list]
        assert ([2], "rejected_filter") not in calls

    def test_important_and_embedded_article_is_marked_saved(self, service):
        service.semantic_filter.is_important.return_value = True
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(3, ["Real economic news about banking rates."])
        ]
        service.data_flow_repo.save_chunk_data.return_value = [3]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_any_call([3], "saved")

    def test_mixed_batch_classifies_each_sitemap_independently(self, service):
        def fake_is_important(text, category=None):
            return "banking" in text

        service.semantic_filter.is_important.side_effect = fake_is_important
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(1, ["Real economic news about banking rates."]),  # important -> saved
            article(2, ["Celebrity gossip."]),                        # rejected_filter
            article(3, []),                                           # empty_extraction
        ]
        service.data_flow_repo.save_chunk_data.return_value = [1]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_any_call([2], "rejected_filter")
        service.data_flow_repo.mark_sitemaps_status.assert_any_call([3], "empty_extraction")
        service.data_flow_repo.mark_sitemaps_status.assert_any_call([1], "saved")

    def test_a_filter_exception_marks_neither_status_and_stays_pending(self, service):
        """An error during filtering isn't a deterministic rejection -- it should
        neither be excluded permanently nor pinned to empty_extraction; leaving its
        crawl_status untouched (pending) means it retries at the normal cooldown."""
        service.semantic_filter.is_important.side_effect = ValueError("boom")
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(1, ["Some text."])
        ]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_not_called()
