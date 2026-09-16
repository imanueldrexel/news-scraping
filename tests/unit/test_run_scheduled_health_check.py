"""
OPS-01: run_scheduled_health_check.py must send a Telegram notification when
check_crawlers.py exits non-zero (an unhealthy source), stay silent on success, and
always propagate check_crawlers.py's own exit code so Task Scheduler's history
reflects the real result independent of whether the notification succeeded.
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
        with patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=0, stdout="ALL OK", stderr="")
            result = mod.main()
        assert result == 0
        mock_send.assert_not_called()

    def test_unhealthy_run_sends_a_notification_and_returns_the_same_code(self):
        mod = _load()
        with patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=1, stdout="VIVA BROKEN", stderr="")
            result = mod.main()
        assert result == 1
        mock_send.assert_called_once()
        assert "VIVA BROKEN" in mock_send.call_args[0][0]

    def test_empty_output_still_sends_a_notification_on_failure(self):
        mod = _load()
        with patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send") as mock_send:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = mod.main()
        assert result == 1
        mock_send.assert_called_once()

    def test_check_crawlers_is_invoked_with_quiet_and_log_db(self):
        mod = _load()
        with patch.object(mod.subprocess, "run") as mock_run, \
             patch("notify_telegram.send"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mod.main()
        args = mock_run.call_args[0][0]
        assert "--quiet" in args
        assert "--log-db" in args
