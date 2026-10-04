"""SYS-39 (#125): how an extraction run on a priced provider is bounded and
accounted -- the peak window, the day's dollar budget, a provider that is down,
the per-run cap, running on until the queue is empty, and the tokens and cost
written to api_usage_log for every answered call. A fake provider and a fake
clock; no network, no database."""
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import newscrawler.core.knowledge_extractor as ke
from newscrawler.core.entity_normalizer import EntityNormalizer
from newscrawler.core.extraction_provider import Completion, ProviderQuotaExhausted, ProviderTransientError
from newscrawler.core.knowledge_extractor import KnowledgeExtractor
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
    ApiUsage,
)

SATURDAY_NOON = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)      # off-peak
MONDAY_0700 = datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)         # peak
MONDAY_1200 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)        # off-peak
REPLY = json.dumps({"persons": [{"name": "Prabowo"}], "event_type": "x"})


class ScriptedProvider:
    """Answers from a list: a Completion, or an exception to raise."""
    name = "deepseek-test"

    def __init__(self, answers=None, priced=True):
        self.priced = priced
        self.answers = list(answers) if answers is not None else None
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        if self.answers is None:
            return Completion(REPLY, 700, 300)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _articles(first, n):
    return [{"article_id": i, "sitemap_id": i, "posted_at": 20260101, "source": "S", "extracted_text": "x"}
            for i in range(first, first + n)]


def _ds(batches, spent=0.0, calls=0):
    """`batches`: what successive get_articles_pending_extraction calls return."""
    ds = MagicMock()
    ds.load_alias_map.return_value = {}
    queue = list(batches) + [[]] * 5
    ds.get_articles_pending_extraction.side_effect = lambda limit: queue.pop(0)[:limit]   # LIMIT :batch_size
    ds.get_today_api_usage.return_value = ApiUsage(calls, 0, 0, spent)
    ds.get_today_api_call_count.return_value = calls
    ds.upsert_entity.return_value = 1
    ds.get_l1_chunk_id_for_article.return_value = None
    return ds


def _kx(ds, provider=None, now=SATURDAY_NOON, allow_peak=False, monkeypatch=None):
    kx = KnowledgeExtractor.__new__(KnowledgeExtractor)
    kx.ds = ds
    kx._provider = provider or ScriptedProvider()
    kx.model_name = kx._provider.name
    kx.daily_limit = 20
    kx.batch_size = 50
    kx.allow_peak = allow_peak
    kx._now = lambda: now
    kx.normalizer = EntityNormalizer()
    kx.alias_map = {}
    return kx


class TestPeakHours:
    def test_a_run_started_in_a_peak_block_makes_no_call(self):
        ds = _ds([_articles(1, 3)])
        kx = _kx(ds, now=MONDAY_0700)
        result = kx.extract_all()
        assert result.attempted == 0 and "peak hours" in result.stopped and "10:00 UTC" in result.stopped
        assert kx._provider.prompts == []
        ds.get_articles_pending_extraction.assert_not_called()

    def test_allow_peak_runs_anyway_and_prices_the_call_at_the_peak_rate(self):
        ds = _ds([_articles(1, 1)])
        kx = _kx(ds, now=MONDAY_0700, allow_peak=True)
        assert kx.extract_all() == 1
        # 700 in x $0.30 + 300 out x $1.20 per 1M
        assert ds.increment_api_call_count.call_args.kwargs["cost_usd"] == pytest.approx(0.00057)

    def test_off_peak_is_priced_at_the_off_peak_rate(self):
        ds = _ds([_articles(1, 1)])
        _kx(ds, now=MONDAY_1200).extract_all()
        assert ds.increment_api_call_count.call_args.kwargs["cost_usd"] == pytest.approx(0.000285)

    def test_a_weekend_is_never_peak(self):
        ds = _ds([_articles(1, 1)])
        assert _kx(ds, now=datetime(2026, 10, 4, 7, 0, tzinfo=timezone.utc)).extract_all() == 1

    def test_the_window_opening_mid_run_stops_it_before_the_next_call(self):
        clock = iter([MONDAY_1200, MONDAY_1200, MONDAY_1200, MONDAY_1200, MONDAY_0700, MONDAY_0700, MONDAY_0700])
        ds = _ds([_articles(1, 5)])
        kx = _kx(ds)
        kx._now = lambda: next(clock)
        result = kx.extract_all()
        assert 0 < result.attempted < 5, "some articles were done off-peak, the rest wait"
        assert "peak hours" in result.stopped


