"""
OPS-01: run_scheduled_health_check.py must send a Telegram notification when
check_crawlers.py exits non-zero (an unhealthy source), stay silent on success, and
always propagate check_crawlers.py's own exit code so Task Scheduler's history
reflects the real result independent of whether the notification succeeded.

Reopened 2026-09-17: it must also flag a missed run -- a gap of more than 36h since
the last logged health_check row -- because -StartWhenAvailable/-WakeToRun only
catch a missed 05:30 window if the job runs *at all* on the next boot; a deleted
task, expired credentials, or the machine being off longer than any catch-up window
would otherwise stay completely silent (no alert, no exit code, no crawl_log row).

_hours_since_last_health_check() itself does a live DB query and is always mocked
out below -- unit tests must not touch a database (see
tests/integration/test_run_scheduled_health_check_live.py for the live round-trip).

OPS-13 (#76): the wrapper now reads check_crawlers.py's --json payload and decides
from its `delta` block -- a recovery on a green day still notifies, and a red day
whose statuses all match the previous run can be muted with
HEALTH_ALERT_ON_NO_CHANGE=false. The decision is a pure function, tested directly.
"""
import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts",
)
_SCRIPT = os.path.join(_SCRIPTS, "run_scheduled_health_check.py")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


@pytest.fixture(autouse=True)
def _fresh_backup():
    """OPS-23: every test runs with a fresh dump, so the backup-age alert never
    leaks into the notification counts the tests below assert. The alert's own
    tests override it."""
    with patch("backup_db.newest_dump_age_hours", return_value=1.0):
        yield


def _load():
    spec = importlib.util.spec_from_file_location("run_scheduled_health_check", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMain:
    def test_healthy_run_sends_no_notification_and_returns_zero(self):
        mod = _load()
        with patch.object(mod, "_hours_since_last_health_check", return_value=None), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=0, stdout="ALL OK", stderr="")
            result = mod.main()
        assert result == 0
        mock_send.assert_not_called()

    def test_unhealthy_run_sends_a_notification_and_returns_the_same_code(self):
        mod = _load()
        with patch.object(mod, "_hours_since_last_health_check", return_value=None), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=1, stdout="VIVA BROKEN", stderr="")
            result = mod.main()
        assert result == 1
        mock_send.assert_called_once()
        assert "VIVA BROKEN" in mock_send.call_args[0][0]

    def test_empty_output_still_sends_a_notification_on_failure(self):
        mod = _load()
        with patch.object(mod, "_hours_since_last_health_check", return_value=None), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = mod.main()
        assert result == 1
        mock_send.assert_called_once()

    def test_check_crawlers_is_invoked_with_json_and_log_db(self):
        """OPS-13: --json (not --quiet) so the delta block is readable here; --log-db
        both writes the rows and implies the --diff-db baseline read."""
        mod = _load()
        with patch.object(mod, "_hours_since_last_health_check", return_value=None), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mod.main()
        args = mock_run.call_args[0][0]
        assert "--json" in args
        assert "--log-db" in args
        # The summary carries emoji; Windows' cp1252 default would mangle or raise.
        assert mock_run.call_args[1].get("encoding") == "utf-8"

    def test_json_payload_message_is_the_summary_not_the_whole_blob(self):
        mod = _load()
        payload = json.dumps({"summary": "Crawler health 2026-09-18: \U0001F534 NEW: KOMPAS (BROKEN, was OK)\nTotals: OK=31, FALLBACK=0, PARTIAL=0, BROKEN=1, ERROR=0 (of 32)",
                              "delta": {"new": [{"website": "KOMPAS"}], "changed": [], "recovered": [],
                                        "baseline": [], "unchanged": [], "no_change": False},
                              "results": [{"website": "KOMPAS", "status": "BROKEN"}]})
        with patch.object(mod, "_hours_since_last_health_check", return_value=None), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=1, stdout=payload, stderr="")
            result = mod.main()
        assert result == 1
        message = mock_send.call_args[0][0]
        assert "NEW: KOMPAS (BROKEN, was OK)" in message
        assert '"results"' not in message


def _report(new=(), changed=(), recovered=(), baseline=(), unchanged=(), no_change=False):
    def entries(names):
        return [{"website": n, "status": "BROKEN", "previous": "OK"} for n in names]
    return {"summary": "s", "delta": {
        "new": entries(new), "changed": entries(changed), "recovered": entries(recovered),
        "baseline": entries(baseline), "unchanged": entries(unchanged), "no_change": no_change}}


