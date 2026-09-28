"""
OPS-01: notify_telegram.send() must never raise -- a missing config or a network
failure while sending an alert must not crash the health check it's attached to.
"""
import importlib.util
import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "notify_telegram.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("notify_telegram", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _outbox(tmp_path, monkeypatch):
    """OPS-32: no test may queue into the real logs/telegram_outbox.jsonl, or
    wait out the real retry delays."""
    path = str(tmp_path / "outbox.jsonl")
    monkeypatch.setenv("TELEGRAM_OUTBOX", path)
    slept = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return {"path": path, "slept": slept}


class TestSend:
    def test_missing_token_returns_false_without_raising(self):
        mod = _load()
        mod.TELEGRAM_BOT_TOKEN = None
        mod.TELEGRAM_CHAT_ID = "123"
        assert mod.send("hello") is False

    def test_missing_chat_id_returns_false_without_raising(self):
        mod = _load()
        mod.TELEGRAM_BOT_TOKEN = "token"
        mod.TELEGRAM_CHAT_ID = None
        assert mod.send("hello") is False

    def test_successful_post_returns_true(self):
        mod = _load()
        mod.TELEGRAM_BOT_TOKEN = "token"
        mod.TELEGRAM_CHAT_ID = "123"
        with patch.object(mod, "requests") as mock_requests:
            mock_requests.post.return_value = MagicMock(status_code=200)
            assert mod.send("hello") is True
            url = mock_requests.post.call_args[0][0]
            assert "token" in url
            assert mock_requests.post.call_args[1]["json"]["chat_id"] == "123"
            assert mock_requests.post.call_args[1]["json"]["text"] == "hello"

    def test_non_200_response_returns_false(self):
        mod = _load()
        mod.TELEGRAM_BOT_TOKEN = "token"
        mod.TELEGRAM_CHAT_ID = "123"
        with patch.object(mod, "requests") as mock_requests:
            mock_requests.post.return_value = MagicMock(status_code=401, text="Unauthorized")
            assert mod.send("hello") is False

    def test_network_exception_returns_false_not_raises(self):
        mod = _load()
        mod.TELEGRAM_BOT_TOKEN = "token"
        mod.TELEGRAM_CHAT_ID = "123"
        with patch.object(mod, "requests") as mock_requests:
            mock_requests.post.side_effect = ConnectionError("no network")
            assert mod.send("hello") is False


