"""SYS-39 (#125, ADR-003): the providers behind knowledge extraction -- the request
each sends, the tokens each reports, and the OPS-09 boundary (an error before a
response is ProviderTransientError; an empty or unparseable reply is not an error
here). Fake SDK clients only; nothing is sent."""
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import newscrawler.core.extraction_provider as ep
from newscrawler.core.extraction_provider import (
    Completion,
    GeminiProvider,
    OpenAICompatProvider,
    ProviderQuotaExhausted,
    ProviderTransientError,
    build_provider,
)
from newscrawler.core.knowledge_extractor import parse_extraction

_FENCE = chr(96) * 3  # triple backtick


def _chat(content, prompt_tokens=700, completion_tokens=280):
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens))
    return client


class _Http429(Exception):
    status_code = 429


class TestOpenAICompatProvider:
    def test_the_reply_and_its_tokens_are_returned(self):
        provider = OpenAICompatProvider("deepseek-v4-flash", "k", client=_chat('{"persons": []}', 700, 280))
        assert provider.complete("prompt") == Completion('{"persons": []}', 700, 280)

    def test_the_request_asks_for_json_with_thinking_off_and_no_randomness(self):
        client = _chat("{}")
        OpenAICompatProvider("deepseek-v4-flash", "k", client=client).complete("the prompt")
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "deepseek-v4-flash"
        assert kwargs["messages"] == [{"role": "user", "content": "the prompt"}]
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}, "reasoning tokens are billed as output"
        assert kwargs["temperature"] == 0

    def test_the_model_is_the_usage_key_and_the_provider_is_priced(self):
        provider = OpenAICompatProvider("deepseek-v4-flash", "k", client=_chat("{}"))
        assert provider.name == "deepseek-v4-flash" and provider.priced is True

    def test_an_empty_reply_is_a_completion_without_text_not_an_error(self):
        provider = OpenAICompatProvider("m", "k", client=_chat(None, 500, 0))
        assert provider.complete("p") == Completion(None, 500, 0)

    def test_a_reply_with_no_usage_counts_zero_tokens(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))], usage=None)
        assert OpenAICompatProvider("m", "k", client=client).complete("p") == Completion("{}", 0, 0)

    def test_a_reply_with_no_choices_is_a_completion_without_text(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[], usage=None)
        assert OpenAICompatProvider("m", "k", client=client).complete("p").text is None

    def test_a_network_error_is_transient(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = ConnectionError("reset")
        with pytest.raises(ProviderTransientError, match="reset"):
            OpenAICompatProvider("m", "k", client=client).complete("p")

    def test_a_per_day_429_is_a_quota_error_naming_the_quota(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = _Http429(
            "429 quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        with pytest.raises(ProviderQuotaExhausted) as raised:
            OpenAICompatProvider("m", "k", client=client, sleep=lambda s: None).complete("p")
        assert raised.value.quota == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        assert isinstance(raised.value, ProviderTransientError), "still a no-response failure (OPS-09)"

    def test_a_rate_limit_waits_once_and_the_retry_can_succeed(self):
        client = _chat('{"ok": 1}')
        client.chat.completions.create.side_effect = [_Http429("slow down"), client.chat.completions.create.return_value]
        waits = []
        provider = OpenAICompatProvider("m", "k", client=client, sleep=waits.append)
        assert provider.complete("p").text == '{"ok": 1}'
        assert len(waits) == 1 and client.chat.completions.create.call_count == 2

    def test_a_rate_limit_twice_is_transient_not_quota(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = _Http429("slow down")
        with pytest.raises(ProviderTransientError) as raised:
            OpenAICompatProvider("m", "k", client=client, sleep=lambda s: None).complete("p")
        assert not isinstance(raised.value, ProviderQuotaExhausted)


class TestGeminiProvider:
    def _client(self, text, usage):
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(text=text, usage_metadata=usage)
        return client

    def test_the_request_is_unchanged_json_mime_type(self):
        client = self._client("{}", None)
        GeminiProvider("gemini-2.5-flash", "k", client=client).complete("p")
        kwargs = client.models.generate_content.call_args.kwargs
        assert kwargs["model"] == "gemini-2.5-flash" and kwargs["contents"] == "p"
        assert kwargs["config"] == {"response_mime_type": "application/json"}

    def test_thinking_tokens_count_as_output(self):
        """OPS-20: gemini-2.5-flash spends 1,932 thinking tokens per article; they are output."""
        usage = SimpleNamespace(prompt_token_count=760, candidates_token_count=300, thoughts_token_count=1932)
        completion = GeminiProvider("m", "k", client=self._client("{}", usage)).complete("p")
        assert (completion.input_tokens, completion.output_tokens) == (760, 2232)

    def test_a_missing_count_is_zero(self):
        usage = SimpleNamespace(prompt_token_count=760, candidates_token_count=None, thoughts_token_count=None)
        completion = GeminiProvider("m", "k", client=self._client("{}", usage)).complete("p")
        assert (completion.input_tokens, completion.output_tokens) == (760, 0)

    def test_no_usage_metadata_is_zero_tokens(self):
        assert GeminiProvider("m", "k", client=self._client("{}", None)).complete("p") == Completion("{}", 0, 0)

    def test_a_safety_block_is_a_completion_without_text(self):
        assert GeminiProvider("m", "k", client=self._client(None, None)).complete("p").text is None

    def test_an_api_error_is_transient(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("503")
        with pytest.raises(ProviderTransientError, match="503"):
            GeminiProvider("m", "k", client=client).complete("p")

    def test_a_per_day_quota_error_is_a_quota_stop(self):
        """OPS-20: the free tier's daily cap. The run stops instead of failing every remaining article."""
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError(
            "429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        with pytest.raises(ProviderQuotaExhausted) as raised:
            GeminiProvider("m", "k", client=client).complete("p")
        assert raised.value.quota == "GenerateRequestsPerDayPerProjectPerModel-FreeTier"

    def test_a_per_minute_429_is_only_transient(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED quotaId: PerMinute")
        with pytest.raises(ProviderTransientError) as raised:
            GeminiProvider("m", "k", client=client).complete("p")
        assert not isinstance(raised.value, ProviderQuotaExhausted)

    def test_it_is_not_priced(self):
        assert GeminiProvider("m", "k", client=MagicMock()).priced is False


class TestBuildProvider:
    @pytest.fixture(autouse=True)
    def keys(self, monkeypatch):
        monkeypatch.setattr(ep, "OPENAI_API_KEY", "ok")
        monkeypatch.setattr(ep, "GEMINI_API_KEY", "gk")
        monkeypatch.setattr(ep, "OpenAICompatProvider", lambda *a, **k: SimpleNamespace(name="openai-provider"))
        monkeypatch.setattr(ep, "GeminiProvider", lambda *a, **k: SimpleNamespace(name="gemini-provider"))

    def test_empty_means_gemini_even_when_the_other_key_is_set(self):
        """Moving to the priced provider is a decision, not a side effect of a key."""
        assert build_provider("").name == "gemini-provider"

    def test_openai_is_chosen_only_by_name(self):
        assert build_provider("openai").name == "openai-provider"

    def test_gemini_by_name(self):
        assert build_provider("gemini").name == "gemini-provider"

    def test_the_environment_value_is_used_when_no_argument_is_given(self, monkeypatch):
        monkeypatch.setattr(ep, "KNOWLEDGE_LLM_PROVIDER", "openai")
        assert build_provider().name == "openai-provider"

    def test_openai_without_its_key_is_none_and_says_so(self, monkeypatch, caplog):
        monkeypatch.setattr(ep, "OPENAI_API_KEY", None)
        with caplog.at_level(logging.WARNING, logger="newscrawler.core.extraction_provider"):
            assert build_provider("openai") is None
        assert "OPENAI_API_KEY" in caplog.text

    def test_gemini_without_its_key_is_none(self, monkeypatch):
        monkeypatch.setattr(ep, "GEMINI_API_KEY", None)
        assert build_provider("gemini") is None

    def test_a_typo_is_an_error_not_a_silent_default(self):
        with pytest.raises(ValueError, match="KNOWLEDGE_LLM_PROVIDER"):
            build_provider("deepseek")


class TestParseExtraction:
    def test_parses_fenced_json(self):
        fenced = _FENCE + "json" + chr(10) + '{"persons": []}' + chr(10) + _FENCE
        assert parse_extraction(fenced) == {"persons": []}

    def test_parses_bare_json(self):
        assert parse_extraction('{"event_type": "earnings"}')["event_type"] == "earnings"

    def test_invalid_json_is_none(self):
        assert parse_extraction("not json at all") is None

    def test_a_prose_prefix_before_the_json_is_none_without_raising(self):
        """SYS-19's own repro."""
        assert parse_extraction("Here is the JSON you asked for: {not json") is None

    def test_no_text_is_none_without_raising(self):
        """SYS-19: a safety-blocked response has no text; .strip() on it used to crash."""
        assert parse_extraction(None) is None

    def test_json_that_is_not_an_object_is_none(self):
        """A list or a number parses but would crash extraction.get(...); it is an unusable reply."""
        assert parse_extraction("[1, 2]") is None
        assert parse_extraction("42") is None


class TestReplyCap:
    """SYS-78 (#230): on the first real run one reply in ~100 was cut at the 1,200-token cap,
    unparseable every time, and the article was dropped after 3 attempts."""

    def _cut_reply(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"persons": [{"name": "A"'), finish_reason="length")],
            usage=SimpleNamespace(prompt_tokens=900, completion_tokens=3000))
        return client

    def test_a_cut_reply_is_named_in_the_log_and_still_returned(self, caplog):
        provider = OpenAICompatProvider("deepseek-v4-flash", "k", client=self._cut_reply())
        with caplog.at_level(logging.WARNING, logger="newscrawler.core.extraction_provider"):
            completion = provider.complete("p")
        assert completion.text == '{"persons": [{"name": "A"' and completion.output_tokens == 3000
        assert "cut at max_tokens=" in caplog.text and "KNOWLEDGE_MAX_OUTPUT_TOKENS" in caplog.text
        assert parse_extraction(completion.text) is None

    def test_a_complete_reply_logs_nothing(self, caplog):
        client = _chat('{"persons": []}')
        client.chat.completions.create.return_value.choices[0].finish_reason = "stop"
        with caplog.at_level(logging.WARNING, logger="newscrawler.core.extraction_provider"):
            OpenAICompatProvider("m", "k", client=client).complete("p")
        assert "cut at max_tokens" not in caplog.text

    def test_the_cap_sent_to_the_provider_is_the_configured_one(self, monkeypatch):
        client = _chat("{}")
        OpenAICompatProvider("m", "k", client=client).complete("p")
        assert client.chat.completions.create.call_args.kwargs["max_tokens"] == ep.KNOWLEDGE_MAX_OUTPUT_TOKENS == 3000

    def test_a_custom_cap_is_passed_through(self):
        client = _chat("{}")
        OpenAICompatProvider("m", "k", client=client, max_tokens=500).complete("p")
        assert client.chat.completions.create.call_args.kwargs["max_tokens"] == 500
