"""
SYS-17: SQLAlchemyChunkDataSource.get_existing_sitemap_ids is the SQL source of
truth save_chunk_data now dedups against, instead of FAISS membership.
"""
from unittest.mock import MagicMock

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
    SQLAlchemyChunkDataSource,
)


def _ds_with_mock_session(rows):
    client = MagicMock()
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [(r,) for r in rows]
    client.get_session.return_value.__enter__.return_value = session
    client.get_session.return_value.__exit__.return_value = False
    return SQLAlchemyChunkDataSource(client), session


class TestGetExistingSitemapIds:
    def test_returns_ids_present_in_chunks_table(self):
        ds, session = _ds_with_mock_session([10, 20])
        result = ds.get_existing_sitemap_ids([10, 20, 30])
        assert result == {10, 20}

    def test_empty_input_returns_empty_without_a_query(self):
        ds, session = _ds_with_mock_session([])
        result = ds.get_existing_sitemap_ids([])
        assert result == set()
        session.execute.assert_not_called()

    def test_query_is_scoped_to_the_given_ids(self):
        ds, session = _ds_with_mock_session([])
        ds.get_existing_sitemap_ids([1, 2, 3])
        params = session.execute.call_args[0][1]
        assert set(params["ids"]) == {1, 2, 3}
