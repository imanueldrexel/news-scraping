import json
import logging
from datetime import date, datetime
from typing import Dict, Optional

from newscrawler.core.constants import (
    DAILY_API_CALL_LIMIT,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    KNOWLEDGE_BATCH_SIZE,
)
from newscrawler.core.entity_normalizer import EntityNormalizer
from newscrawler.infrastructure.datasource.dataflow.model.entity_model import (
    EntityMentionModel,
    EntityModel,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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
        self.daily_limit = daily_limit or DAILY_API_CALL_LIMIT
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

    def extract_all(self) -> int:
        if not self._client:
            logger.warning("Skipping extraction: no Gemini model configured.")
            return 0

        current_count = self.ds.get_today_api_call_count(self.model_name)
        if current_count >= self.daily_limit:
            logger.warning(
                f"Daily API limit reached ({current_count}/{self.daily_limit}). "
                "Skipping knowledge extraction."
            )
            return 0

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
        for article_meta in articles:
            current_count = self.ds.get_today_api_call_count(self.model_name)
            if current_count >= self.daily_limit:
                logger.warning("Daily limit reached mid-batch. Stopping.")
                break

            article_id = article_meta["article_id"]
            try:
                extraction = self._call_gemini(article_meta["extracted_text"])
                # Increment regardless of parse success (the API call was made)
                self.ds.increment_api_call_count(self.model_name)

                if extraction is None:
                    # API error (e.g. transient 503) or unparseable response. SYS-19:
                    # this used to leave knowledge_extract_attempts untouched, so a
                    # deterministically-unparseable response burned one Gemini call
                    # every run forever. Recording the failure means it eventually
                    # drops out of get_articles_pending_extraction instead.
                    logger.warning(
                        f"Article {article_id}: no usable extraction (API/parse failure) "
                        "- leaving pending for retry"
                    )
                    self.ds.record_extraction_failure(article_id, "no usable extraction (API/parse failure)")
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
                logger.error(f"Error processing article {article_id}: {e}")
                self.ds.record_extraction_failure(article_id, str(e))

        logger.info(f"Knowledge extraction complete: {processed} articles processed.")
        return processed

    # ── Gemini call ──────────────────────────────────────────────────────────

    def _call_gemini(self, article_text: str) -> Optional[dict]:
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
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error from Gemini response: {e}")
            return None
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
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
                posted_at=self._posted_at_to_date(article_meta["posted_at"]), session=session,
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
                posted_at=self._posted_at_to_date(article_meta["posted_at"]), session=session,
            )
            self._insert_mention(entity_id, article_meta, event_type, article_text, name, session)

        for loc in self._valid_dicts(extraction.get("locations")):
            name = loc.get("name", "").strip()
            if not name:
                continue
            entity_id = self._resolve_or_upsert(
                name, "LOCATION", subtype=None, ticker=None,
                posted_at=self._posted_at_to_date(article_meta["posted_at"]), session=session,
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
                            subtype: Optional[str], ticker: Optional[str],
                            posted_at: date, session) -> int:
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
            first_seen_at=posted_at,
            last_seen_at=posted_at,
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
