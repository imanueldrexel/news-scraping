"""
Unit tests for the mark_sitemaps_attempted passthrough wiring:
DataFlowRepositoryImpl -> NewsDataSource -> SQLAlchemySitemapDataSource.
"""
from unittest.mock import MagicMock

from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
    DataFlowRepositoryImpl,
)
from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import (
    NewsDataSource,
)


class TestRepositoryPassthrough:
    def test_repo_delegates_to_news_data_source(self):
        repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
        repo.news_data_source = MagicMock()

        repo.mark_sitemaps_attempted([1, 2, 3])

        repo.news_data_source.mark_sitemaps_attempted.assert_called_once_with([1, 2, 3])


class TestNewsDataSourcePassthrough:
    def test_news_data_source_delegates_to_sitemap_source(self):
        nds = NewsDataSource.__new__(NewsDataSource)
        nds.sql_alchemy_sitemap = MagicMock()

        nds.mark_sitemaps_attempted([4, 5])

        nds.sql_alchemy_sitemap.mark_sitemaps_attempted.assert_called_once_with([4, 5])
