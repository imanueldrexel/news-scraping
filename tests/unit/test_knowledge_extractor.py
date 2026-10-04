"""
Unit tests for KnowledgeExtractor (Phase 2): JSON parsing, entity processing, the
daily-limit guard, and SYS-19's poison-pill handling -- a failed extraction must
record an attempt (so it eventually drops out of the pending query) instead of being
silently retried forever, and a partial failure mid-article must roll back instead of
leaving some mentions committed.
"""
import json
import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from newscrawler.core.entity_normalizer import EntityNormalizer
from newscrawler.core.extraction_provider import Completion, ProviderQuotaExhausted
from newscrawler.core.knowledge_extractor import GeminiTransientError, KnowledgeExtractor


class FakeProvider:
    """A provider that is never called: tests replace `kx._complete`."""
    name = "gemini-test"
    priced = False

    def complete(self, prompt):
        raise AssertionError("the provider was called")


def _make(ds=None, client=None, daily_limit=1400, batch_size=50):
    """`client` is truthy when a provider is configured (None: extraction disabled)."""
    kx = KnowledgeExtractor.__new__(KnowledgeExtractor)
    kx.ds = ds or _mock_ds()
    kx._provider = FakeProvider() if client is not None else None
    kx.model_name = "gemini-test"
    kx.daily_limit = daily_limit
    kx.batch_size = batch_size
    kx.allow_peak = True          # the clock is not under test here (test_extraction_stops.py)
    kx._now = lambda: datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)   # a Saturday: off-peak
    kx.normalizer = EntityNormalizer()
    kx.alias_map = {}
    return kx


def _wrapped(fn):
    """Adapt a test's `text -> extraction dict | None` into a provider answer."""
    def complete(text):
        result = fn(text)
        return Completion(None if result is None else json.dumps(result))
    return complete


def _mock_ds():
    """A MagicMock whose atomic_extraction_session() behaves like a real context
    manager (MagicMock supports __enter__/__exit__ automatically)."""
    ds = MagicMock()
    return ds


class TestInferSubtype:
    def test_ticker_means_emiten(self):
        assert KnowledgeExtractor._infer_subtype({"ticker": "BBCA"}) == "emiten"

    def test_bank(self):
        assert KnowledgeExtractor._infer_subtype({"type": "Bank BUMN"}) == "bank"

    def test_ministry(self):
        assert KnowledgeExtractor._infer_subtype({"type": "Kementerian Keuangan"}) == "ministry"

    def test_other_none(self):
        assert KnowledgeExtractor._infer_subtype({"type": "startup"}) is None


class TestProcessExtraction:
    def _meta(self):
        return {"article_id": 1, "sitemap_id": 2, "posted_at": 20260101,
                "source": "WARTAEKONOMI", "extracted_text": "Prabowo di Jakarta dari BCA"}

    def test_upserts_all_entity_types(self):
        ds = MagicMock()
        ds.upsert_entity.side_effect = [10, 11, 12]
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds)
        extraction = {
            "persons": [{"name": "Prabowo", "role": "Presiden"}],
            "organizations": [{"name": "BCA", "type": "Bank", "ticker": "BBCA"}],
            "locations": [{"name": "Jakarta", "type": "city"}],
            "event_type": "policy",
        }
        session = MagicMock()
        kx._process_extraction(extraction, self._meta(), session)
        types = [c.args[0].entity_type for c in ds.upsert_entity.call_args_list]
        assert types == ["PERSON", "ORGANIZATION", "LOCATION"]
        assert ds.insert_entity_mention.call_count == 3
        # every write must carry the shared session through, not open its own
        for c in ds.upsert_entity.call_args_list + ds.insert_entity_mention.call_args_list:
            assert c.kwargs.get("session") is session

    def test_blank_names_skipped(self):
        ds = MagicMock()
        ds.upsert_entity.return_value = 1
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds)
        kx._process_extraction({"persons": [{"name": "  "}]}, self._meta(), MagicMock())
        ds.upsert_entity.assert_not_called()

    def test_non_dict_entities_are_skipped_not_crashed(self):
        """SYS-19: Gemini can return a list of bare strings for one of the three
        entity lists despite still being valid JSON overall -- person.get("name")
        on a str used to raise AttributeError and abort the whole article."""
        ds = MagicMock()
        ds.upsert_entity.return_value = 1
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds)
        extraction = {
            "persons": ["Prabowo", "Sri Mulyani"],  # malformed: bare strings
            "organizations": [{"name": "BCA"}],      # well-formed
        }
        kx._process_extraction(extraction, self._meta(), MagicMock())  # must not raise
        assert ds.upsert_entity.call_count == 1
        assert ds.upsert_entity.call_args.args[0].entity_type == "ORGANIZATION"


