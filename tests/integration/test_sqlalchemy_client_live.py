"""
SYS-03 against a live PostgreSQL: a real database error must escape get_session(),
and a data-source call built on it must fail loudly instead of returning "nothing".

Requires the newsaggregator_test DB (tests/integration/conftest.py forces it).
"""
import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError, ProgrammingError  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    return c


class TestGetSessionLive:
    def test_LGS01_bad_sql_raises_out_of_with_block(self, client):
        with pytest.raises(ProgrammingError):
            with client.get_session() as s:
                s.execute(text("SELECT * FROM table_that_does_not_exist"))

    def test_LGS02_session_is_usable_again_after_a_failure(self, client):
        with pytest.raises(ProgrammingError):
            with client.get_session() as s:
                s.execute(text("SELECT nope FROM sitemaps"))
        with client.get_session() as s:
            assert s.execute(text("SELECT 1")).scalar() == 1

    def test_LGS03_unreachable_server_raises_not_empty_result(self, monkeypatch):
        """The exact SYS-03 scenario: DB down -> data source must raise, not return []."""
        from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
            SQLAlchemyChunkDataSource,
        )
        from newscrawler.infrastructure.datasource.dataflow.model.chunk_model import ChunkModel

        monkeypatch.setenv("POSTGRES_DB_PORT", "1")  # nothing listens here
        dead = SQLAlchemyClient()
        ds = SQLAlchemyChunkDataSource(dead)
        chunk = ChunkModel(sitemap_id=1, chunk_level=1, chunk_index=0, chunk_total=1,
                           is_first_chunk=True, is_last_chunk=True, text_content="x",
                           token_count=1, embedding_id="e", chunk_status="embedded")
        with pytest.raises(DBAPIError):
            ds.save_chunks([chunk])