class TestCostLimit:
    def test_a_spent_budget_makes_no_call(self, monkeypatch):
        monkeypatch.setattr(ke, "KNOWLEDGE_DAILY_COST_LIMIT_USD", 5.0)
        ds = _ds([_articles(1, 3)], spent=5.0)
        kx = _kx(ds)
        result = kx.extract_all()
        assert result.attempted == 0 and "daily cost limit" in result.stopped and "$5.00" in result.stopped
        assert kx._provider.prompts == []

    def test_the_budget_running_out_mid_run_ends_it(self, monkeypatch):
        monkeypatch.setattr(ke, "KNOWLEDGE_DAILY_COST_LIMIT_USD", 1.0)
        ds = _ds([_articles(1, 5)])
        # checked once at the start and once before each article
        ds.get_today_api_usage.side_effect = [ApiUsage(0, 0, 0, spent) for spent in (0.0, 0.0, 0.5, 1.2, 1.2)]
        kx = _kx(ds)
        result = kx.extract_all()
        assert result.attempted == 2 and "daily cost limit" in result.stopped

    def test_an_unpriced_provider_is_held_to_its_call_budget_not_dollars(self):
        ds = _ds([_articles(1, 3)], calls=20)
        kx = _kx(ds, provider=ScriptedProvider(priced=False))
        result = kx.extract_all()
        assert result.attempted == 0 and "daily call limit reached (20/20" in result.stopped
        ds.get_today_api_usage.assert_not_called()

    def test_a_priced_provider_is_not_held_to_the_gemini_call_limit(self):
        """GEMINI_DAILY_CALL_LIMIT (20) must not gate DeepSeek: 4,000 calls a day is normal."""
        ds = _ds([_articles(1, 3)], calls=3000)
        assert _kx(ds).extract_all() == 3
        ds.get_today_api_call_count.assert_not_called()


class TestAccounting:
    def test_every_answered_call_records_its_tokens_and_cost(self):
        ds = _ds([_articles(1, 2)])
        kx = _kx(ds, provider=ScriptedProvider([Completion(REPLY, 700, 300), Completion(REPLY, 800, 250)]))
        result = kx.extract_all()
        calls = ds.increment_api_call_count.call_args_list
        assert [c.args[0] for c in calls] == ["deepseek-test", "deepseek-test"]
        assert [(c.kwargs["input_tokens"], c.kwargs["output_tokens"]) for c in calls] == [(700, 300), (800, 250)]
        assert (result.input_tokens, result.output_tokens) == (1500, 550)
        assert result.cost_usd == pytest.approx(0.000285 + 0.00027)

    def test_an_unparseable_answer_is_still_counted_and_costs_money(self):
        ds = _ds([_articles(1, 1)])
        kx = _kx(ds, provider=ScriptedProvider([Completion("not json", 700, 40)]))
        result = kx.extract_all()
        assert result.processed == 0 and result.input_tokens == 700
        ds.increment_api_call_count.assert_called_once()
        ds.record_extraction_failure.assert_called_once()        # SYS-19: counts against the article

    def test_a_failed_call_records_nothing(self):
        ds = _ds([_articles(1, 1)])
        kx = _kx(ds, provider=ScriptedProvider([ProviderTransientError("503")]))
        result = kx.extract_all()
        ds.increment_api_call_count.assert_not_called()
        ds.record_extraction_failure.assert_not_called()
        assert (result.input_tokens, result.cost_usd) == (0, 0.0)

    def test_an_unpriced_call_costs_nothing_but_still_reports_tokens(self):
        ds = _ds([_articles(1, 1)])
        result = _kx(ds, provider=ScriptedProvider(priced=False)).extract_all()
        assert ds.increment_api_call_count.call_args.kwargs["cost_usd"] == 0.0
        assert result.input_tokens == 700

    def test_the_crawl_log_note_says_what_ran(self):
        ds = _ds([_articles(1, 2)])
        note = _kx(ds).extract_all().note()
        assert "2/2 extracted" in note and "1400 in / 600 out tokens" in note and "stopped" not in note

    def test_a_run_with_nothing_to_do_has_no_note(self):
        assert _kx(_ds([])).extract_all().note() is None


