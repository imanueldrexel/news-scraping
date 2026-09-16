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
