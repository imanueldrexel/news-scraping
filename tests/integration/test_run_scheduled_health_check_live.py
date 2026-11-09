"""
OPS-01 (reopened 2026-09-17) against a live PostgreSQL: verifies
_hours_since_last_health_check()'s query -- EXTRACT(EPOCH FROM (NOW() -
MAX(finished_at))) / 3600 -- actually computes the right gap against the real
crawl_log.finished_at TIMESTAMP column, and returns None when there is nothing to
compare against yet. This is the absence-detection signal: a gap this large since
the last logged run means the scheduled job stopped firing, independent of whether
this run itself fires on schedule.
"""
import importlib.util
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "run_scheduled_health_check.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("run_scheduled_health_check_live", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


class TestHoursSinceLastHealthCheckLive:
    def test_computes_the_real_gap_from_a_known_past_row(self, client):
        with client.get_session() as s:
            s.execute(text(
                "INSERT INTO crawl_log (website, task, status, finished_at) "
                "VALUES ('OPS09_TEST', 'health_check', 'completed', NOW() - INTERVAL '50 hours')"
            ))
            s.commit()

        try:
            mod = _load()
            gap = mod._hours_since_last_health_check()

            assert gap is not None
            assert 49.9 < gap < 50.1, f"expected ~50h gap, got {gap}"
        finally:
            with client.get_session() as s:
                s.execute(text("DELETE FROM crawl_log WHERE website = 'OPS09_TEST'"))
                s.commit()

    def test_returns_none_when_no_health_check_row_exists(self, client):
        with client.get_session() as s:
            s.execute(text("DELETE FROM crawl_log WHERE task = 'health_check'"))
            s.commit()

        mod = _load()
        gap = mod._hours_since_last_health_check()

        assert gap is None
