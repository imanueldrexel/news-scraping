"""The text-summarizing LLM behind the newsletter (OPS-20 #136, SYS-68 #216, ADR-001).

The generator depends on `Summarizer.summarize(prompt)`, not on a vendor SDK, so
the provider is configuration (`NEWSLETTER_LLM_PROVIDER`) and a test passes a
fake. Two errors matter to the caller: `QuotaExhausted` (the provider refuses
all further calls today, so stop asking) and `SummarizerError` (this one call
failed; the next may succeed).

A call is counted in `api_usage_log` under the model name only once the API
answered (OPS-09's rule): a 429 or a timeout never produced a response and must
not eat budget.

`complete(prompt)` (SYS-98, ADR-005) is the same call without the counting: it
returns the raw `Reply` with the tokens the provider reported, so a caller that
keeps its own books (the RAG page, under `web:<model>` with dollars) can count
it. `summarize` is `complete` + the count + the empty-answer check.
"""
import logging
import re
import time
from typing import Callable, NamedTuple, Optional, Protocol

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
    """The provider refused the call because a DAILY quota is spent (SYS-71: a
    429 that names no per-day quota is a rate limit, retried once, not this).
    Every further call today will fail the same way, so the caller stops."""

    def __init__(self, message: str, quota: Optional[str] = None):
        super().__init__(message)
        self.quota = quota