class TestRunsOnUntilTheQueueIsEmpty:
    def test_it_keeps_fetching_batches(self):
        ds = _ds([_articles(1, 3), _articles(4, 3), _articles(7, 2)])
        kx = _kx(ds)
        kx.batch_size = 3
        result = kx.extract_all()
        assert result.attempted == 8 and result.processed == 8
        assert [c.args[0] for c in ds.get_articles_pending_extraction.call_args_list[:3]] == [3, 3, 3]

    def test_the_per_run_cap_ends_it(self, monkeypatch):
        monkeypatch.setattr(ke, "KNOWLEDGE_MAX_PER_RUN", 5)
        ds = _ds([_articles(1, 3), _articles(4, 3), _articles(7, 3)])
        kx = _kx(ds)
        kx.batch_size = 3
        result = kx.extract_all()
        assert result.attempted == 5
        assert ds.get_articles_pending_extraction.call_args_list[1].args[0] == 2, "asks only for what is left"

    def test_an_article_that_failed_transiently_is_not_retried_in_the_same_run(self):
        """It stays pending (OPS-09), so the next query offers it again."""
        ds = _ds([_articles(1, 2), _articles(1, 2)])
        provider = ScriptedProvider([ProviderTransientError("timeout"), Completion(REPLY, 700, 300)])
        result = _kx(ds, provider=provider).extract_all()
        assert result.attempted == 2 and len(provider.prompts) == 2


class TestProviderDown:
    def test_consecutive_failures_stop_the_run(self, monkeypatch):
        monkeypatch.setattr(ke, "KNOWLEDGE_MAX_CONSECUTIVE_ERRORS", 3)
        ds = _ds([_articles(1, 10)])
        provider = ScriptedProvider([ProviderTransientError("502")] * 10)
        result = _kx(ds, provider=provider).extract_all()
        assert result.attempted == 3 and len(provider.prompts) == 3
        assert "3 failed calls in a row" in result.stopped and "502" in result.stopped
        assert result.all_calls_failed

    def test_a_success_resets_the_count(self, monkeypatch):
        monkeypatch.setattr(ke, "KNOWLEDGE_MAX_CONSECUTIVE_ERRORS", 3)
        ds = _ds([_articles(1, 6)])
        e = ProviderTransientError("502")
        provider = ScriptedProvider([e, e, Completion(REPLY, 700, 300), e, e, Completion(REPLY, 700, 300)])
        result = _kx(ds, provider=provider).extract_all()
        assert result.attempted == 6 and result.stopped is None and result.processed == 2

    def test_a_daily_quota_stops_at_once(self):
        ds = _ds([_articles(1, 10)])
        provider = ScriptedProvider([ProviderQuotaExhausted("429", "PerDay")] * 10)
        result = _kx(ds, provider=provider).extract_all()
        assert result.attempted == 1 and "provider quota exhausted (PerDay)" in result.stopped

    def test_no_provider_does_nothing(self):
        kx = _kx(_ds([]))
        kx._provider = None
        assert kx.extract_all() == 0
