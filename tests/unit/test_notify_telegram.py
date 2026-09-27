"""
OPS-01: notify_telegram.send() must never raise -- a missing config or a network
failure while sending an alert must not crash the health check it's attached to.
"""
import importlib.util
import os
from unittest.mock import MagicMock, patch

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "notify_telegram.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("notify_telegram", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
