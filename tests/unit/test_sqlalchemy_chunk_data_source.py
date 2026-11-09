"""
SYS-17: SQLAlchemyChunkDataSource.get_existing_sitemap_level_pairs is the SQL
source of truth save_chunk_data now dedups against, instead of FAISS membership.

SYS-25: keyed on (sitemap_id, chunk_level), not sitemap_id alone -- a sitemap
holding chunks at one level and missing the other used to be treated as fully
saved, permanently dropping the missing level from every future save_chunk_data
call.
"""
from unittest.mock import MagicMock

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
    SQLAlchemyChunkDataSource,
)


def _ds_with_mock_session(rows):
    """rows: list of (sitemap_id, chunk_level) tuples the query should return."""
    client = MagicMock()
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = list(rows)
    client.get_session.return_value.__enter__.return_value = session
    client.get_session.return_value.__exit__.return_value = False
    return SQLAlchemyChunkDataSource(client), session


class TestGetExistingSitemapLevelPairs:
    def test_returns_sitemap_level_pairs_present_in_chunks_table(self):
        ds, session = _ds_with_mock_session([(10, 1), (10, 2), (20, 1)])
        result = ds.get_existing_sitemap_level_pairs([10, 20, 30])
        assert result == {(10, 1), (10, 2), (20, 1)}

    def test_a_sitemap_with_only_one_level_saved_reports_only_that_level(self):
        """SYS-25: sitemap_id=10 has only its L2 chunk saved -- the pair set must
        say so, not collapse to "sitemap_id=10 is saved"."""
        ds, session = _ds_with_mock_session([(10, 2)])
        result = ds.get_existing_sitemap_level_pairs([10])
        assert result == {(10, 2)}
        assert (10, 1) not in result

    def test_empty_input_returns_empty_without_a_query(self):
        ds, session = _ds_with_mock_session([])
        result = ds.get_existing_sitemap_level_pairs([])
        assert result == set()
        session.execute.assert_not_called()

    def test_query_is_scoped_to_the_given_ids(self):
        ds, session = _ds_with_mock_session([])
        ds.get_existing_sitemap_level_pairs([1, 2, 3])
        params = session.execute.call_args[0][1]
        assert set(params["ids"]) == {1, 2, 3}


class TestNullEmbeddingRowsAreVisible:
    """DBT-23 (#74): the dedup must not count a level as saved while any of its
    rows lacks an embedding_id, and save_chunks must upsert on the DBT-09 key so
    such a row is repaired in place. Statement shape pinned here; behaviour on
    the real table in tests/integration/test_chunks_null_embedding_live.py."""

    def test_existing_pairs_query_requires_every_row_to_carry_an_embedding(self):
        from unittest.mock import MagicMock
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
            SQLAlchemyChunkDataSource,
        )
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [(5, 1)]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session
        pairs = SQLAlchemyChunkDataSource(client).get_existing_sitemap_level_pairs([5])
        sql = " ".join(str(session.execute.call_args[0][0]).split())
        assert "GROUP BY sitemap_id, chunk_level" in sql
        assert "HAVING COUNT(*) FILTER (WHERE embedding_id IS NULL) = 0" in sql
        assert pairs == {(5, 1)}

    def test_save_chunks_is_an_upsert_on_the_unique_key(self):
        from unittest.mock import MagicMock
        from newscrawler.infrastructure.datasource.dataflow.model.chunk_model import ChunkModel
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
            SQLAlchemyChunkDataSource,
        )
        session = MagicMock()
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session
        SQLAlchemyChunkDataSource(client).save_chunks([
            ChunkModel(sitemap_id=1, chunk_level=2, chunk_index=0, chunk_total=1, is_first_chunk=True,
                       is_last_chunk=True, text_content="t", token_count=1, embedding_id="e", chunk_status="embedded"),
        ])
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT (sitemap_id, chunk_level, chunk_index) DO UPDATE SET" in sql
        assert "embedding_id = excluded.embedding_id" in sql and "chunk_status = excluded.chunk_status" in sql
        session.commit.assert_called_once()
