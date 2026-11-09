"""SYS-39 / OPS-20: scripts/run_scheduled_extraction.py runs the nightly extraction, reports it, and
exits 2 under the run lock. Offline: a fake service, no database, no Telegram."""
import importlib.util
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from newscrawler.core.knowledge_extractor import ExtractionResult

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "scripts", "run_scheduled_extraction.py")


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("run_scheduled_extraction", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _result(processed=4800, attempted=4830, in_tokens=3_800_000, out_tokens=1_480_000, cost=1.5, stopped=None,
            transient=0, first_error=None):
    return ExtractionResult(processed, attempted, transient, first_error, in_tokens, out_tokens, cost, stopped)


class TestSummaryLine:
    def test_numbers_first_and_the_pending_movement(self, script):
        line = script.summary_line(_result(), 84000, 79200)
        assert line == "4800/4830 extracted · 3800000 in / 1480000 out tokens, $1.50 · pending 84000 -> 79200"

    def test_an_expected_stop_is_lowercase_and_not_a_failure(self, script):
        for reason in ("peak hours (UTC weekdays 01-04, 06-10; next off-peak 2026-10-05 04:00 UTC)",
                       "daily cost limit reached ($8.01 of $8.00; KNOWLEDGE_DAILY_COST_LIMIT_USD)"):
            result = _result(stopped=reason)
            assert "stopped: " + reason in script.summary_line(result, 10, 5)
            assert "STOPPED" not in script.summary_line(result, 10, 5) and not script.is_failure(result)

    @pytest.mark.parametrize("reason", ["5 failed calls in a row (HTTP 502)", "provider quota exhausted (PerDay)"])
    def test_a_provider_stop_is_loud_and_a_failure(self, script, reason):
        result = _result(stopped=reason)
        assert "STOPPED: " + reason in script.summary_line(result, 10, 5)
        assert script.is_failure(result)

    def test_every_call_failing_leads_with_failed(self, script):
        result = _result(processed=0, attempted=5, in_tokens=0, out_tokens=0, cost=0.0, transient=5,
                         first_error="ProviderTransientError: 401", stopped="5 failed calls in a row (401)")
        line = script.summary_line(result, 10, 10)
        assert line.startswith("FAILED") and script.is_failure(result)

    def test_a_run_that_made_no_call_has_no_token_part(self, script):
        line = script.summary_line(_result(0, 0, 0, 0, 0.0, stopped="peak hours (x)"), 100, 100)
        assert "tokens" not in line and line.startswith("0/0 extracted")

class TestLockWait:
    def test_a_free_lock_does_not_wait(self, script):
        slept = []
        assert script.wait_for_lock(lambda: False, 90, sleep=slept.append) is True and slept == []

    def test_it_polls_until_the_crawl_ends(self, script):
        states = iter([True, True, False])
        slept = []
        assert script.wait_for_lock(lambda: next(states), 90, sleep=slept.append, poll_s=60) is True
        assert slept == [60, 60]

    def test_it_gives_up_after_the_wait(self, script):
        slept = []
        assert script.wait_for_lock(lambda: True, 3, sleep=slept.append, poll_s=60) is False
        assert sum(slept) == 180

    def test_zero_minutes_means_refuse_at_once(self, script):
        slept = []
        assert script.wait_for_lock(lambda: True, 0, sleep=slept.append) is False and slept == []


def _wire(script, monkeypatch, result, before=100, after=40, fail=None):
    sent = []
    service = MagicMock()
    if fail:
        service.extract_knowledge.side_effect = fail
    else:
        service.extract_knowledge.return_value = result
    monkeypatch.setattr("newscrawler.application.api.lambda_function.lambda_handler.init_crawler",
                        lambda: SimpleNamespace(crawler_service=service))
    monkeypatch.setattr("newscrawler.infrastructure.network.clients.sqlalchemy_client.SQLAlchemyClient",
                        lambda: MagicMock(get_session=MagicMock(return_value=MagicMock(
                            __enter__=lambda s: MagicMock(), __exit__=lambda s, *a: False))))
    counts = iter([before, after])
    monkeypatch.setattr(script, "pending_count", lambda session: next(counts))
    monkeypatch.setattr("newscrawler.tools.run_lock.refused_by_run_lock", lambda log: False)
    monkeypatch.setattr(script, "open_run_log", lambda d: (None, None))
    monkeypatch.setattr(script, "_notify", lambda message: sent.append("Extraction " + message))
    return sent


class TestMain:
    def test_a_normal_run_reports_and_exits_0(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, _result())
        assert script.main([]) == 0
        assert len(sent) == 1 and "4800/4830 extracted" in sent[0] and "pending 100 -> 40" in sent[0]

    def test_a_bare_count_from_an_older_repository_still_reports(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, 7)
        assert script.main([]) == 0 and "7/0 extracted" in sent[0]

    def test_a_budget_stop_still_exits_0(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, _result(stopped="daily cost limit reached ($8.01 of $8.00)"))
        assert script.main([]) == 0 and "stopped: daily cost limit" in sent[0]

    def test_an_outage_stop_exits_1_and_says_so(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, _result(stopped="5 failed calls in a row (HTTP 502)"))
        assert script.main([]) == 1 and "STOPPED: 5 failed calls in a row" in sent[0]

    def test_an_exception_is_reported_and_exits_1(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, None, fail=RuntimeError("DB down"))
        assert script.main([]) == 1
        assert len(sent) == 1 and sent[0].startswith("Extraction FAILED: RuntimeError: DB down")

    def test_the_run_lock_refuses_before_anything_is_built(self, script, monkeypatch):
        monkeypatch.setattr("newscrawler.tools.run_lock.refused_by_run_lock", lambda log: True)
        monkeypatch.setattr(script, "_run", lambda *a: pytest.fail("ran under a held lock"))
        monkeypatch.setattr(script, "open_run_log", lambda d: pytest.fail("opened a log under a held lock"))
        assert script.main([]) == 2

    def test_waiting_for_a_crawl_that_ends_then_runs(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, _result())
        states = iter([True, False])
        monkeypatch.setattr("newscrawler.tools.run_lock.refused_by_run_lock", lambda log: next(states))
        monkeypatch.setattr(script.time, "sleep", lambda s: None)
        assert script.main(["--wait-for-crawl", "90"]) == 0 and len(sent) == 1

    def test_dry_run_calls_nothing(self, script, monkeypatch):
        monkeypatch.setattr(script, "_run", lambda *a: pytest.fail("ran"))
        monkeypatch.setattr("newscrawler.tools.run_lock.refused_by_run_lock", lambda log: pytest.fail("lock"))
        assert script.main(["--dry-run"]) == 0
