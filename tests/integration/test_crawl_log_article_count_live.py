"""
SYS-04 against a live PostgreSQL: crawl_log.article_count for task='full_text' must
actually be persisted as the number of articles saved, not hard-coded 0. Uses the
real SQLAlchemyArticleDataSource (the actual log_crawl_start/log_crawl_complete
writer) against newsaggregator_test, with everything else (crawler, filter, chunk
storage) mocked out so no network call or FAISS write happens -- this isolates the
one thing the ticket's own "Done when" cares about: what lands in the real
crawl_log row.
"""
from unittest.mock import MagicMock, patch

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    return c


class TestArticleCountPersistedForFullText:
    def test_real_crawl_log_row_shows_actual_saved_count(self, client):
        from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
        from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
            SQLAlchemyArticleDataSource,
        )

        real_article_ds = SQLAlchemyArticleDataSource(client)

        mock_repo = MagicMock()
        mock_repo.log_crawl_start = real_article_ds.log_crawl_start
        mock_repo.log_crawl_complete = real_article_ds.log_crawl_complete
        mock_repo.log_crawl_failed = real_article_ds.log_crawl_failed
        mock_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=1)]
        mock_repo.save_chunk_data.return_value = [1]  # 1 sitemap_id embedded

        with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
            service = CrawlerServiceImpl(data_flow_repo=mock_repo)
        service.semantic_filter.is_important.return_value = True
        service.crawler_dict = {"SYS04_TEST": MagicMock()}
        service.crawler_dict["SYS04_TEST"].batch_crawling_details.return_value = [
            NewsDetailsDTO(
                sitemap_id=1,
                extracted_text=["Real economic news text."],
                meta_data={"title": "Title"},
                reporter=["Reporter"],
            )
        ]

        service.crawl_newsdetails("SYS04_TEST")

        with client.get_session() as s:
            row = s.execute(
                text(
                    "SELECT article_count, status FROM crawl_log "
                    "WHERE website = 'SYS04_TEST' AND task = 'full_text' "
                    "ORDER BY log_id DESC LIMIT 1"
                )
            ).fetchone()

        assert row is not None, "expected a crawl_log row to have been written"
        assert row.status == "completed"
        assert row.article_count == 1, f"expected article_count=1, got {row.article_count}"

        with client.get_session() as s:
            s.execute(text("DELETE FROM crawl_log WHERE website = 'SYS04_TEST'"))
            s.commit()
