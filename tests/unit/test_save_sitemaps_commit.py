"""
SYS-13: save_sitemaps must not swallow a failed COMMIT and return phantom
sitemap_ids. A failed commit has to propagate so get_session() rolls back and
crawl_sitemaps() marks the run failed instead of logging "Saved N sitemaps" and
letting task=all crawl articles for sitemap_ids that were never persisted.
No database needed: the session factory is replaced with a mock.
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
    SQLAlchemySitemapDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _data_source_with_mock_session():
    client = SQLAlchemyClient()  # create_engine is lazy; no connection is opened
    session = MagicMock(name="session")
    session.query.return_value.filter.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter.return_value.all.return_value = []
    client.Session = MagicMock(return_value=session)
    return SQLAlchemySitemapDataSource(client), session


def make_sitemap(link="https://x/a", source="KOMPAS"):
    return NewsSitemapModel(
        headline="h",
        link=link,
        sources=source,
        category="finansial",
        posted_at=datetime(2026, 9, 16),
        keywords=None,
    )


class TestSaveSitemapsCommitFailure:
    def test_failed_commit_propagates(self):
        data_source, session = _data_source_with_mock_session()
        session.commit.side_effect = Exception("server closed the connection unexpectedly")

        with pytest.raises(Exception, match="server closed the connection"):
            data_source.save_sitemaps([make_sitemap()])

    def test_failed_commit_rolls_back_via_get_session(self):
        data_source, session = _data_source_with_mock_session()
        session.commit.side_effect = Exception("server closed the connection unexpectedly")

        with pytest.raises(Exception):
            data_source.save_sitemaps([make_sitemap()])

        session.rollback.assert_called_once()
        session.close.assert_called_once()

    def test_no_ids_returned_on_the_failed_path(self):
        """Pre-fix behaviour: the function returned a list of sitemaps with
        sitemap_ids generated inside the rolled-back transaction. There must be no
        return value at all on this path -- the caller learns via the exception."""
        data_source, session = _data_source_with_mock_session()
        session.commit.side_effect = Exception("boom")
        result = None
        with pytest.raises(Exception):
            result = data_source.save_sitemaps([make_sitemap()])
        assert result is None

    def test_successful_commit_still_returns_populated_ids(self):
        data_source, session = _data_source_with_mock_session()

        result = data_source.save_sitemaps([make_sitemap()])

        assert len(result) == 1
        session.commit.assert_called_once()