class TestTheTokenNeverReachesTheLog:
    """OPS-33 (#194): requests puts the URL, /bot<token>/sendMessage, in its
    exception messages, and the 2026-09-27 07:00 run log carried the token."""

    TOKEN = "123:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789_-"

    def _mod(self):
        mod = _load()
        mod.TELEGRAM_BOT_TOKEN, mod.TELEGRAM_CHAT_ID = self.TOKEN, "42"
        return mod

    def test_a_connection_error_is_logged_without_the_token(self, caplog):
        mod = self._mod()
        err = ConnectionError("HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded "
                              "with url: /bot%s/sendMessage (Caused by NameResolutionError)" % self.TOKEN)
        with patch.object(mod, "requests") as mock_requests:
            mock_requests.post.side_effect = err
            assert mod.send("hello") is False
        logged = caplog.text
        assert "Failed to send Telegram notification: ConnectionError:" in logged
        assert "/botbot<redacted>/" not in logged and "/bot<redacted>/sendMessage" in logged
        assert "123:ABC" not in logged and "ABCdefGHI" not in logged

    def test_a_non_200_body_is_logged_without_the_token(self, caplog):
        mod = self._mod()
        with patch.object(mod, "requests") as mock_requests:
            mock_requests.post.return_value = MagicMock(status_code=404, text="not found: /bot%s/x" % self.TOKEN)
            assert mod.send("hello") is False
        assert "ABCdefGHI" not in caplog.text

    def test_redact_covers_a_token_of_any_shape_and_a_token_it_was_not_given(self):
        mod = self._mod()
        mod.TELEGRAM_BOT_TOKEN = "not-shaped-like-a-token"
        assert mod.redact("url /botnot-shaped-like-a-token/sendMessage") == "url /bot<redacted>/sendMessage"
        assert mod.redact("bare not-shaped-like-a-token here") == "bare <redacted> here"
        assert mod.redact("an old one /bot999:Zz_-9/getMe") == "an old one /bot<redacted>/getMe"
        assert mod.redact("nothing secret") == "nothing secret"


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class TestAFailedAlertIsDeliveredLater:
    """OPS-32 (#193): the 2026-09-27 07:00 summary, the one message that said 27
    sources had failed, hit the same outage and was only logged."""

    def _mod(self):
        mod = _load()
        mod.TELEGRAM_BOT_TOKEN, mod.TELEGRAM_CHAT_ID = "123:abc", "42"
        return mod

    def _queued(self, outbox):
        if not os.path.exists(outbox["path"]):
            return []
        with open(outbox["path"], encoding="utf-8") as f:
            return [json.loads(line)["text"] for line in f]

    def test_a_network_failure_is_retried_then_queued(self, _outbox):
        mod = self._mod()
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = ConnectionError("getaddrinfo failed")
            assert mod.send("27 sources FAILED") is False
        assert rq.post.call_count == 1 + len(mod.RETRY_DELAYS)
        assert _outbox["slept"] == list(mod.RETRY_DELAYS)
        assert self._queued(_outbox) == ["27 sources FAILED"]

    def test_a_retry_that_succeeds_queues_nothing(self, _outbox):
        mod = self._mod()
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = [ConnectionError("blip"), _Resp(200)]
            assert mod.send("hello") is True
        assert self._queued(_outbox) == []

    def test_the_next_send_delivers_the_queued_alert_first_marked_delayed(self, _outbox):
        mod = self._mod()
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = ConnectionError("down")
            mod.send("07:00 summary")
        with patch.object(mod, "requests") as rq:
            rq.post.return_value = _Resp(200)
            assert mod.send("19:00 summary") is True
        texts = [c[1]["json"]["text"] for c in rq.post.call_args_list]
        assert len(texts) == 2 and texts[0].startswith("[delayed; queued ") and texts[0].endswith("07:00 summary")
        assert texts[1] == "19:00 summary"
        assert not os.path.exists(_outbox["path"])

    def test_while_the_queue_cannot_drain_the_new_message_waits_behind_it(self, _outbox):
        mod = self._mod()
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = ConnectionError("down")
            mod.send("first")
            mod.send("second")
        assert self._queued(_outbox) == ["first", "second"]

    def test_a_new_message_is_not_posted_while_an_older_one_is_still_queued(self, _outbox):
        """DBT-48 (#199): queued alerts are delivered first, so the alerts
        arrive in order. When the flush fails, the new message must wait behind
        the old one even if it could have been sent: only the flush attempts
        are posted, and the new message is queued after the old one."""
        mod = self._mod()
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = ConnectionError("down")
            mod.send("07:00 summary")
        attempts = 1 + len(mod.RETRY_DELAYS)
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = [ConnectionError("still down")] * attempts + [_Resp(200)]
            assert mod.send("19:00 summary") is False
        texts = [c[1]["json"]["text"] for c in rq.post.call_args_list]
        assert len(texts) == attempts and all(t.endswith("07:00 summary") for t in texts), texts
        assert self._queued(_outbox) == ["07:00 summary", "19:00 summary"]

    def test_a_message_the_api_refuses_for_good_is_not_queued(self, _outbox):
        mod = self._mod()
        with patch.object(mod, "requests") as rq:
            rq.post.return_value = _Resp(400, "Bad Request: message is too long")
            assert mod.send("x" * 5000) is False
        assert rq.post.call_count == 1 and self._queued(_outbox) == []

    def test_a_queued_alert_the_api_now_refuses_is_dropped_not_stuck(self, _outbox):
        mod = self._mod()
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = ConnectionError("down")
            mod.send("old")
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = [_Resp(400, "Bad Request"), _Resp(200)]
            assert mod.send("new") is True
        assert self._queued(_outbox) == []

    def test_the_queue_keeps_the_newest(self, _outbox):
        mod = self._mod()
        mod.OUTBOX_MAX = 3
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = ConnectionError("down")
            for i in range(5):
                mod.send("m%d" % i)
        assert self._queued(_outbox) == ["m2", "m3", "m4"]

    def test_the_command_line_test_message_is_never_queued(self, _outbox):
        mod = self._mod()
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = ConnectionError("down")
            assert mod.send("test", queue_on_failure=False) is False
        assert self._queued(_outbox) == []

    def test_the_command_line_entry_point_leaves_the_outbox_as_it_was(self, _outbox, capsys):
        """DBT-48 (#199): the entry point itself, not send(): OPERATIONS.md's
        step-5 test run during an outage must fail now and queue nothing."""
        mod = self._mod()
        with patch.object(mod, "requests") as rq:
            rq.post.side_effect = ConnectionError("down")
            assert mod.main(["test"]) == 1
            assert self._queued(_outbox) == []
            mod.send("07:00 summary")
            assert mod.main(["test"]) == 1
        assert self._queued(_outbox) == ["07:00 summary"]
        assert "Failed to send" in capsys.readouterr().out
