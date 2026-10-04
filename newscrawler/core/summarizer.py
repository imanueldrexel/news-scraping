"""The text-summarizing LLM behind the newsletter (OPS-20 #136, SYS-68 #216, ADR-001).

The generator depends on `Summarizer.summarize(prompt)`, not on a vendor SDK, so
the provider is configuration (`NEWSLETTER_LLM_PROVIDER`) and a test passes a
fake. Two errors matter to the caller: `QuotaExhausted` (the provider refuses
all further calls today, so stop asking) and `SummarizerError` (this one call
failed; the next may succeed).

A call is counted in `api_usage_log` under the model name only once the API
answered (OPS-09's rule): a 429 or a timeout never produced a response and must
not eat budget.
"""
import logging
import re
from typing import Optional, Protocol

from newscrawler.core.constants import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    NEWSLETTER_LLM_PROVIDER,
    NEWSLETTER_SUMMARY_MAX_TOKENS,
    NEWSLETTER_SUMMARY_TIMEOUT_S,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SummarizerError(Exception):
    """One summarization call failed; a later call may still succeed."""


class QuotaExhausted(SummarizerError):
    """The provider refused the call for quota (HTTP 429 / RESOURCE_EXHAUSTED).
    Every further call today will fail the same way, so the caller stops."""

    def __init__(self, message: str, quota: Optional[str] = None):
        super().__init__(message)
        self.quota = quota


class Summarizer(Protocol):
    name: str

    def summarize(self, prompt: str) -> str:
        """The model's answer. Raises QuotaExhausted or SummarizerError."""


class UsageCounter(Protocol):
    def increment_api_call_count(self, api_name: str) -> None: ...


_QUOTA_ID = re.compile(r"quotaId['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_.\-]+)")


def quota_name(error: BaseException) -> Optional[str]:
    """The quota a provider's error names (Gemini: `quotaId`, e.g.
    GenerateRequestsPerDayPerProjectPerModel-FreeTier), or None."""
    match = _QUOTA_ID.search(str(error))
    return match.group(1) if match else None


def is_quota_error(error: BaseException) -> bool:
    """True for an HTTP 429 or a RESOURCE_EXHAUSTED status, whatever SDK raised
    it (openai.RateLimitError and google.genai errors both carry them)."""
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    return status == 429 or "RESOURCE_EXHAUSTED" in str(error)


def _count(usage: Optional[UsageCounter], model_name: str) -> None:
    if usage is None:
        return
    try:
        usage.increment_api_call_count(model_name)
    except Exception as e:  # noqa: BLE001 -- accounting must never cost the summary
        logger.warning(f"Could not count the {model_name} call in api_usage_log: {e}")


class OpenAICompatSummarizer:
    """Any OpenAI-compatible chat endpoint (SumoPod's `deepseek-v4-flash`).
    deepseek-v4-flash is a reasoning model: with thinking on it can spend the
    whole output budget on reasoning and return nothing (EXPERIMENTS, OPS-20),
    so it is switched off; an endpoint that does not know the field ignores it."""

    def __init__(self, model_name: str, api_key: str, base_url: Optional[str] = None,
                 usage: Optional[UsageCounter] = None, client=None,
                 timeout_s: float = NEWSLETTER_SUMMARY_TIMEOUT_S,
                 max_tokens: int = NEWSLETTER_SUMMARY_MAX_TOKENS):
        self.name = model_name
        self._usage = usage
        self._max_tokens = max_tokens
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s)
        self._client = client

    def summarize(self, prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=self._max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except Exception as e:  # noqa: BLE001 -- any SDK or network error
            if is_quota_error(e):
                raise QuotaExhausted(str(e), quota_name(e)) from e
            raise SummarizerError(f"{type(e).__name__}: {e}") from e
        _count(self._usage, self.name)
        return _answer(response.choices[0].message.content)


class GeminiSummarizer:
    def __init__(self, model_name: str, api_key: str, usage: Optional[UsageCounter] = None, client=None):
        self.name = model_name
        self._usage = usage
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self._client = client

    def summarize(self, prompt: str) -> str:
        try:
            response = self._client.models.generate_content(model=self.name, contents=prompt)
        except Exception as e:  # noqa: BLE001
            if is_quota_error(e):
                raise QuotaExhausted(str(e), quota_name(e)) from e
            raise SummarizerError(f"{type(e).__name__}: {e}") from e
        _count(self._usage, self.name)
        return _answer(response.text)


def _answer(text: Optional[str]) -> str:
    """The reply, or SummarizerError for an empty one (a safety block, or a
    reasoning model that ran out of tokens): an empty summary is not a summary."""
    text = (text or "").strip()
    if not text:
        raise SummarizerError("empty answer")
    return text


def build_summarizer(usage: Optional[UsageCounter] = None, provider: Optional[str] = None) -> Optional[Summarizer]:
    """The configured summarizer, or None when no credentials exist (the
    digest then lists headlines and says so). `provider` is
    NEWSLETTER_LLM_PROVIDER: "openai", "gemini", or empty to prefer the
    OpenAI-compatible endpoint when its key is set."""
    provider = (provider if provider is not None else NEWSLETTER_LLM_PROVIDER) or ""
    if provider not in ("", "openai", "gemini"):
        raise ValueError(f"NEWSLETTER_LLM_PROVIDER must be openai, gemini or empty, not {provider!r}")
    if provider in ("", "openai") and OPENAI_API_KEY:
        return OpenAICompatSummarizer(OPENAI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL, usage=usage)
    if provider in ("", "gemini") and GEMINI_API_KEY:
        return GeminiSummarizer(GEMINI_MODEL, GEMINI_API_KEY, usage=usage)
    return None