class TestExtractAllGuards:
    def test_no_client_returns_zero(self):
        assert _make(client=None).extract_all() == 0

    def test_daily_limit_blocks_run(self):
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 1400
        kx = _make(ds=ds, client=MagicMock(), daily_limit=1400)
        assert kx.extract_all() == 0
        ds.get_articles_pending_extraction.assert_not_called()

    def test_failed_extraction_not_marked_and_attempt_recorded(self):
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": 9, "sitemap_id": 2, "posted_at": 20260101,
             "source": "S", "extracted_text": "x"}
        ]
        kx = _make(ds=ds, client=MagicMock())
        kx._complete = _wrapped(lambda text: None)
        assert kx.extract_all() == 0
        ds.mark_article_extracted.assert_not_called()
        ds.increment_api_call_count.assert_called()
        # SYS-19: must record the failed attempt so this article eventually drops
        # out of get_articles_pending_extraction instead of retrying forever.
        ds.record_extraction_failure.assert_called_once()
        assert ds.record_extraction_failure.call_args.args[0] == 9

    def test_successful_extraction_marks_article(self):
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": 9, "sitemap_id": 2, "posted_at": 20260101,
             "source": "S", "extracted_text": "x"}
        ]
        ds.upsert_entity.return_value = 1
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds, client=MagicMock())
        kx._complete = _wrapped(lambda text: {"persons": [{"name": "Prabowo"}], "event_type": "x"})
        assert kx.extract_all() == 1
        ds.mark_article_extracted.assert_called_once()
        assert ds.mark_article_extracted.call_args.args[0] == 9
        assert ds.mark_article_extracted.call_args.kwargs.get("session") is not None
        ds.record_extraction_failure.assert_not_called()

    def test_transient_api_failure_does_not_record_attempt_or_consume_quota(self):
        """OPS-09 (#63): a GeminiTransientError must leave knowledge_extract_attempts
        and today's API call count untouched -- otherwise a Gemini outage spanning
        a few runs permanently retires every article it touches."""
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": 9, "sitemap_id": 2, "posted_at": 20260101,
             "source": "S", "extracted_text": "x"}
        ]
        kx = _make(ds=ds, client=MagicMock())

        def raise_transient(text):
            raise GeminiTransientError("503 Service Unavailable")
        kx._complete = _wrapped(raise_transient)

        assert kx.extract_all() == 0
        ds.record_extraction_failure.assert_not_called()
        ds.increment_api_call_count.assert_not_called()
        ds.mark_article_extracted.assert_not_called()

    def test_transient_failure_on_one_article_does_not_stop_the_rest_of_the_batch(self):
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": 1, "sitemap_id": 1, "posted_at": 20260101, "source": "S", "extracted_text": "x"},
            {"article_id": 2, "sitemap_id": 2, "posted_at": 20260101, "source": "S", "extracted_text": "x"},
        ]
        ds.upsert_entity.return_value = 1
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds, client=MagicMock())

        def flaky(text):
            flaky.calls += 1
            if flaky.calls == 1:
                raise GeminiTransientError("timeout")
            return {"persons": [{"name": "Prabowo"}]}
        flaky.calls = 0
        kx._complete = _wrapped(flaky)

        assert kx.extract_all() == 1
        ds.mark_article_extracted.assert_called_once()
        assert ds.mark_article_extracted.call_args.args[0] == 2
        ds.record_extraction_failure.assert_not_called()

    def test_simulated_three_run_outage_leaves_article_still_selectable(self):
        """OPS-09 (#63) Done-when: a simulated 3-run API outage must leave the
        article still selectable afterwards -- i.e. knowledge_extract_attempts
        never moves, so get_articles_pending_extraction (mocked here as always
        returning the same article, since attempts never changed) keeps offering it."""
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": 9, "sitemap_id": 2, "posted_at": 20260101,
             "source": "S", "extracted_text": "x"}
        ]
        kx = _make(ds=ds, client=MagicMock())
        kx._complete = _wrapped(lambda text: (_ for _ in ()).throw(GeminiTransientError("outage")))

        for _ in range(3):
            assert kx.extract_all() == 0

        ds.record_extraction_failure.assert_not_called()
        # every run was offered the article again (a run asks once more for the next batch)
        assert ds.get_articles_pending_extraction.call_count >= 3

    def test_process_extraction_raising_records_failure_and_rolls_back(self):
        """SYS-19: a mid-article crash (e.g. a malformed entity that still slips
        past _valid_dicts, or a DB error) must record the attempt via the outer
        except, and mark_article_extracted must not have been called."""
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": 9, "sitemap_id": 2, "posted_at": 20260101,
             "source": "S", "extracted_text": "x"}
        ]
        ds.upsert_entity.side_effect = RuntimeError("DB exploded")
        kx = _make(ds=ds, client=MagicMock())
        kx._complete = _wrapped(lambda text: {"persons": [{"name": "Prabowo"}]})
        assert kx.extract_all() == 0
        ds.mark_article_extracted.assert_not_called()
        ds.record_extraction_failure.assert_called_once()
        assert ds.record_extraction_failure.call_args.args[0] == 9
        assert "DB exploded" in ds.record_extraction_failure.call_args.args[1]


