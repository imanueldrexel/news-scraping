"""
SYS-03: SQLAlchemyClient.get_session must roll back AND re-raise on error.
Swallowing the exception made a DB outage look like a successful crawl with 0 rows.
No database needed: the session factory is replaced with a mock.
"""
from unittest.mock import MagicMock

import pytest

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _client_with_mock_session():
    client = SQLAlchemyClient()  # create_engine is lazy; no connection is opened
    session = MagicMock(name="session")
    client.Session = MagicMock(return_value=session)
    return client, session


class TestGetSession:
    def test_GS01_error_inside_block_is_reraised(self):
        client, session = _client_with_mock_session()
        with pytest.raises(RuntimeError, match="boom"):
            with client.get_session():
                raise RuntimeError("boom")

    def test_GS02_error_rolls_back_then_closes(self):
        client, session = _client_with_mock_session()
        with pytest.raises(RuntimeError):
            with client.get_session():
                raise RuntimeError("boom")
        session.rollback.assert_called_once()
        session.close.assert_called_once()

    def test_GS03_success_closes_without_rollback(self):
        client, session = _client_with_mock_session()
        with client.get_session() as s:
            s.execute("SELECT 1")
        session.rollback.assert_not_called()
        session.close.assert_called_once()

    def test_GS04_code_after_failed_block_does_not_run(self):
        """The pre-SYS-03 behaviour: the with-block exited normally and the caller
        continued to `return []`, reporting success. That path must be gone."""
        client, _ = _client_with_mock_session()
        reached_after = False
        with pytest.raises(RuntimeError):
            with client.get_session():
                raise RuntimeError("db down")
            reached_after = True  # noqa: F841 - would only run if swallowed
        assert reached_after is False

    def test_GS05_error_is_logged_once_with_type(self, caplog):
        import logging
        client, _ = _client_with_mock_session()
        with caplog.at_level(logging.ERROR, logger="newscrawler.infrastructure.network.clients.sqlalchemy_client"):
            with pytest.raises(ValueError):
                with client.get_session():
                    raise ValueError("bad value")
        msgs = [r.message for r in caplog.records if "Database error" in r.message]
        assert len(msgs) == 1 and "ValueError" in msgs[0]