class TestDecideNotification:
    """OPS-13: exit-code semantics are unchanged (exit 1 still notifies); the delta
    adds recoveries on green days and lets the operator mute no-change red days."""

    def test_unhealthy_with_movement_sends_the_problem_headline(self):
        mod = _load()
        d = mod.decide_notification(1, _report(new=["KOMPAS"], unchanged=["A"]), alert_on_no_change=True)
        assert d["send"] and "found a problem" in d["headline"]

    def test_unhealthy_no_change_sends_by_default(self):
        mod = _load()
        d = mod.decide_notification(1, _report(unchanged=["A", "B"], no_change=True), alert_on_no_change=True)
        assert d["send"]

    def test_unhealthy_no_change_is_muted_when_operator_opts_out(self):
        mod = _load()
        d = mod.decide_notification(1, _report(unchanged=["A", "B"], no_change=True), alert_on_no_change=False)
        assert not d["send"]
        assert "HEALTH_ALERT_ON_NO_CHANGE" in d["reason"]

    def test_opt_out_does_not_mute_a_day_with_movement(self):
        """The knob mutes *unchanged* red days only -- a NEW breakage always goes out."""
        mod = _load()
        d = mod.decide_notification(1, _report(new=["KOMPAS"], unchanged=["A"]), alert_on_no_change=False)
        assert d["send"]

    def test_healthy_with_a_recovery_sends_the_green_headline(self):
        """A recovery must be visible without opening crawl_log, even on exit 0."""
        mod = _load()
        d = mod.decide_notification(0, _report(recovered=["TEMPO"], unchanged=["A"]), alert_on_no_change=True)
        assert d["send"] and "healthy" in d["headline"]

    def test_healthy_unchanged_stays_silent(self):
        mod = _load()
        d = mod.decide_notification(0, _report(unchanged=["A", "B"], no_change=True), alert_on_no_change=True)
        assert not d["send"]

    def test_unparseable_output_falls_back_to_exit_code_only(self):
        """A crash trace instead of JSON: exit 1 still notifies (with the raw text),
        exit 0 stays silent -- the pre-OPS-13 behaviour."""
        mod = _load()
        assert mod._parse_report("Traceback (most recent call last): boom") is None
        assert mod.decide_notification(1, None, True)["send"]
        assert not mod.decide_notification(0, None, True)["send"]

    def test_env_knob_parses_false_variants(self, monkeypatch):
        for raw in ("false", "False", "0", "no", " FALSE "):
            monkeypatch.setenv("HEALTH_ALERT_ON_NO_CHANGE", raw)
            assert _load().HEALTH_ALERT_ON_NO_CHANGE is False, raw
        for raw in ("true", "1", "yes", ""):
            monkeypatch.setenv("HEALTH_ALERT_ON_NO_CHANGE", raw)
            assert _load().HEALTH_ALERT_ON_NO_CHANGE is True, raw
        monkeypatch.delenv("HEALTH_ALERT_ON_NO_CHANGE")
        assert _load().HEALTH_ALERT_ON_NO_CHANGE is True


class TestMissedRunGapDetection:
    def test_gap_past_threshold_sends_a_distinct_notification(self):
        mod = _load()
        with patch.object(mod, "_hours_since_last_health_check", return_value=48.5), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=0, stdout="ALL OK", stderr="")
            result = mod.main()

        assert result == 0  # the health check itself still ran and was healthy
        mock_send.assert_called_once()
        message = mock_send.call_args[0][0]
        assert "48.5" in message
        assert "schtasks" in message

    def test_gap_within_threshold_sends_no_notification(self):
        mod = _load()
        with patch.object(mod, "_hours_since_last_health_check", return_value=20.0), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=0, stdout="ALL OK", stderr="")
            mod.main()
        mock_send.assert_not_called()

    def test_unknown_gap_does_not_crash_or_notify(self):
        """DB unreachable, or no health_check row has ever been logged -- must not
        block the health check itself from running."""
        mod = _load()
        with patch.object(mod, "_hours_since_last_health_check", return_value=None), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=0, stdout="ALL OK", stderr="")
            result = mod.main()
        assert result == 0
        mock_send.assert_not_called()
        mock_run.assert_called_once()

    def test_gap_check_runs_before_the_subprocess_writes_new_rows(self):
        """The gap must reflect the *previous* run, not this run's own -- so it has
        to be read before check_crawlers.py --log-db inserts fresh crawl_log rows."""
        mod = _load()
        call_order = []
        with patch.object(
            mod, "_hours_since_last_health_check",
            side_effect=lambda: call_order.append("gap_check") or None,
        ), patch.object(
            mod.subprocess, "run",
            side_effect=lambda *a, **k: call_order.append("subprocess") or MagicMock(
                returncode=0, stdout="", stderr=""
            ),
        ), patch("notify_telegram.send"):
            mod.main()
        assert call_order == ["gap_check", "subprocess"]


class TestStaleBackupAlert:
    """OPS-23 (#164): the backup job cannot report its own failure to fire."""

    def _run(self, age):
        mod = _load()
        with patch("backup_db.newest_dump_age_hours", return_value=age), \
             patch.object(mod, "_hours_since_last_health_check", return_value=None), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=0, stdout="ALL OK", stderr="")
            result = mod.main()
        return result, [c[0][0] for c in mock_send.call_args_list]

    def test_an_old_dump_alerts_and_the_check_still_runs(self):
        result, sent = self._run(72.0)
        assert result == 0
        assert len(sent) == 1 and "72.0h old" in sent[0] and "NewsAggregator DB Backup" in sent[0]

    def test_no_dump_at_all_alerts(self):
        _, sent = self._run(None)
        assert len(sent) == 1 and "backup_db.py" in sent[0]

    def test_a_fresh_dump_is_silent(self):
        _, sent = self._run(3.0)
        assert sent == []
