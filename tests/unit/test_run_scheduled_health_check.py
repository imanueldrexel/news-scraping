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
"""
import importlib.util
import os
from unittest.mock import MagicMock, patch

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "run_scheduled_health_check.py",
)


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

    def test_check_crawlers_is_invoked_with_quiet_and_log_db(self):
        mod = _load()
        with patch.object(mod, "_hours_since_last_health_check", return_value=None), \
             patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mod.main()
        args = mock_run.call_args[0][0]
        assert "--quiet" in args
        assert "--log-db" in args


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
