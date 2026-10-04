"""DBT-53 (#226): the unit suite cannot reach a database or send a Telegram message."""
import pytest
from sqlalchemy import text


class TestNoRealDatabase:
    def test_a_raw_connection_is_refused(self):
        import psycopg2
        with pytest.raises(AssertionError, match="unit tests may not reach a database"):
            psycopg2.connect(host="localhost", port=5431, dbname="newsaggregator")

    def test_the_applications_own_client_cannot_open_a_session(self):
        from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
        client = SQLAlchemyClient()
        with pytest.raises(Exception) as raised:
            with client.get_session() as session:
                session.execute(text("SELECT 1"))
        assert "unit tests may not reach a database" in str(raised.value)

    def test_the_client_forced_to_the_local_production_defaults_is_refused_too(self):
        from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
        client = SQLAlchemyClient(sent_to_local=True)
        with pytest.raises(Exception, match="unit tests may not reach a database"):
            with client.get_session() as session:
                session.execute(text("SELECT 1"))

    def test_migrate_py_cannot_connect(self):
        import importlib.util
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "scripts", "migrate.py")
        spec = importlib.util.spec_from_file_location("migrate_guard_probe", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with pytest.raises(AssertionError, match="unit tests may not reach a database"):
            module._connect()

    def test_a_test_can_still_fake_the_connection_itself(self, monkeypatch):
        import psycopg2
        sentinel = object()
        monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: sentinel)
        assert psycopg2.connect() is sentinel


class TestNoRealTelegram:
    def test_the_token_and_chat_are_blank(self):
        import newscrawler.core.constants as constants
        assert constants.TELEGRAM_BOT_TOKEN == "" and constants.TELEGRAM_CHAT_ID == ""

    def test_the_outbox_is_this_tests_own(self, tmp_path):
        import os
        assert os.environ["TELEGRAM_OUTBOX"].startswith(str(tmp_path))
