"""OPS-20 (#136) / SYS-68 (#216), ADR-001: the summarizer interface. Offline: the
SDK clients are fakes. What matters is the boundary the newsletter relies on --
a quota error is told apart from an ordinary failure, an empty answer is not a
summary, and a call is counted only after the API answered."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import newscrawler.core.summarizer as sm


class _StatusError(Exception):
    def __init__(self, status, message="boom", retry_after=None):
        super().__init__(message)
        self.status_code = status
        if retry_after is not None:
            self.response = SimpleNamespace(headers={"retry-after": retry_after})


def _answer(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _openai(answer=None, error=None, usage=None, sleeps=None):
    client = MagicMock()
    if error is not None:
        client.chat.completions.create.side_effect = error
    else:
        client.chat.completions.create.return_value = _answer(answer)
    sleep = sleeps.append if sleeps is not None else (lambda s: None)
    return sm.OpenAICompatSummarizer("deepseek-test", "k", usage=usage, client=client, sleep=sleep), client


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

    def test_a_per_day_429_is_quota_exhausted_and_not_counted(self):
        usage = MagicMock()
        s, client = _openai(error=_StatusError(429, "Daily request limit reached"), usage=usage)
        with pytest.raises(sm.QuotaExhausted):
            s.summarize("p")
        usage.increment_api_call_count.assert_not_called()
        assert client.chat.completions.create.call_count == 1   # a spent day is not retried

    def test_a_per_minute_429_waits_retries_once_and_then_succeeds(self):
        """SYS-71: the next call 2 s later would work, so it must run."""
        sleeps = []
        usage = MagicMock()
        s, client = _openai(usage=usage, sleeps=sleeps,
                            error=[_StatusError(429, "Rate limit exceeded: 60 requests per minute", retry_after="7"),
                                   _answer("- ok")])
        assert s.summarize("p") == "- ok"
        assert sleeps == [7.0]
        assert client.chat.completions.create.call_count == 2
        usage.increment_api_call_count.assert_called_once_with("deepseek-test")   # only the answered call

    def test_a_rate_limit_twice_is_a_plain_error_not_a_daily_quota(self):
        sleeps = []
        s, client = _openai(sleeps=sleeps, error=[_StatusError(429, "slow down"), _StatusError(429, "slow down")])
        with pytest.raises(sm.SummarizerError, match="rate limited twice") as info:
            s.summarize("p")
        assert not isinstance(info.value, sm.QuotaExhausted)
        assert client.chat.completions.create.call_count == 2    # one retry, never a loop
        assert len(sleeps) == 1

    def test_a_per_day_429_on_the_retry_still_stops_the_run(self):
        s, _ = _openai(error=[_StatusError(429, "slow down"), _StatusError(429, "daily quota spent")])
        with pytest.raises(sm.QuotaExhausted):
            s.summarize("p")

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


class TestRateLimitVersusDailyQuota:
    """SYS-71 (#219): only a quota that names a day stops the run."""

    @pytest.mark.parametrize("message", [
        "429 RESOURCE_EXHAUSTED. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier",
        "You exceeded your daily quota",
        "limit: 20 requests per day",
    ])
    def test_daily_quota_messages(self, message):
        assert sm.is_daily_quota(Exception(message))

    @pytest.mark.parametrize("message", [
        "Rate limit exceeded: 60 requests per minute",
        "429 RESOURCE_EXHAUSTED. quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
        "429 slow down",
    ])
    def test_rate_limit_messages_are_not_daily(self, message):
        assert not sm.is_daily_quota(Exception(message))

    def test_gemini_per_minute_429_retries_using_its_retry_delay(self):
        sleeps = []
        client = MagicMock()
        client.models.generate_content.side_effect = [
            Exception("429 RESOURCE_EXHAUSTED. quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier "
                      "retryDelay: '23s'"),
            SimpleNamespace(text="- ok"),
        ]
        s = sm.GeminiSummarizer("gemini-test", "k", client=client, sleep=sleeps.append)
        assert s.summarize("p") == "- ok"
        assert sleeps == [23.0]

    def test_retry_after_is_read_from_the_header_the_message_or_defaults(self):
        assert sm.retry_after_seconds(_StatusError(429, "x", retry_after="3")) == 3.0
        assert sm.retry_after_seconds(Exception("Please retry in 4.5s")) == 4.5
        assert sm.retry_after_seconds(Exception("429")) == sm.RATE_LIMIT_DEFAULT_WAIT_S
        assert sm.retry_after_seconds(_StatusError(429, "x", retry_after="garbage")) == sm.RATE_LIMIT_DEFAULT_WAIT_S

    def test_a_long_retry_after_is_capped(self):
        assert sm.retry_after_seconds(_StatusError(429, "x", retry_after="3600")) == sm.RATE_LIMIT_MAX_WAIT_S


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


class TestCompleteReturnsTokensWithoutCounting:
    """SYS-98 (#267, ADR-005): the RAG page keeps its own books under web:<model>, so
    complete() must hand back the tokens and must not count the call itself."""

    def test_openai_reply_carries_the_reported_tokens(self):
        usage = MagicMock()
        s, client = _openai(usage=usage)
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Jawaban"))],
            usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=90))
        assert s.complete("p") == sm.Reply("Jawaban", 1200, 90)
        usage.increment_api_call_count.assert_not_called()

    def test_openai_reply_without_usage_is_zero_tokens_and_an_empty_text_is_returned(self):
        s, _ = _openai(None)
        assert s.complete("p") == sm.Reply("", 0, 0)

    def test_gemini_reply_counts_thinking_as_output(self):
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="Jawaban", usage_metadata=SimpleNamespace(prompt_token_count=800, candidates_token_count=50,
                                                           thoughts_token_count=30))
        usage = MagicMock()
        s = sm.GeminiSummarizer("gemini-test", "k", usage=usage, client=client, sleep=lambda s: None)
        assert s.complete("p") == sm.Reply("Jawaban", 800, 80)
        usage.increment_api_call_count.assert_not_called()

    def test_priced_marks_who_costs_dollars(self):
        assert sm.OpenAICompatSummarizer.priced is True and sm.GeminiSummarizer.priced is False

    def test_summarize_still_counts_once(self):
        usage = MagicMock()
        s, _ = _openai("- a", usage=usage)
        s.summarize("p")
        usage.increment_api_call_count.assert_called_once_with("deepseek-test")

    def test_the_error_names_the_setting(self):
        with pytest.raises(ValueError, match="RAG_LLM_PROVIDER"):
            sm.build_summarizer(provider="claude", setting="RAG_LLM_PROVIDER")

    def test_a_forced_provider_without_its_key_is_none_not_the_other(self, monkeypatch):
        monkeypatch.setattr(sm, "OPENAI_API_KEY", None)
        monkeypatch.setattr(sm, "GEMINI_API_KEY", "g")
        assert sm.build_summarizer(provider="openai") is None

    def test_openai_options_reach_the_client(self, monkeypatch):
        monkeypatch.setattr(sm, "OPENAI_API_KEY", "k")
        seen = {}
        monkeypatch.setattr(sm, "OpenAICompatSummarizer", lambda *a, **k: seen.update(k) or "s")
        sm.build_summarizer(provider="openai", timeout_s=30, max_tokens=600)
        assert seen["timeout_s"] == 30 and seen["max_tokens"] == 600


class TestSdkRetries:
    """ADR-010: the search page's rewrite waits on its call, so it turns the SDK's own retries off
    (a 6 s timeout would otherwise be ~3 attempts with backoff). Everyone else keeps the default."""

    def _built(self, monkeypatch, **options):
        import openai
        seen = {}
        monkeypatch.setattr(openai, "OpenAI", lambda **kw: seen.update(kw) or MagicMock())
        sm.OpenAICompatSummarizer("m", "k", base_url="u", **options)
        return seen

    def test_max_retries_is_passed_when_set(self, monkeypatch):
        assert self._built(monkeypatch, max_retries=0, timeout_s=6)["max_retries"] == 0

    def test_the_default_is_the_sdks(self, monkeypatch):
        assert "max_retries" not in self._built(monkeypatch)
