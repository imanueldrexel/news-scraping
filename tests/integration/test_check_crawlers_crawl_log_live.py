"""
OPS-12 (#75) and OPS-13 (#76) against a live PostgreSQL: the crawl_log side of
scripts/check_crawlers.py that unit tests can only mock.

- log_to_db must land the outlet's own started_at/finished_at (distinct, real
  duration) rather than the logging transaction's NOW() twice, and the aware-UTC
  bind values must be stored in the same frame as the pipeline's NOW() writes so
  the 36 h gap check (NOW() - MAX(finished_at)) stays correct.
- load_previous_statuses must return the most recent row *per outlet* -- a manual
  `--website KOMPAS --log-db` after the morning batch moves only KOMPAS's baseline
  -- and hand back finished_at as an aware instant.

Runs against newsaggregator_test only (tests/integration/conftest.py forces it).
"""
import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "check_crawlers.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("check_crawlers_live", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["check_crawlers.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            assert s.execute(text("SELECT current_database()")).scalar() == "newsaggregator_test"
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    with c.get_session() as s:
        s.execute(text("DELETE FROM crawl_log WHERE website LIKE 'OPS1213_%'"))
        s.commit()


def _result(mod, website, status, started, finished, note=""):
    return {"website": website, "status": status, "note": note, "sitemap_links": 3,
            "started_at": started, "finished_at": finished,
            "duration_sec": (finished - started).total_seconds()}


class TestLogToDbTimestampsLive:
    def test_rows_carry_the_outlet_window_not_the_transaction_clock(self, client):
        mod = _load()
        started = datetime.now(timezone.utc) - timedelta(seconds=90)
        finished = started + timedelta(seconds=61.5)

        with client.get_session() as s:
            mod.log_to_db([_result(mod, "OPS1213_A", mod.STATUS_ERROR, started, finished, "timeout after 60s")], s)

        with client.get_session() as s:
            row = s.execute(text(
                "SELECT started_at, finished_at, "
                "       EXTRACT(EPOCH FROM (finished_at - started_at)) AS duration_sec, "
                "       EXTRACT(EPOCH FROM (NOW() - finished_at)) AS age_sec, status, error_msg "
                "FROM crawl_log WHERE website = 'OPS1213_A' AND task = 'health_check'"
            )).fetchone()

        assert row is not None
        assert row.started_at != row.finished_at, "OPS-12: started_at must not fall back to DEFAULT NOW()"
        assert abs(float(row.duration_sec) - 61.5) < 0.01
        # Stored in the same frame as NOW(): the row finished ~28.5 s ago by the DB's own clock,
        # not 7 h off (which a naive local datetime would have produced on this UTC server).
        assert 20 < float(row.age_sec) < 120, f"finished_at is {row.age_sec}s old by NOW(); TZ frame mismatch?"
        assert row.status == "failed" and row.error_msg == "ERROR: timeout after 60s"


class TestLoadPreviousStatusesLive:
    def test_returns_the_latest_row_per_outlet_not_the_latest_batch(self, client):
        mod = _load()
        t0 = datetime.now(timezone.utc) - timedelta(hours=24)   # morning batch
        t1 = t0 + timedelta(hours=8)                             # a manual --website run on one outlet
        with client.get_session() as s:
            mod.log_to_db([
                _result(mod, "OPS1213_KOMPAS", mod.STATUS_BROKEN, t0, t0 + timedelta(seconds=5), "sitemap fetch failed"),
                _result(mod, "OPS1213_DETIK", mod.STATUS_OK, t0, t0 + timedelta(seconds=7)),
                _result(mod, "OPS1213_CNBC", mod.STATUS_FALLBACK, t0, t0 + timedelta(seconds=9), "rescued by trafilatura"),
            ], s)
        with client.get_session() as s:
            mod.log_to_db([
                _result(mod, "OPS1213_KOMPAS", mod.STATUS_OK, t1, t1 + timedelta(seconds=4)),
            ], s)

        with client.get_session() as s:
            previous = mod.load_previous_statuses(s)

        ours = {k: v for k, v in previous.items() if k.startswith("OPS1213_")}
        assert ours["OPS1213_KOMPAS"]["status"] == "OK", "the later manual row must win for KOMPAS"
        assert ours["OPS1213_DETIK"]["status"] == "OK", "DETIK's morning row must still be its baseline"
        assert ours["OPS1213_CNBC"]["status"] == "FALLBACK"
        for v in ours.values():
            assert v["finished_at"].tzinfo is not None, "finished_at must come back as an aware instant"
        # The instant round-trips through the timestamp column and AT TIME ZONE unchanged.
        assert abs((ours["OPS1213_KOMPAS"]["finished_at"] - (t1 + timedelta(seconds=4))).total_seconds()) < 0.001
        assert abs((ours["OPS1213_DETIK"]["finished_at"] - (t0 + timedelta(seconds=7))).total_seconds()) < 0.001

    def test_delta_end_to_end_against_real_rows(self, client):
        mod = _load()
        t0 = datetime.now(timezone.utc) - timedelta(hours=24)
        with client.get_session() as s:
            mod.log_to_db([
                _result(mod, "OPS1213_KOMPAS", mod.STATUS_OK, t0, t0 + timedelta(seconds=5)),
                _result(mod, "OPS1213_TEMPO", mod.STATUS_ERROR, t0, t0 + timedelta(seconds=60), "timeout after 60s"),
                _result(mod, "OPS1213_BISNIS", mod.STATUS_BROKEN, t0, t0 + timedelta(seconds=2), "sitemap fetch failed"),
            ], s)
        with client.get_session() as s:
            previous = mod.load_previous_statuses(s)

        now = datetime.now(timezone.utc)
        today = [
            _result(mod, "OPS1213_KOMPAS", mod.STATUS_BROKEN, now, now + timedelta(seconds=1), "no branches"),
            _result(mod, "OPS1213_TEMPO", mod.STATUS_OK, now, now + timedelta(seconds=3)),
            _result(mod, "OPS1213_BISNIS", mod.STATUS_BROKEN, now, now + timedelta(seconds=2), "sitemap fetch failed"),
        ]
        delta = mod.compute_delta(today, previous)
        assert [e["website"] for e in delta["new"]] == ["OPS1213_KOMPAS"]
        assert [e["website"] for e in delta["recovered"]] == ["OPS1213_TEMPO"]
        assert [e["website"] for e in delta["unchanged"]] == ["OPS1213_BISNIS"]
        first = mod.summary_line(today, delta).split("\n")[0]
        assert "NEW: OPS1213_KOMPAS (BROKEN, was OK)" in first
        assert "RECOVERED: OPS1213_TEMPO (OK, was ERROR)" in first
