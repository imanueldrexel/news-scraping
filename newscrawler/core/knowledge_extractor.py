import json
import logging
from datetime import date, datetime
from typing import Dict, Optional

from newscrawler.core.constants import (
    GEMINI_API_KEY,
    GEMINI_DAILY_CALL_LIMIT,
    GEMINI_MODEL,
    KNOWLEDGE_BATCH_SIZE,
)
from newscrawler.core.entity_normalizer import EntityNormalizer
from newscrawler.core.summarizer import is_quota_error, quota_name
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
    attempts never got a response (GeminiTransientError), and the first such
    error. `attempted > 0 and transient_failures == attempted` is an outage --
    a revoked key, a retired model name, a sustained 5xx -- not N independent
    skips, and the service records it in crawl_log as a failed run."""

    def __new__(cls, processed: int = 0, attempted: int = 0, transient_failures: int = 0,
                first_transient_error: Optional[str] = None):
        obj = super().__new__(cls, processed)
        obj.processed = int(processed)
        obj.attempted = attempted
        obj.transient_failures = transient_failures
        obj.first_transient_error = first_transient_error
        return obj

    @property
    def all_calls_failed(self) -> bool:
        return self.attempted > 0 and self.transient_failures == self.attempted


class GeminiTransientError(Exception):
    """OPS-09 (#63): raised by _call_gemini when the API call itself never
    produced a usable response -- network error, timeout, rate limit, server
    error, auth failure -- as opposed to a response we did receive but couldn't
    use (a safety block, or a response that failed JSON parsing). The former has
    nothing to do with this article's content and must never count against
    knowledge_extract_attempts, or a Gemini outage spanning a few runs would
    permanently retire every article it touched -- the exact failure mode SYS-19's
    attempt cap was supposed to guard against, inverted."""


_PROMPT_TEMPLATE = (
    "Extract entities from the following Indonesian news article.\n"
    "Return ONLY a JSON object with this exact schema and no other text:\n"
    '{{"persons": [{{"name": "string", "role": "string"}}],\n'
    ' "organizations": [{{"name": "string", "type": "string", "ticker": "string or null"}}],\n'
    ' "locations": [{{"name": "string", "type": "string"}}],\n'
    ' "event_type": "string",\n'
    ' "key_metrics": [{{"metric": "string", "value": "string"}}]}}\n\n'
    "Article:\n{article_text}"
)


class KnowledgeExtractor:
    def __init__(self, knowledge_datasource, api_key: str = None,
                 model_name: str = None, daily_limit: int = None,
                 batch_size: int = None):
        self.ds          = knowledge_datasource
        self.api_key     = api_key     or GEMINI_API_KEY
        self.model_name  = model_name  or GEMINI_MODEL
        self.daily_limit = daily_limit or GEMINI_DAILY_CALL_LIMIT
        self.batch_size  = batch_size  or KNOWLEDGE_BATCH_SIZE
        self.normalizer  = EntityNormalizer()
        self.alias_map: Dict[str, int] = {}

        if self.api_key:
            from google import genai
            # Initialize the client instead of using a global configuration.
            # (If you set GEMINI_API_KEY as an environment var, you can just use genai.Client())
            self._client = genai.Client(api_key=self.api_key)
            # genai.configure(api_key=self.api_key)
            # self._model = genai.GenerativeModel(self.model_name)
        else:
            logger.warning("GEMINI_API_KEY not set — knowledge extraction disabled.")
            self._client = None

    # ── Public entry point ───────────────────────────────────────────────────

    def extract_all(self) -> "ExtractionResult":
        if not self._client:
            logger.warning("Skipping extraction: no Gemini model configured.")
            return ExtractionResult(0)

        current_count = self.ds.get_today_api_call_count(self.model_name)
        if current_count >= self.daily_limit:
            logger.warning(
                f"Daily API limit reached ({current_count}/{self.daily_limit}). "
                "Skipping knowledge extraction."
            )
            return ExtractionResult(0)

        remaining = self.daily_limit - current_count
        effective_batch = min(self.batch_size, remaining)

        self.alias_map = self.ds.load_alias_map()
        logger.info(
            f"Loaded {len(self.alias_map)} aliases. "
            f"API budget remaining today: {remaining}. "
            f"Will process up to {effective_batch} articles."
        )

        articles = self.ds.get_articles_pending_extraction(effective_batch)
        logger.info(f"Found {len(articles)} articles pending extraction.")

        processed = 0
        # OPS-11 (#67): OPS-09 made a transient API failure leave no trace in
        # any table, by design. Count them here so a run where EVERY call
        # failed is reported as the outage it is (ERROR + crawl_log failed),
        # instead of N warnings nobody reads and exit 0.
        attempted = 0
        transient_failures = 0
        first_transient_error = None
        quota_warned = False
        for article_meta in articles:
            current_count = self.ds.get_today_api_call_count(self.model_name)
            if current_count >= self.daily_limit:
                logger.warning("Daily limit reached mid-batch. Stopping.")
                break

            article_id = article_meta["article_id"]
            attempted += 1
            try:
                extraction = self._call_gemini(article_meta["extracted_text"])
            except GeminiTransientError as e:
                # OPS-09 (#63): we never got a response to evaluate, so this has
                # nothing to do with this article's content -- leave
                # knowledge_extract_attempts and today's API call count untouched.
                # continue (not break): the next article gets its own independent
                # attempt rather than assuming one failure means a full outage.
                transient_failures += 1
                first_transient_error = first_transient_error or f"{type(e).__name__}: {e}"[:200]
                logger.warning(
                    f"Article {article_id}: transient Gemini API failure, leaving "
                    f"attempts and call count untouched: {e}"
                )
                if not quota_warned and is_quota_error(e.__cause__ or e):
                    # OPS-20 (#136): "20 extractions, then 429s all day" must be
                    # visible: one WARNING per run, naming the quota that ran out.
                    quota_warned = True
                    logger.warning(
                        f"Gemini quota exhausted ({quota_name(e.__cause__ or e) or 'unnamed quota'}) "
                        f"after {processed} extractions this run; every further call today will "
                        f"fail the same way. GEMINI_DAILY_CALL_LIMIT={self.daily_limit} should match "
                        f"the project's real per-model quota."
                    )
                continue

            # Increment regardless of parse success (the API call was made and got
            # a response -- this is the boundary GeminiTransientError sits outside of).
            self.ds.increment_api_call_count(self.model_name)

            try:
                if extraction is None:
                    # Unparseable response or a safety block -- a response we DID
                    # get back but couldn't use. SYS-19: this must count against
                    # knowledge_extract_attempts, or a deterministically-unparseable
                    # response burns one Gemini call every run forever.
                    logger.warning(
                        f"Article {article_id}: no usable extraction (safety block/parse failure) "
                        "- leaving pending for retry"
                    )
                    self.ds.record_extraction_failure(article_id, "no usable extraction (safety block/parse failure)")
                    continue

                # SYS-19: persons/organizations/locations + mark_article_extracted all
                # happen in one transaction now -- a malformed entity (or any other
                # mid-article failure) rolls back every mention this article would
                # have written instead of leaving some committed while the article
                # stays knowledge_extracted=0 (which would double-count them via
                # upsert_entity's mention_count += 1 on the next attempt).
                with self.ds.atomic_extraction_session() as session:
                    self._process_extraction(extraction, article_meta, session)
                    self.ds.mark_article_extracted(article_id, session=session)
                    session.commit()
                processed += 1
                logger.debug(f"Processed article {article_id}")
            except Exception as e:
                # A deterministic, content-specific failure (malformed entity shape,
                # a DB constraint this article's data violates) -- distinct from
                # GeminiTransientError above, and legitimately counts against the cap.
                logger.error(f"Error processing article {article_id}: {e}")
                self.ds.record_extraction_failure(article_id, str(e))

        logger.info(f"Knowledge extraction complete: {processed} articles processed.")
        result = ExtractionResult(processed, attempted, transient_failures, first_transient_error)
        if result.all_calls_failed:
            logger.error(
                f"Knowledge extraction: all {attempted} Gemini call(s) failed without a response "
                f"({first_transient_error}) -- an API outage, not {attempted} skips. Nothing was extracted."
            )
        return result

    # ── Gemini call ──────────────────────────────────────────────────────────

    def _call_gemini(self, article_text: str) -> Optional[dict]:
        """Returns the parsed dict on success, or None for a deterministic failure
        (a response we did receive but couldn't use -- a safety block, or JSON that
        failed to parse). Raises GeminiTransientError for anything where the API
        call itself never produced a usable response (network error, timeout, rate
        limit, server error, auth failure) -- see GeminiTransientError's docstring
        for why that boundary matters (OPS-09, #63)."""
        truncated = article_text[:3000]
        prompt    = _PROMPT_TEMPLATE.format(article_text=truncated)
        try:
            # SYS-19: ask Gemini to constrain its own output to JSON. Doesn't
            # eliminate every failure mode (a safety block still returns no text;
            # the model can still emit JSON with the wrong shape), but removes the
            # "prose prefix before the JSON" class of parse failure at the source
            # instead of only handling it after the fact.
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
        except Exception as e:
            raise GeminiTransientError(str(e)) from e

        if response.text is None:
            # Safety block or an otherwise empty response -- nothing to parse.
            logger.warning("Gemini returned no text (likely a safety block)")
            return None
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error from Gemini response: {e}")
            return None

    # ── Extraction processing ────────────────────────────────────────────────

    def _process_extraction(self, extraction: dict, article_meta: dict, session) -> None:
        event_type   = extraction.get("event_type") or None
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
