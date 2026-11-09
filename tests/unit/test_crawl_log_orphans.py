"""OPS-39 (#232): a crawl_log row 'started' past its job's time limit belongs to no run;
the 05:30 health check reports it, scripts/close_abandoned_crawl_log.py closes it."""
import importlib.util
import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from newscrawler.tools import crawl_log_orphans as orphans

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "run_scheduled_health_check.py")


@pytest.mark.parametrize("task,age_hours,orphan", [
    ("full_text", 5.0, True),             # the ticket's case: a crawl row started 5 h ago
    ("full_text", 10 / 60, False),        # ... and one started 10 minutes ago
    ("sitemap", 4.01, True), ("sitemap", 3.99, False),
    ("newsletter", 4.5, True), ("health_check", 4.5, True),
    ("extract_knowledge", 5.0, False),    # the extraction may run for 8 h (PT8H)
    ("extract_knowledge", 8.5, True),
])
def test_is_orphan(task, age_hours, orphan):
    assert orphans.is_orphan(task, age_hours) is orphan


def _row(log_id, task, age, website="KOMPAS"):
    return SimpleNamespace(log_id=log_id, website=website, task=task, started_at=datetime(2026, 10, 6, 7, 0),
                           age=age)


def test_find_orphans_keeps_only_rows_past_their_limit():
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        _row(1, "full_text", 5.0), _row(2, "full_text", 0.2), _row(3, "extract_knowledge", 5.0),
        _row(4, "extract_knowledge", 9.0)]
    assert [r.log_id for r in orphans.find_orphans(session)] == [1, 4]
    sql = str(session.execute.call_args.args[0])
    assert "status = 'started'" in sql and "NOW() - started_at" in sql


def test_close_orphans_touches_only_the_given_rows_still_started():
    session = MagicMock()
    session.execute.return_value.rowcount = 2
    rows = [orphans.OpenRow(2, "WARTAEKONOMI", "full_text", datetime(2026, 5, 29), 3000.0),
            orphans.OpenRow(4, "WARTAEKONOMI", "full_text", datetime(2026, 5, 30), 2990.0)]
    assert orphans.close_orphans(session, rows, "abandoned") == 2
    sql, params = str(session.execute.call_args.args[0]), session.execute.call_args.args[1]
    assert "status = 'failed'" in sql and "finished_at = started_at" in sql and "AND status = 'started'" in sql
    assert params == {"reason": "abandoned", "ids": [2, 4]}
    session.commit.assert_called_once()
    assert orphans.close_orphans(MagicMock(), [], "x") == 0


def test_describe():
    rows = [orphans.OpenRow(i, "WARTAEKONOMI", "full_text", datetime(2026, 5, 29, 23, 36), 3118.4) for i in range(7)]
    text = orphans.describe(rows)
    assert text.startswith("#0 WARTAEKONOMI full_text since 2026-05-29 23:36 (3,118 h); #1 ")
    assert text.endswith("; +2 more")


class TestHealthCheck:
    def _load(self, monkeypatch):
        monkeypatch.setenv("FILTER_AUDIT_WEEKDAY", "-1")
        spec = importlib.util.spec_from_file_location("run_scheduled_health_check", _SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_an_orphan_is_reported_with_how_to_close_it(self, monkeypatch):
        mod = self._load(monkeypatch)
        row = orphans.OpenRow(458, "IDNTIMES", "full_text", datetime(2026, 9, 20, 6, 22), 400.0)
        monkeypatch.setattr(orphans, "find_orphans", lambda session: [row])
        with patch("newscrawler.infrastructure.network.clients.sqlalchemy_client.SQLAlchemyClient"):
            message = mod._orphaned_crawl_log_message()
        assert message.startswith("1 row(s) still 'started' past their job's time limit")
        assert "#458 IDNTIMES full_text since 2026-09-20 06:22" in message
        assert "scripts/close_abandoned_crawl_log.py" in message

    def test_no_orphan_no_message(self, monkeypatch):
        mod = self._load(monkeypatch)
        monkeypatch.setattr(orphans, "find_orphans", lambda session: [])
        with patch("newscrawler.infrastructure.network.clients.sqlalchemy_client.SQLAlchemyClient"):
            assert mod._orphaned_crawl_log_message() is None

    def test_a_database_error_never_breaks_the_health_check(self, monkeypatch):
        mod = self._load(monkeypatch)       # the unit conftest refuses every connection (DBT-53)
        assert mod._orphaned_crawl_log_message() is None

    def test_main_sends_the_line(self, monkeypatch):
        mod = self._load(monkeypatch)
        monkeypatch.setattr(mod, "_hours_since_last_health_check", lambda: None)
        monkeypatch.setattr(mod, "_stale_backup_message", lambda: None)
        monkeypatch.setattr(mod, "_orphaned_crawl_log_message", lambda: "1 row(s) still 'started' ...")
        with patch.object(mod.subprocess, "run") as run, patch("notify_telegram.send") as send:
            run.return_value = MagicMock(returncode=0, stdout="ALL OK", stderr="")
            assert mod.main() == 0
        assert [c.args[0] for c in send.call_args_list] == ["📋 NewsAggregator crawl_log: 1 row(s) still 'started' ..."]
