import collections
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Dict, Optional

from newscrawler.core.constants import (
    GEMINI_DAILY_CALL_LIMIT,
    GEMINI_MODEL,
    KNOWLEDGE_ALLOW_PEAK,
    KNOWLEDGE_BATCH_SIZE,
    KNOWLEDGE_DAILY_COST_LIMIT_USD,
    KNOWLEDGE_MAX_CONSECUTIVE_ERRORS,
    KNOWLEDGE_MAX_PER_RUN,
    KNOWLEDGE_WORKERS,
)
from newscrawler.core.entity_normalizer import EntityNormalizer
from newscrawler.core.extraction_provider import (
    Completion,
    GeminiProvider,
    ProviderQuotaExhausted,
    ProviderTransientError,
    build_provider,
)
from newscrawler.core.peak_hours import cost_usd, is_peak, next_off_peak
from newscrawler.infrastructure.datasource.dataflow.model.entity_model import (
    EntityMentionModel,
    EntityModel,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class ExtractionResult(int):
    """OPS-11 (#67): `extract_all` returns the processed count as an int (so
    every existing caller keeps working) that also carries what happened to
    the calls: how many articles a call was attempted for, how many of those
    attempts never got a response (ProviderTransientError), and the first such
    error. `attempted > 0 and transient_failures == attempted` is an outage --
    a revoked key, a retired model name, a sustained 5xx -- not N independent
    skips, and the service records it in crawl_log as a failed run.

    SYS-39 (#125): it also carries the tokens the provider reported, what they
    cost, and why the run stopped before the queue was empty (None when it ran
    to the end), so crawl_log can say what a run spent and why it ended."""

    def __new__(cls, processed: int = 0, attempted: int = 0, transient_failures: int = 0,
                first_transient_error: Optional[str] = None, input_tokens: int = 0,
                output_tokens: int = 0, cost_usd: float = 0.0, stopped: Optional[str] = None):
        obj = super().__new__(cls, processed)
        obj.processed = int(processed)
        obj.attempted = attempted
        obj.transient_failures = transient_failures
        obj.first_transient_error = first_transient_error
        obj.input_tokens = input_tokens
        obj.output_tokens = output_tokens
        obj.cost_usd = cost_usd
        obj.stopped = stopped
        return obj

    @property
    def all_calls_failed(self) -> bool:
        return self.attempted > 0 and self.transient_failures == self.attempted

    def note(self) -> Optional[str]:
        """What crawl_log shows beside the count; None for a run that made no call."""
        if not self.attempted and not self.stopped:
            return None
        parts = [f"{self.processed}/{self.attempted} extracted"]
        if self.input_tokens or self.output_tokens:
            parts.append(f"{self.input_tokens} in / {self.output_tokens} out tokens, ${self.cost_usd:.4f}")
        if self.stopped:
            parts.append(f"stopped: {self.stopped}")
        return "; ".join(parts)


# Kept under its old name: OPS-09's tests and docs refer to it, and a Gemini outage
# is still one.
GeminiTransientError = ProviderTransientError


# SYS-76/SYS-77 (QA 2026-10-04): on 200 real articles 30% listed the publishing outlet as an
# organization (Kompas.com 29 times, the most frequent "organization" of the sample) and the
# free-text event_type took 189 distinct values, so neither the KB's entity counts nor
# `kb_query --event-type` meant anything. event_type is now one of a closed list.
EVENT_TYPES = (
    "earnings_report", "corporate_action", "policy_announcement", "regulation_law", "market_movement",
    "commodity_price", "economic_data", "legal_case", "crime", "accident", "disaster",
    "politics_election", "international_relations", "social_welfare", "technology", "other",
)

_PROMPT_TEMPLATE = (
    "Extract entities from the following Indonesian news article.\n"
    "Return ONLY a JSON object with this exact schema and no other text:\n"
    '{{"persons": [{{"name": "string", "role": "string"}}],\n'
    ' "organizations": [{{"name": "string", "type": "string", "ticker": "string or null"}}],\n'
    ' "locations": [{{"name": "string", "type": "string"}}],\n'
    ' "event_type": "string",\n'
    ' "key_metrics": [{{"metric": "string", "value": "string"}}]}}\n'
    "Rules:\n"
    "- Do not list the news outlet that published the article, or its reporters and editors, as an "
    "organization or person (for example Kompas.com, Kontan, Detik, CNBC Indonesia, Antara, Tribunnews, "
    "Liputan6, Beritasatu, jpnn.com), including in a byline, a dateline or a 'Baca juga' line. List an "
    "outlet only when the story is about that outlet.\n"
    '- "event_type" must be exactly one of: ' + ", ".join(EVENT_TYPES) + '. Use "other" when none fits.\n\n'
    "Article:\n{article_text}"
)


def normalize_event_type(value) -> Optional[str]:
    """The closed-list event_type, or None when the model gave none. A value outside the
    list (the model's own wording) is stored as "other", not as a one-off string."""
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not text:
        return None
    return text if text in EVENT_TYPES else "other"

ARTICLE_CHARS = 3000   # how much of an article the prompt carries


def build_prompt(article_text: str) -> str:
    return _PROMPT_TEMPLATE.format(article_text=article_text[:ARTICLE_CHARS])


def parse_extraction(text: Optional[str]) -> Optional[dict]:
    """The extraction dict from a model reply, or None for a reply we cannot use:
    no text (a safety block), or JSON that does not parse. Shared by the extractor
    and the bake-off so both read a reply the same way."""
    if text is None:
        logger.warning("Provider returned no text (likely a safety block)")
        return None
    raw = text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error from the provider's reply: {e}")
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass
class _RunState:
    """What one `extract_all` run has done so far (SYS-39). Touched only by the calling
    thread: the worker threads run provider calls and nothing else."""
    processed: int = 0
    attempted: int = 0
    transient_failures: int = 0
    first_transient_error: Optional[str] = None
    consecutive_failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    stopped: Optional[str] = None
    seen: set = field(default_factory=set)


_FROM_CONFIG = object()   # "build the provider from the environment" (None means: none)


class KnowledgeExtractor:
    workers = 1     # provider calls in flight; __init__ sets KNOWLEDGE_WORKERS (a test may set it directly)

    def __init__(self, knowledge_datasource, api_key: str = None,
                 model_name: str = None, daily_limit: int = None,
                 batch_size: int = None, provider=_FROM_CONFIG, allow_peak: bool = None, workers: int = None,
                 now: Callable[[], datetime] = None):
        """provider: an ExtractionProvider (ADR-003). Left out, it is built from
        KNOWLEDGE_LLM_PROVIDER and the API keys; `api_key` (with an optional
        `model_name`) builds a Gemini one directly, as before. None means no
        provider: extraction is disabled. `daily_limit` is the Gemini call budget
        (an unpriced provider's); a priced provider is held to
        KNOWLEDGE_DAILY_COST_LIMIT_USD instead. `now` is the clock (UTC)."""
        self.ds          = knowledge_datasource
        if api_key is not None and provider is _FROM_CONFIG:
            provider = GeminiProvider(model_name or GEMINI_MODEL, api_key)
        elif provider is _FROM_CONFIG:
            provider = build_provider()
        self._provider   = provider
        self.model_name  = provider.name if provider else (model_name or GEMINI_MODEL)
        self.daily_limit = daily_limit or GEMINI_DAILY_CALL_LIMIT
        self.batch_size  = batch_size  or KNOWLEDGE_BATCH_SIZE
        self.allow_peak  = KNOWLEDGE_ALLOW_PEAK if allow_peak is None else allow_peak
        self.workers     = max(1, workers or KNOWLEDGE_WORKERS)
        self._now        = now or (lambda: datetime.now(timezone.utc))
        self.normalizer  = EntityNormalizer()
        self.alias_map: Dict[str, int] = {}

        if self._provider is None:
            logger.warning("No extraction provider configured (KNOWLEDGE_LLM_PROVIDER, GEMINI_API_KEY, "
                           "OPENAI_API_KEY) — knowledge extraction disabled.")

    # ── Public entry point ───────────────────────────────────────────────────

    def _stop_reason(self) -> Optional[str]:
        """Why the run must not make another call, or None. Checked before every
        article: the peak window opens and the day's budget runs out mid-run."""
        if not self.allow_peak and is_peak(self._now()):
            return (f"peak hours (UTC weekdays 01-04, 06-10; next off-peak "
                    f"{next_off_peak(self._now()):%Y-%m-%d %H:%M} UTC)")
        if self._provider.priced:
            spent = self.ds.get_today_api_usage(self.model_name).cost_usd
            if spent >= KNOWLEDGE_DAILY_COST_LIMIT_USD:
                return (f"daily cost limit reached (${spent:.2f} of "
                        f"${KNOWLEDGE_DAILY_COST_LIMIT_USD:.2f}; KNOWLEDGE_DAILY_COST_LIMIT_USD)")
        else:
            calls = self.ds.get_today_api_call_count(self.model_name)
            if calls >= self.daily_limit:
                return f"daily call limit reached ({calls}/{self.daily_limit}; GEMINI_DAILY_CALL_LIMIT)"
        return None

    def extract_all(self) -> "ExtractionResult":
        if not self._provider:
            logger.warning("Skipping extraction: no extraction provider configured.")
            return ExtractionResult(0)

        stop = self._stop_reason()
        if stop:
            logger.warning(f"Skipping knowledge extraction: {stop}.")
            return ExtractionResult(0, stopped=stop)

        self.alias_map = self.ds.load_alias_map()
        logger.info(f"Loaded {len(self.alias_map)} aliases. Provider {self.model_name}; {self.workers} worker(s); "
                    f"up to {KNOWLEDGE_MAX_PER_RUN} articles this run, {self.batch_size} per query.")

        run = _RunState()
        # A transient failure leaves the article pending (OPS-09), so the next query offers it
        # again: `run.seen` keeps one run from retrying it.
        while not run.stopped and run.attempted < KNOWLEDGE_MAX_PER_RUN:
            articles = [a for a in self.ds.get_articles_pending_extraction(
                min(self.batch_size, KNOWLEDGE_MAX_PER_RUN - run.attempted)) if a["article_id"] not in run.seen]
            if not articles:
                break
            logger.info(f"Found {len(articles)} articles pending extraction.")
            self._extract_batch(articles, run)

        result = ExtractionResult(run.processed, run.attempted, run.transient_failures, run.first_transient_error,
                                  run.input_tokens, run.output_tokens, round(run.cost, 6), run.stopped)
        logger.info(f"Knowledge extraction complete: {result.note() or 'nothing to do'}.")
        if result.all_calls_failed:
            logger.error(
                f"Knowledge extraction: all {run.attempted} call(s) failed without a response "
                f"({run.first_transient_error}) -- an API outage, not {run.attempted} skips. Nothing was extracted."
            )
        return result

    def _extract_batch(self, articles: list, run: "_RunState") -> None:
        """One query's articles. The provider calls run on `self.workers` threads; the
        stop checks, the usage counters and every database write stay on this one, in
        article order. At most `workers` calls are in flight, so a stop (the peak window
        opening, the budget, a quota) overshoots by at most that many calls, each a
        fraction of a cent; their answers are still recorded, because they were paid for."""
        in_flight = collections.deque()
        remaining = iter(articles)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            while True:
                while len(in_flight) < self.workers and not run.stopped:
                    meta = next(remaining, None)
                    if meta is None:
                        break
                    run.stopped = self._stop_reason()
                    if run.stopped:
                        logger.warning(f"Stopping knowledge extraction: {run.stopped}.")
                        break
                    run.seen.add(meta["article_id"])
                    run.attempted += 1
                    in_flight.append((meta, is_peak(self._now()),
                                      pool.submit(self._complete, meta["extracted_text"])))
                if not in_flight:
                    return
                meta, peak, future = in_flight.popleft()
                self._consume(meta, peak, future, run)

    def _consume(self, article_meta: dict, peak: bool, future, run: "_RunState") -> None:
        """One finished call: count it, then extract or record the failure."""
        article_id = article_meta["article_id"]
        try:
            completion = future.result()
        except ProviderQuotaExhausted as e:
            # OPS-20 (#136): "20 extractions, then 429s all day" -- every further
            # call today fails the same way, so stop instead of trying them all.
            run.transient_failures += 1
            run.first_transient_error = run.first_transient_error or f"{type(e).__name__}: {e}"[:200]
            run.stopped = f"provider quota exhausted ({e.quota or 'unnamed quota'})"
            logger.warning(f"Stopping knowledge extraction after {run.processed} extractions this run: "
                           f"{run.stopped}; every further call today will fail the same way.")
            return
        except ProviderTransientError as e:
            # OPS-09 (#63): we never got a response to evaluate, so this has nothing to do with
            # this article's content -- leave knowledge_extract_attempts and today's API call
            # count untouched. The next article gets its own independent attempt rather than
            # assuming one failure means a full outage, until KNOWLEDGE_MAX_CONSECUTIVE_ERRORS
            # in a row say it is one.
            run.transient_failures += 1
            run.consecutive_failures += 1
            run.first_transient_error = run.first_transient_error or f"{type(e).__name__}: {e}"[:200]
            logger.warning(
                f"Article {article_id}: transient provider failure, leaving "
                f"attempts and call count untouched: {e}"
            )
            if run.consecutive_failures >= KNOWLEDGE_MAX_CONSECUTIVE_ERRORS and not run.stopped:
                run.stopped = f"{run.consecutive_failures} failed calls in a row ({run.first_transient_error})"
                logger.error(f"Stopping knowledge extraction: {run.stopped}.")
            return
        run.consecutive_failures = 0

        # Increment regardless of parse success (the API call was made and got a response --
        # this is the boundary ProviderTransientError sits outside of).
        call_cost = (cost_usd(completion.input_tokens, completion.output_tokens, peak)
                     if self._provider.priced else 0.0)
        run.input_tokens += completion.input_tokens
        run.output_tokens += completion.output_tokens
        run.cost += call_cost
        self.ds.increment_api_call_count(self.model_name, input_tokens=completion.input_tokens,
                                         output_tokens=completion.output_tokens, cost_usd=call_cost)
        extraction = parse_extraction(completion.text)

        try:
            if extraction is None:
                # Unparseable response or a safety block -- a response we DID get back but couldn't
                # use. SYS-19: this must count against knowledge_extract_attempts, or a
                # deterministically-unparseable response burns one call every run forever.
                logger.warning(
                    f"Article {article_id}: no usable extraction (safety block/parse failure) "
                    "- leaving pending for retry"
                )
                self.ds.record_extraction_failure(article_id, "no usable extraction (safety block/parse failure)")
                return

            # SYS-19: persons/organizations/locations + mark_article_extracted all happen in one
            # transaction -- a malformed entity (or any other mid-article failure) rolls back every
            # mention this article would have written instead of leaving some committed while the
            # article stays knowledge_extracted=0 (which would double-count them via
            # upsert_entity's mention_count += 1 on the next attempt).
            with self.ds.atomic_extraction_session() as session:
                self._process_extraction(extraction, article_meta, session)
                self.ds.mark_article_extracted(article_id, session=session)
                session.commit()
            run.processed += 1
            logger.debug(f"Processed article {article_id}")
        except Exception as e:
            # A deterministic, content-specific failure (malformed entity shape, a DB constraint
            # this article's data violates) -- distinct from ProviderTransientError above, and
            # legitimately counts against the cap.
            logger.error(f"Error processing article {article_id}: {e}")
            self.ds.record_extraction_failure(article_id, str(e))

    # ── Provider call ────────────────────────────────────────────────────────

    def _complete(self, article_text: str) -> Completion:
        """One provider call for one article. Raises ProviderTransientError for
        anything where the call itself never produced a usable response (see its
        docstring for why that boundary matters, OPS-09 #63); a response that
        arrived but is empty or unparseable is returned and judged by the caller."""
        return self._provider.complete(build_prompt(article_text))

    # ── Extraction processing ────────────────────────────────────────────────

    def _process_extraction(self, extraction: dict, article_meta: dict, session) -> None:
        event_type   = normalize_event_type(extraction.get("event_type"))
        article_text = article_meta["extracted_text"]

        for person in self._valid_dicts(extraction.get("persons")):
            name = person.get("name", "").strip()
            if not name:
                continue
            entity_id = self._resolve_or_upsert(
                name, "PERSON", subtype=None, ticker=None,
                session=session,
            )
            self._insert_mention(entity_id, article_meta, event_type, article_text, name, session)

        for org in self._valid_dicts(extraction.get("organizations")):
            name = org.get("name", "").strip()
            if not name:
                continue
            entity_id = self._resolve_or_upsert(
                name, "ORGANIZATION",
                subtype=self._infer_subtype(org),
                ticker=org.get("ticker") or None,
                session=session,
            )
            self._insert_mention(entity_id, article_meta, event_type, article_text, name, session)

        for loc in self._valid_dicts(extraction.get("locations")):
            name = loc.get("name", "").strip()
            if not name:
                continue
            entity_id = self._resolve_or_upsert(
                name, "LOCATION", subtype=None, ticker=None,
                session=session,
            )
            self._insert_mention(entity_id, article_meta, event_type, article_text, name, session)

    @staticmethod
    def _valid_dicts(items) -> list:
        """SYS-19: Gemini occasionally returns a list of bare strings instead of
        {"name": ...} objects for one of the three entity lists (still valid JSON,
        so _call_gemini doesn't catch it) -- person.get("name") on a str raises
        AttributeError and used to abort the whole article. Skip malformed entries
        instead of letting one bad shape crash entities that parsed fine."""
        if not items:
            return []
        valid = [item for item in items if isinstance(item, dict)]
        if len(valid) != len(items):
            logger.warning(f"Skipped {len(items) - len(valid)} non-object entit(y/ies) in extraction response")
        return valid

    def _resolve_or_upsert(self, name: str, entity_type: str,
                            subtype: Optional[str], ticker: Optional[str], session) -> int:
        """The entity's id. Counting and the seen-dates belong to the mention
        (SYS-20): insert_entity_mention moves them when it inserts one."""
        entity_id = self.normalizer.resolve_alias(name, self.alias_map)
        if entity_id:
            return entity_id

        normalized = self.normalizer.normalize(name)
        model = EntityModel(
            name=name,
            normalized_name=normalized,
            entity_type=entity_type,
            subtype=subtype,
            ticker=ticker,
        )
        entity_id = self.ds.upsert_entity(model, session=session)
        self.alias_map[normalized] = entity_id
        return entity_id

    def _insert_mention(self, entity_id: int, article_meta: dict,
                         event_type: Optional[str], article_text: str,
                         entity_name: str, session) -> None:
        posted_at  = self._posted_at_to_date(article_meta["posted_at"])
        chunk_id   = self.ds.get_l1_chunk_id_for_article(article_meta["sitemap_id"])
        snippet    = self.normalizer.extract_context_snippet(article_text, entity_name)

        model = EntityMentionModel(
            entity_id=entity_id,
            sitemap_id=article_meta["sitemap_id"],
            article_id=article_meta["article_id"],
            chunk_id=chunk_id,
            context_snippet=snippet,
            event_type=event_type,
            posted_at=posted_at,
            source=article_meta["source"],
        )
        self.ds.insert_entity_mention(model, session=session)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _infer_subtype(org: dict) -> Optional[str]:
        if org.get("ticker"):
            return "emiten"
        org_type = (org.get("type") or "").lower()
        if "bank" in org_type:
            return "bank"
        if "kementerian" in org_type or "ministry" in org_type:
            return "ministry"
        return None

    @staticmethod
    def _posted_at_to_date(posted_at) -> date:
        if isinstance(posted_at, date):
            return posted_at
        if isinstance(posted_at, int):
            return datetime.strptime(str(posted_at), "%Y%m%d").date()
        return date.today()
