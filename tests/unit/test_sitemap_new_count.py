"""
SYS-07 (reopened): crawl_log.article_count for task='sitemap' used to record
len(sitemaps_dtos) -- "entries listed" -- not "new sitemaps saved". A healthy source
re-lists most of its sitemap on every run, so that number told you nothing about
whether new articles actually showed up. save_sitemaps already computes
new_entries_count internally; SitemapSaveResult (a list subclass) carries it up
through save_sitemap -> save_sitemap_data -> crawl_sitemaps without changing what any
existing caller sees when it does len()/iterates/indexes the result.
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
    SitemapSaveResult,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
    SQLAlchemySitemapDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _data_source_with_mock_session(existing_rows=()):
    client = SQLAlchemyClient()
    session = MagicMock(name="session")
    session.query.return_value.filter.return_value.filter.return_value.all.return_value = list(existing_rows)
    session.query.return_value.filter.return_value.all.return_value = list(existing_rows)
    client.Session = MagicMock(return_value=session)
    return SQLAlchemySitemapDataSource(client), session


def make_sitemap(link="https://x/a", source="KOMPAS", posted_at=datetime(2026, 9, 16)):
    return NewsSitemapModel(headline="h", link=link, sources=source, category="finansial",
                            posted_at=posted_at, keywords=None)


class TestSitemapSaveResultType:
    def test_behaves_like_a_plain_list_for_len_iteration_and_indexing(self):
        result = SitemapSaveResult([1, 2, 3], new_count=2)
        assert len(result) == 3
        assert list(result) == [1, 2, 3]
        assert result[0] == 1
        assert isinstance(result, list)

    def test_default_new_count_is_zero(self):
        assert SitemapSaveResult([1, 2]).new_count == 0


class TestSaveSitemapsReportsNewCount:
    def test_all_new_entries_count_matches_the_full_batch(self):
        data_source, _ = _data_source_with_mock_session(existing_rows=[])
        result = data_source.save_sitemaps([make_sitemap("a"), make_sitemap("b")])
        assert len(result) == 2
        assert result.new_count == 2

    def test_a_re_listed_existing_entry_is_not_counted_as_new(self):
        existing_row = MagicMock(link="a", posted_at=20260916, sitemap_id=101)
        data_source, session = _data_source_with_mock_session(existing_rows=[existing_row])
        result = data_source.save_sitemaps([make_sitemap("a"), make_sitemap("b")])
        assert len(result) == 2          # both entries still come back with ids
        assert result.new_count == 1     # only "b" was actually new


class TestDataFlowRepositoryPreservesNewCount:
    def test_save_sitemap_data_carries_new_count_through_dto_conversion(self):
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
            DataFlowRepositoryImpl,
        )
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO

        repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
        repo.news_data_source = MagicMock()
        repo.news_data_source.save_sitemap.return_value = SitemapSaveResult(
            [make_sitemap("a")], new_count=1
        )

        result = repo.save_sitemap_data([
            SitemapDTO(headline="h", link="a", sources="KOMPAS", timestamp=datetime(2026, 9, 16), sitemap_id=None)
        ])

        assert len(result) == 1
        assert result.new_count == 1

    def test_falls_back_to_len_when_the_datasource_returns_a_plain_list(self):
        """Defensive: if a caller/mock returns a plain list (no .new_count), don't
        crash -- fall back to treating everything as new."""
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
            DataFlowRepositoryImpl,
        )
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO

        repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
        repo.news_data_source = MagicMock()
        repo.news_data_source.save_sitemap.return_value = [make_sitemap("a")]

        result = repo.save_sitemap_data([
            SitemapDTO(headline="h", link="a", sources="KOMPAS", timestamp=datetime(2026, 9, 16), sitemap_id=None)
        ])

        assert result.new_count == 1


def _sitemap_dto(i):
    from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
    return SitemapDTO(headline=f"h{i}", link=f"https://x/{i}", sources="KOMPAS")


class TestCrawlSitemapsLogsNewCountNotEntriesListed:
    def test_log_crawl_complete_receives_new_count_not_total_listed(self):
        from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
        from unittest.mock import patch

        with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
            service = CrawlerServiceImpl(data_flow_repo=MagicMock())
        service.crawler_dict = {"KOMPAS": MagicMock()}
        service.crawler_dict["KOMPAS"].get_news_in_bulk.return_value = ["raw"] * 5
        service.crawler_dict["KOMPAS"].batch_crawling_sitemap.return_value = [_sitemap_dto(i) for i in range(5)]
        # 5 entries listed, but only 1 was actually new.
        service.data_flow_repo.save_sitemap_data.return_value = SitemapSaveResult(
            [_sitemap_dto(i) for i in range(5)], new_count=1
        )

        service.crawl_sitemaps("KOMPAS")

        service.data_flow_repo.log_crawl_complete.assert_called_once_with(
            service.data_flow_repo.log_crawl_start.return_value, 1
        )

    def test_nothing_scraped_logs_zero(self):
        from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
        from unittest.mock import patch

        with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
            service = CrawlerServiceImpl(data_flow_repo=MagicMock())
        service.crawler_dict = {"KOMPAS": MagicMock()}
        service.crawler_dict["KOMPAS"].get_news_in_bulk.return_value = []
        service.crawler_dict["KOMPAS"].batch_crawling_sitemap.return_value = []

        service.crawl_sitemaps("KOMPAS")

        service.data_flow_repo.log_crawl_complete.assert_called_once_with(
            service.data_flow_repo.log_crawl_start.return_value, 0
        )
        service.data_flow_repo.save_sitemap_data.assert_not_called()
