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
    # SYS-04: save_newsdetails_data's return value now drives saved_total and the
    # 'saved' status stamp (what actually committed), not len(to_save). Default the
    # mock to "everything handed in commits" so tests about the extraction/filter
    # funnel don't also have to restate the persistence layer's behavior; tests
    # about partial/total persistence failure override this per-test.
    svc.data_flow_repo.save_newsdetails_data.side_effect = (
        lambda dtos: [d.sitemap_id for d in dtos]
    )
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

    def test_all_rows_failing_persistence_reports_zero_and_stamps_nothing_saved(self, service):
        """SYS-04 (reopened): save_newsdetails_data can commit fewer rows than it
        was handed (each row fails inside its own SYS-15 savepoint). If every row
        fails, article_count must be 0 and no sitemap may be stamped 'saved' --
        before this fix, both reported the rows as saved regardless."""
        service.data_flow_repo.load_sitemap_data.return_value = [
            MagicMock(sitemap_id=1), MagicMock(sitemap_id=2)
        ]

        def fake_batch_crawling_details(news, website_name):
            return [make_article(n.sitemap_id) for n in news]

        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = fake_batch_crawling_details
        service.data_flow_repo.save_chunk_data.side_effect = (
            lambda chunks: list({c.sitemap_id for c in chunks})
        )
        # Every row fails its own savepoint inside save_newsdetails_data -- nothing
        # actually committed, even though both were handed to persistence.
        service.data_flow_repo.save_newsdetails_data.side_effect = None
        service.data_flow_repo.save_newsdetails_data.return_value = []

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.log_crawl_complete.assert_called_once_with(
            service.data_flow_repo.log_crawl_start.return_value, 0
        )
        saved_calls = [
            c for c in service.data_flow_repo.mark_sitemaps_status.call_args_list
            if c.args[1] == "saved"
        ]
        assert saved_calls == [], f"no sitemap should be stamped 'saved': {saved_calls}"

    def test_partial_persistence_failure_counts_only_the_committed_half(self, service):
        """SYS-04 (reopened): if half the rows fail their savepoint, article_count
        and the 'saved' stamp must reflect only the half that actually committed."""
        service.data_flow_repo.load_sitemap_data.return_value = [
            MagicMock(sitemap_id=1), MagicMock(sitemap_id=2)
        ]

        def fake_batch_crawling_details(news, website_name):
            return [make_article(n.sitemap_id) for n in news]

        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = fake_batch_crawling_details
        service.data_flow_repo.save_chunk_data.side_effect = (
            lambda chunks: list({c.sitemap_id for c in chunks})
        )
        # sitemap_id=2's row fails its savepoint; only sitemap_id=1 ever commits.
        service.data_flow_repo.save_newsdetails_data.side_effect = (
            lambda dtos: [d.sitemap_id for d in dtos if d.sitemap_id == 1]
        )

        result = service._crawl_newsdetails_inner("TEST_SITE")

        assert result == 1
        saved_calls = [
            c for c in service.data_flow_repo.mark_sitemaps_status.call_args_list
            if c.args[1] == "saved"
        ]
        assert [c.args[0] for c in saved_calls] == [[1]], (
            f"only the committed sitemap should be stamped 'saved': {saved_calls}"
        )