class TestExtractAllOutageSignal:
    """OPS-11 (#67): a run in which every Gemini call fails without a response
    is an outage and must be reported as one -- OPS-09 (correctly) stopped
    those failures from counting against attempts or the call budget, which
    left them with no trace in any table."""

    def _ds(self, n):
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": i, "sitemap_id": i, "posted_at": 20260101, "source": "S", "extracted_text": "x"}
            for i in range(1, n + 1)
        ]
        return ds

    def test_every_call_failing_is_reported_as_an_outage(self, caplog):
        ds = self._ds(3)
        kx = _make(ds=ds, client=MagicMock())

        def boom(text):
            raise GeminiTransientError("429 RESOURCE_EXHAUSTED quota")
        kx._complete = _wrapped(boom)
        with caplog.at_level(logging.ERROR, logger="newscrawler.core.knowledge_extractor"):
            result = kx.extract_all()
        assert result == 0 and isinstance(result, int)
        assert (result.attempted, result.transient_failures, result.all_calls_failed) == (3, 3, True)
        assert "429" in result.first_transient_error
        assert any("all 3 call(s) failed" in r.message for r in caplog.records)
        ds.increment_api_call_count.assert_not_called()      # OPS-09 semantics untouched
        ds.record_extraction_failure.assert_not_called()

    def test_a_partial_failure_is_not_an_outage(self):
        ds = self._ds(2)
        kx = _make(ds=ds, client=MagicMock())
        calls = iter([GeminiTransientError("timeout"), None])

        def flaky(text):
            r = next(calls)
            if isinstance(r, Exception):
                raise r
            return r
        kx._complete = _wrapped(flaky)
        result = kx.extract_all()
        assert (result.attempted, result.transient_failures, result.all_calls_failed) == (2, 1, False)

    def test_no_articles_is_not_an_outage(self):
        ds = self._ds(0)
        result = _make(ds=ds, client=MagicMock()).extract_all()
        assert (int(result), result.attempted, result.all_calls_failed) == (0, 0, False)