class Reply(NamedTuple):
    """One answered call: the text as returned (possibly empty) and the tokens
    the provider reported (0 when it reported none)."""
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class Summarizer(Protocol):
    name: str
    priced: bool    # True: calls cost dollars (core.peak_hours prices); False: a free quota

    def summarize(self, prompt: str) -> str:
        """The model's answer. Raises QuotaExhausted or SummarizerError."""

    def complete(self, prompt: str) -> Reply:
        """The answer and its tokens, not counted. Raises QuotaExhausted or SummarizerError."""


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
    it (openai.RateLimitError and google.genai errors both carry them). This
    says the provider pushed back, not for how long: see `is_daily_quota`."""
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    return status == 429 or "RESOURCE_EXHAUSTED" in str(error)


_DAILY = re.compile(r"per[\s_-]?day|daily|requests per day", re.IGNORECASE)


def is_daily_quota(error: BaseException) -> bool:
    """True when the error names a per-DAY quota (Gemini's quotaId
    `...PerDay...`, or the message says daily / per day). Only that is worth
    stopping for (SYS-71): a per-minute 429 clears in seconds."""
    return bool(_DAILY.search(f"{quota_name(error) or ''} {error}"))


RATE_LIMIT_DEFAULT_WAIT_S = 5.0     # no Retry-After given
RATE_LIMIT_MAX_WAIT_S = 30.0        # never stall a digest longer than this per retry

_RETRY_IN_MESSAGE = re.compile(r"retry(?:Delay)?\D{0,12}?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def retry_after_seconds(error: BaseException) -> float:
    """How long the provider asks us to wait: the `Retry-After` header
    (openai SDK errors carry the response), or Gemini's `retryDelay: '23s'` /
    "Please retry in 23.4s" in the message. Bounded to [0, RATE_LIMIT_MAX_WAIT_S];
    RATE_LIMIT_DEFAULT_WAIT_S when it says nothing usable."""
    wait: Optional[float] = None
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers is not None:
        try:
            wait = float(headers.get("retry-after"))
        except (TypeError, ValueError, AttributeError):
            wait = None
    if wait is None:
        match = _RETRY_IN_MESSAGE.search(str(error))
        wait = float(match.group(1)) if match else RATE_LIMIT_DEFAULT_WAIT_S
    return max(0.0, min(wait, RATE_LIMIT_MAX_WAIT_S))


def call_guarded(call: Callable[[], object], sleep: Callable[[float], None] = time.sleep):
    """Run one provider call, translating its failures (SYS-71):
    - a per-day 429 -> QuotaExhausted (the caller stops);
    - any other 429 -> wait `retry_after_seconds`, retry ONCE, and if it is
      refused again a plain SummarizerError (the caller's consecutive-error
      rule decides whether the provider is down);
    - anything else -> SummarizerError naming the exception type."""
    for attempt in (1, 2):
        try:
            return call()
        except Exception as e:  # noqa: BLE001 -- any SDK or network error
            if not is_quota_error(e):
                raise SummarizerError(f"{type(e).__name__}: {e}") from e
            if is_daily_quota(e):
                raise QuotaExhausted(str(e), quota_name(e)) from e
            if attempt == 2:
                raise SummarizerError(f"rate limited twice ({type(e).__name__}): {e}") from e
            wait = retry_after_seconds(e)
            logger.info(f"Summarizer rate-limited; retrying once in {wait:.0f}s.")
            sleep(wait)


def _tokens(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


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
    priced = True

    def __init__(self, model_name: str, api_key: str, base_url: Optional[str] = None,
                 usage: Optional[UsageCounter] = None, client=None,
                 timeout_s: float = NEWSLETTER_SUMMARY_TIMEOUT_S,
                 max_tokens: int = NEWSLETTER_SUMMARY_MAX_TOKENS, sleep=time.sleep):
        self.name = model_name
        self._sleep = sleep
        self._usage = usage
        self._max_tokens = max_tokens
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s)
        self._client = client

    def complete(self, prompt: str) -> Reply:
        response = call_guarded(lambda: self._client.chat.completions.create(
            model=self.name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=self._max_tokens,
            extra_body={"thinking": {"type": "disabled"}},
        ), self._sleep)
        usage = getattr(response, "usage", None)
        return Reply(response.choices[0].message.content or "", _tokens(getattr(usage, "prompt_tokens", 0)),
                     _tokens(getattr(usage, "completion_tokens", 0)))

    def summarize(self, prompt: str) -> str:
        reply = self.complete(prompt)
        _count(self._usage, self.name)
        return _answer(reply.text)


class GeminiSummarizer:
    priced = False      # the free tier: a call quota, not dollars (OPS-20)

    def __init__(self, model_name: str, api_key: str, usage: Optional[UsageCounter] = None, client=None,
                 sleep=time.sleep):
        self.name = model_name
        self._sleep = sleep
        self._usage = usage
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self._client = client

    def complete(self, prompt: str) -> Reply:
        response = call_guarded(
            lambda: self._client.models.generate_content(model=self.name, contents=prompt), self._sleep)
        usage = getattr(response, "usage_metadata", None)
        return Reply(response.text or "", _tokens(getattr(usage, "prompt_token_count", 0)),
                     _tokens(getattr(usage, "candidates_token_count", 0))
                     + _tokens(getattr(usage, "thoughts_token_count", 0)))

    def summarize(self, prompt: str) -> str:
        reply = self.complete(prompt)
        _count(self._usage, self.name)
        return _answer(reply.text)


def _answer(text: Optional[str]) -> str:
    """The reply, or SummarizerError for an empty one (a safety block, or a
    reasoning model that ran out of tokens): an empty summary is not a summary."""
    text = (text or "").strip()
    if not text:
        raise SummarizerError("empty answer")
    return text


def build_summarizer(usage: Optional[UsageCounter] = None, provider: Optional[str] = None,
                     setting: str = "NEWSLETTER_LLM_PROVIDER", **openai_options) -> Optional[Summarizer]:
    """The configured summarizer, or None when no credentials exist (the
    digest then lists headlines and says so). `provider` is
    NEWSLETTER_LLM_PROVIDER (or the variable named by `setting`, e.g.
    RAG_LLM_PROVIDER): "openai", "gemini", or empty to prefer the
    OpenAI-compatible endpoint when its key is set. A forced provider without
    its key is None, never the other provider."""
    provider = (provider if provider is not None else NEWSLETTER_LLM_PROVIDER) or ""
    if provider not in ("", "openai", "gemini"):
        raise ValueError(f"{setting} must be openai, gemini or empty, not {provider!r}")
    if provider in ("", "openai") and OPENAI_API_KEY:
        # openai_options: timeout_s / max_tokens (the RAG page waits less than a digest run).
        return OpenAICompatSummarizer(OPENAI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL, usage=usage, **openai_options)
    if provider in ("", "gemini") and GEMINI_API_KEY:
        return GeminiSummarizer(GEMINI_MODEL, GEMINI_API_KEY, usage=usage)
    return None
