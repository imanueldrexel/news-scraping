"""The LLM behind knowledge extraction (SYS-39 #125, ADR-003).

`KnowledgeExtractor` asks a provider for one completion per article and reads
its text; the vendor SDK, the request flags (JSON mode, thinking off) and the
token accounting live here, so the provider is configuration
(`KNOWLEDGE_LLM_PROVIDER`) and a test passes a fake.

The boundary OPS-09 drew is kept: a provider raises `ProviderTransientError`
only when the call never produced a usable response (network, timeout, rate
limit, server error, auth). A response that arrived empty or unparseable is not
an error here: `Completion.text` is None or garbage and the extractor counts it
against the article (SYS-19).
"""
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

from newscrawler.core.constants import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    KNOWLEDGE_LLM_PROVIDER,
    KNOWLEDGE_REQUEST_TIMEOUT_S,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError, call_guarded

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ProviderTransientError(Exception):
    """The call never produced a usable response. Nothing about the article's
    content caused it, so it must not count against `knowledge_extract_attempts`
    (OPS-09: an outage spanning a few runs would retire every article it touched)."""


class ProviderQuotaExhausted(ProviderTransientError):
    """The provider refuses all further calls today (a per-day quota). The
    extractor stops the run instead of failing every remaining article."""

    def __init__(self, message: str, quota: Optional[str] = None):
        super().__init__(message)
        self.quota = quota


@dataclass(frozen=True)
class Completion:
    """One answer. `text` is None for a safety block or an empty reply. Token
    counts are what the provider reported (0 when it reported none)."""
    text: Optional[str]
    input_tokens: int = 0
    output_tokens: int = 0


class ExtractionProvider(Protocol):
    name: str               # the model; also the api_usage_log key
    priced: bool            # True: spend is tracked in dollars; False: the call count is the budget

    def complete(self, prompt: str) -> Completion:
        """Raises ProviderTransientError (or ProviderQuotaExhausted)."""


def _tokens(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


class OpenAICompatProvider:
    """An OpenAI-compatible chat endpoint (SumoPod's `deepseek-v4-flash`).

    Thinking is switched off: deepseek-v4-flash is a reasoning model that can
    spend the whole output budget on reasoning and return nothing (OPS-20), and
    reasoning tokens are billed as output. JSON mode keeps the reply parseable."""
    priced = True

    def __init__(self, model_name: str, api_key: str, base_url: Optional[str] = None, client=None,
                 timeout_s: float = KNOWLEDGE_REQUEST_TIMEOUT_S, max_tokens: int = 1200, sleep=None):
        self.name = model_name
        self._max_tokens = max_tokens
        self._sleep = sleep
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s)
        self._client = client

    def complete(self, prompt: str) -> Completion:
        kwargs = {} if self._sleep is None else {"sleep": self._sleep}
        try:
            response = call_guarded(lambda: self._client.chat.completions.create(
                model=self.name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            ), **kwargs)
        except QuotaExhausted as e:
            raise ProviderQuotaExhausted(str(e), e.quota) from e
        except SummarizerError as e:
            raise ProviderTransientError(str(e)) from e
        usage = getattr(response, "usage", None)
        choices = getattr(response, "choices", None) or []
        text = choices[0].message.content if choices else None
        return Completion(text, _tokens(getattr(usage, "prompt_tokens", 0)),
                          _tokens(getattr(usage, "completion_tokens", 0)))


class GeminiProvider:
    """The previous provider, kept as the fallback. Its request is unchanged
    (JSON mime type; the model's default thinking), only its token counts are read."""
    priced = False

    def __init__(self, model_name: str, api_key: str, client=None):
        self.name = model_name
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self._client = client

    def complete(self, prompt: str) -> Completion:
        try:
            response = self._client.models.generate_content(
                model=self.name, contents=prompt, config={"response_mime_type": "application/json"})
        except Exception as e:  # noqa: BLE001 -- any SDK or network error: no response came back
            raise ProviderTransientError(str(e)) from e
        usage = getattr(response, "usage_metadata", None)
        return Completion(response.text, _tokens(getattr(usage, "prompt_token_count", 0)),
                          _tokens(getattr(usage, "candidates_token_count", 0))
                          + _tokens(getattr(usage, "thoughts_token_count", 0)))


def build_provider(provider: Optional[str] = None) -> Optional[ExtractionProvider]:
    """The configured provider, or None when its credentials are missing
    (extraction is then disabled, as before). `provider` is
    KNOWLEDGE_LLM_PROVIDER: "openai" or "gemini"; empty means gemini, the
    behaviour before SYS-39 -- moving to the priced provider is a deliberate
    config change, not a side effect of an API key being present."""
    provider = (provider if provider is not None else KNOWLEDGE_LLM_PROVIDER) or "gemini"
    if provider not in ("openai", "gemini"):
        raise ValueError(f"KNOWLEDGE_LLM_PROVIDER must be openai, gemini or empty, not {provider!r}")
    if provider == "openai":
        if not OPENAI_API_KEY:
            logger.warning("KNOWLEDGE_LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
            return None
        return OpenAICompatProvider(OPENAI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL)
    return GeminiProvider(GEMINI_MODEL, GEMINI_API_KEY) if GEMINI_API_KEY else None
