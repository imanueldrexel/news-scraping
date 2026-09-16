"""
SYS-04: crawl_newsdetails always logged crawl_log.article_count=0 for task=full_text
because `total_saved = 0` was declared in crawl_newsdetails but never incremented, and
_crawl_newsdetails_inner didn't return anything for it to be assigned from. The
extracted/passed_filter/saved funnel is also the most useful "is this scraper
rotting" signal, so it's tracked end-to-end and logged in one summary line.
"""
from unittest.mock import MagicMock, patch

import pytest

from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl


@pytest.fixture
def service():
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.semantic_filter.is_important.return_value = True
    svc.crawler_dict = {"TEST_SITE": MagicMock()}
    return svc


def make_article(sitemap_id):
    return NewsDetailsDTO(
        sitemap_id=sitemap_id,
        extracted_text=["Some economic news."],
        meta_data={"title": "Title"},
        reporter=["Reporter"],
    )


class TestCrawlLogArticleCount:
    def test_log_crawl_complete_receives_actual_saved_count_not_zero(self, service):
        service.data_flow_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=1)]
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [make_article(1)]
        service.data_flow_repo.save_chunk_data.return_value = [1]  # embedded

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.log_crawl_complete.assert_called_once_with(
            service.data_flow_repo.log_crawl_start.return_value, 1
        )

    def test_zero_articles_extracted_still_logs_zero_correctly(self, service):
        service.data_flow_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=1)]
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = []

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.log_crawl_complete.assert_called_once_with(
            service.data_flow_repo.log_crawl_start.return_value, 0
        )

    def test_articles_filtered_out_are_not_counted_as_saved(self, service):
        service.semantic_filter.is_important.return_value = False
        service.data_flow_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=1)]
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [make_article(1)]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.log_crawl_complete.assert_called_once_with(
            service.data_flow_repo.log_crawl_start.return_value, 0
        )

    def test_saved_count_sums_across_multiple_batches(self, service):
        # 25 sitemaps -> batch_size = ceil(25/10) = 3 -> batches of [3,3,3,3,3,3,3,3,1]
        sitemaps = [MagicMock(sitemap_id=i) for i in range(25)]
        service.data_flow_repo.load_sitemap_data.return_value = sitemaps

        def fake_batch_crawling_details(news, website_name):
            return [make_article(n.sitemap_id) for n in news]

        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = fake_batch_crawling_details
        service.data_flow_repo.save_chunk_data.side_effect = (
            lambda chunks: list({c.sitemap_id for c in chunks})
        )

        total_returned = service._crawl_newsdetails_inner("TEST_SITE")

        assert total_returned == 25
        service.crawl_newsdetails("TEST_SITE")
        service.data_flow_repo.log_crawl_complete.assert_called_once_with(
            service.data_flow_repo.log_crawl_start.return_value, 25
        )

    def test_embedded_sitemap_ids_empty_means_nothing_saved(self, service):
        """FAISS/chunk save can return no ids (e.g. all chunking failed) -- must not
        be counted as saved even though articles passed the semantic filter."""
        service.data_flow_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=1)]
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [make_article(1)]
        service.data_flow_repo.save_chunk_data.return_value = []

        result = service._crawl_newsdetails_inner("TEST_SITE")

        assert result == 0
        service.data_flow_repo.save_newsdetails_data.assert_not_called()
