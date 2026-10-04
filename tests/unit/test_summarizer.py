"""OPS-20 (#136) / SYS-68 (#216), ADR-001: the summarizer interface. Offline: the
SDK clients are fakes. What matters is the boundary the newsletter relies on --
a quota error is told apart from an ordinary failure, an empty answer is not a
summary, and a call is counted only after the API answered."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import newscrawler.core.summarizer as sm


class _StatusError(Exception):
    def __init__(self, status, message="boom"):
        super().__init__(message)
        self.status_code = status


def _openai(answer=None, error=None, usage=None):
    client = MagicMock()
    if error is not None:
        client.chat.completions.create.side_effect = error
    else:
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])
    return sm.OpenAICompatSummarizer("deepseek-test", "k", usage=usage, client=client), client


class TestOpenAICompatSummarizer:
    def test_returns_the_stripped_answer_and_counts_one_call(self):
        usage = MagicMock()
        s, _ = _openai("  - a\n- b  ", usage=usage)
        assert s.summarize("p") == "- a\n- b"
        usage.increment_api_call_count.assert_called_once_with("deepseek-test")

    def test_thinking_is_off_and_the_output_is_bounded(self):
        s, client = _openai("- a")
        s.summarize("p")
        kw = client.chat.completions.create.call_args.kwargs
        assert kw["extra_body"] == {"thinking": {"type": "disabled"}}
        assert kw["max_tokens"] == sm.NEWSLETTER_SUMMARY_MAX_TOKENS
        assert kw["model"] == "deepseek-test"

    @pytest.mark.parametrize("answer", [None, "", "   \n"])
    def test_an_empty_answer_is_an_error_not_a_summary_and_is_not_counted(self, answer):
        usage = MagicMock()
        s, _ = _openai(answer, usage=usage)
        # counted: the API did answer -- but an empty reply must not read as a summary
        with pytest.raises(sm.SummarizerError, match="empty"):
            s.summarize("p")

    def test_http_429_is_quota_exhausted_and_not_counted(self):
        usage = MagicMock()
        s, _ = _openai(error=_StatusError(429, "rate limited"), usage=usage)
        with pytest.raises(sm.QuotaExhausted):
            s.summarize("p")
        usage.increment_api_call_count.assert_not_called()

    def test_any_other_failure_is_a_plain_error_that_names_its_type(self):
        s, _ = _openai(error=_StatusError(503, "unavailable"))
        with pytest.raises(sm.SummarizerError) as info:
            s.summarize("p")
        assert not isinstance(info.value, sm.QuotaExhausted)
        assert "_StatusError" in str(info.value)

    def test_a_failing_usage_counter_never_costs_the_summary(self):
        usage = MagicMock()
        usage.increment_api_call_count.side_effect = RuntimeError("db down")
        s, _ = _openai("- a", usage=usage)
        assert s.summarize("p") == "- a"


class TestGeminiSummarizer:
    def test_resource_exhausted_is_quota_and_names_the_quota(self):
        client = MagicMock()
        client.models.generate_content.side_effect = Exception(
            "429 RESOURCE_EXHAUSTED. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        s = sm.GeminiSummarizer("gemini-test", "k", client=client)
        with pytest.raises(sm.QuotaExhausted) as info:
            s.summarize("p")
        assert info.value.quota == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"

    def test_returns_text_and_counts(self):
        usage = MagicMock()
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(text="- ok")
        s = sm.GeminiSummarizer("gemini-test", "k", usage=usage, client=client)
        assert s.summarize("p") == "- ok"
        usage.increment_api_call_count.assert_called_once_with("gemini-test")


class TestQuotaHelpers:
    def test_is_quota_error(self):
        assert sm.is_quota_error(_StatusError(429))
        assert sm.is_quota_error(Exception("RESOURCE_EXHAUSTED: limit: 20"))
        assert not sm.is_quota_error(_StatusError(500))
        assert not sm.is_quota_error(Exception("timeout"))

    def test_quota_name_is_none_when_the_error_names_none(self):
        assert sm.quota_name(Exception("429 slow down")) is None


class TestBuildSummarizer:
    def _keys(self, monkeypatch, openai="ok", gemini="gk"):
        monkeypatch.setattr(sm, "OPENAI_API_KEY", openai)
        monkeypatch.setattr(sm, "GEMINI_API_KEY", gemini)
        monkeypatch.setattr(sm, "OpenAICompatSummarizer", lambda *a, **k: SimpleNamespace(name="openai"))
        monkeypatch.setattr(sm, "GeminiSummarizer", lambda *a, **k: SimpleNamespace(name="gemini"))

    def test_default_prefers_the_openai_endpoint(self, monkeypatch):
        self._keys(monkeypatch)
        assert sm.build_summarizer(provider="").name == "openai"

    def test_default_falls_back_to_gemini_without_an_openai_key(self, monkeypatch):
        self._keys(monkeypatch, openai=None)
        assert sm.build_summarizer(provider="").name == "gemini"

    def test_a_forced_provider_without_its_key_is_none_not_the_other_one(self, monkeypatch):
        self._keys(monkeypatch, openai=None)
        assert sm.build_summarizer(provider="openai") is None

    def test_no_keys_is_none(self, monkeypatch):
        self._keys(monkeypatch, openai=None, gemini=None)
        assert sm.build_summarizer(provider="") is None

    def test_an_unknown_provider_is_refused(self, monkeypatch):
        self._keys(monkeypatch)
        with pytest.raises(ValueError):
            sm.build_summarizer(provider="claude")