class TestQuotaStop:
    """OPS-20 (#136): "20 extractions, then 429s all day" must be visible and must
    not spin. A provider's per-day quota ends the run and the run says which quota;
    an ordinary transient failure does not."""

    def _ds(self, n):
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": i, "sitemap_id": i, "posted_at": 20260101, "source": "S", "extracted_text": "x"}
            for i in range(1, n + 1)
        ]
        return ds

    def test_a_daily_quota_ends_the_run_and_names_the_quota(self, caplog):
        kx = _make(ds=self._ds(4), client=MagicMock())

        def quota(text):
            raise ProviderQuotaExhausted("429", "GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        kx._complete = _wrapped(quota)
        with caplog.at_level(logging.WARNING, logger="newscrawler.core.knowledge_extractor"):
            result = kx.extract_all()
        assert result.attempted == 1, "every further call today fails the same way: stop, do not try all four"
        assert "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in result.stopped
        assert result.all_calls_failed
        assert [r for r in caplog.records if "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in r.message]
        kx.ds.record_extraction_failure.assert_not_called()      # OPS-09: the article is not at fault

    def test_an_ordinary_transient_failure_does_not_stop_the_batch(self, caplog):
        kx = _make(ds=self._ds(2), client=MagicMock())

        def timeout(text):
            raise GeminiTransientError("timeout")
        kx._complete = _wrapped(timeout)
        result = kx.extract_all()
        assert result.attempted == 2 and result.stopped is None

    def test_the_default_budget_is_geminis_not_the_other_endpoints(self, monkeypatch):
        """OPS-20: Gemini's per-model quota (20/day on the free tier) and the
        OpenAI-compatible endpoint's budget are two numbers."""
        import newscrawler.core.extraction_provider as ep
        monkeypatch.setattr(ep, "GEMINI_API_KEY", None)
        monkeypatch.setattr(ep, "OPENAI_API_KEY", None)
        monkeypatch.setattr(ep, "KNOWLEDGE_LLM_PROVIDER", "")
        import newscrawler.core.knowledge_extractor as ke
        monkeypatch.setattr(ke, "GEMINI_DAILY_CALL_LIMIT", 20)
        assert KnowledgeExtractor(MagicMock()).daily_limit == 20


class TestEventTypeAndOutletRules:
    """SYS-76 (#228) / SYS-77 (#229): on 200 real articles 30% listed the publishing outlet as an
    entity and event_type took 189 distinct values. The measured before/after is in
    EXPERIMENTS.md (2026-10-04, 'SYS-76/77'); these pin the pieces the unit level can see."""

    def test_the_prompt_lists_the_closed_event_types(self):
        from newscrawler.core.knowledge_extractor import EVENT_TYPES, build_prompt
        prompt = build_prompt("isi")
        for value in EVENT_TYPES:
            assert value in prompt
        assert "other" in EVENT_TYPES and len(EVENT_TYPES) == len(set(EVENT_TYPES))

    def test_the_prompt_forbids_the_outlet_and_its_reporters(self):
        from newscrawler.core.knowledge_extractor import build_prompt
        prompt = build_prompt("isi")
        for outlet in ("Kompas.com", "Kontan", "Detik", "CNBC Indonesia", "Antara"):
            assert outlet in prompt
        assert "reporters and editors" in prompt and "byline" in prompt and "'Baca juga' line" in prompt
        assert "only when the story is about that outlet" in prompt

    def test_the_schema_keys_are_unchanged(self):
        from newscrawler.core.knowledge_extractor import build_prompt
        prompt = build_prompt("isi")
        for key in ('"persons"', '"organizations"', '"locations"', '"event_type"', '"key_metrics"'):
            assert key in prompt

    @pytest.mark.parametrize("given,stored", [
        ("policy_announcement", "policy_announcement"),
        ("Policy Announcement", "policy_announcement"),
        ("  LEGAL-CASE ", "legal_case"),
        ("kecelakaan lalu lintas", "other"),
        ("commodity price movement", "other"),
        ("other", "other"),
        ("", None), (None, None), ("   ", None),
    ])
    def test_normalize_event_type(self, given, stored):
        from newscrawler.core.knowledge_extractor import normalize_event_type
        assert normalize_event_type(given) == stored

    def test_the_mention_stores_the_normalised_value(self):
        ds = MagicMock()
        ds.upsert_entity.return_value = 1
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds)
        meta = {"article_id": 1, "sitemap_id": 2, "posted_at": 20260101, "source": "S",
                "extracted_text": "Prabowo di Jakarta"}
        kx._process_extraction({"persons": [{"name": "Prabowo"}], "event_type": "Pelantikan Menteri"}, meta, MagicMock())
        mention = ds.insert_entity_mention.call_args.args[0]
        assert mention.event_type == "other"
        kx._process_extraction({"persons": [{"name": "Prabowo"}], "event_type": "Politics Election"}, meta, MagicMock())
        assert ds.insert_entity_mention.call_args.args[0].event_type == "politics_election"
