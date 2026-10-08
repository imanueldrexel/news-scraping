"""SYS-94 (#263) / SYS-98 (#267) / SYS-99 (#268), ADR-005: the answer is a state, never an
error as text; it goes through the shared Summarizer; its usage is counted under
`web:<model>` with tokens and dollars and bounded by the page's own daily cap; no
relevant article means no model call."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import newscrawler.web.query_processor as qp_mod
from newscrawler.core.summarizer import QuotaExhausted, Reply, SummarizerError
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import ApiUsage
from newscrawler.web.query_processor import FAILED, NO_HITS, OK, UNAVAILABLE, QueryProcessor

TODAY = date(2026, 10, 7)
HITS = [{"n": 1, "sitemap_id": 1, "source": "KONTAN", "posted_date": date(2026, 10, 5), "title": "Rupiah Melemah",
         "text_content": "Rupiah ditutup di Rp16.420 per dolar AS.", "link": "https://kontan.co.id/a"},
        {"n": 2, "sitemap_id": 2, "source": "CNBC", "posted_date": date(2026, 10, 2), "title": "Asing Jual",
         "text_content": "Asing jual bersih Rp1,2 triliun.", "link": "https://cnbcindonesia.com/b"}]


class FakeSummarizer:
    def __init__(self, reply=None, error=None, priced=True, name="deepseek-test"):
        self.name, self.priced = name, priced
        self.reply, self.error = reply, error
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply


def _usage(spent=0.0):
    usage = MagicMock()
    usage.get_today_api_usage.return_value = ApiUsage(0, 0, 0, spent)
    return usage


def _qp(summarizer, usage=None):
    return QueryProcessor(MagicMock(), MagicMock(), summarizer=summarizer, usage=usage or _usage())


class TestStates:
    def test_no_hits_makes_no_model_call(self):
        fake = FakeSummarizer(Reply("x"))
        result = _qp(fake).answer("q", [], [], TODAY)
        assert result.status == NO_HITS and fake.prompts == []

    def test_no_provider_is_unavailable(self):
        assert _qp(None).answer("q", HITS, [], TODAY).status == UNAVAILABLE

    def test_a_daily_quota_is_unavailable_and_not_counted(self, caplog):
        usage = _usage()
        fake = FakeSummarizer(error=QuotaExhausted("429 RESOURCE_EXHAUSTED quotaId PerDay", "PerDay"))
        result = _qp(fake, usage).answer("q", HITS, [], TODAY)
        assert result.status == UNAVAILABLE and result.text == ""
        usage.increment_api_call_count.assert_not_called()
        assert any("daily quota" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("error", [SummarizerError("ConnectTimeout: secret detail"), RuntimeError("boom")])
    def test_a_failed_call_is_failed_with_no_error_text(self, error, caplog):
        result = _qp(FakeSummarizer(error=error)).answer("q", HITS, [], TODAY)
        assert result.status == FAILED and result.text == "" and result.blocks == []
        assert any(str(error) in r.getMessage() for r in caplog.records), "the exception belongs in the log"

    def test_an_empty_reply_is_failed_but_was_paid_for(self):
        usage = _usage()
        result = _qp(FakeSummarizer(Reply("  ", 900, 0)), usage).answer("q", HITS, [], TODAY)
        assert result.status == FAILED
        usage.increment_api_call_count.assert_called_once()

    def test_ok_answer_is_parsed_with_citations(self):
        fake = FakeSummarizer(Reply("Rupiah ditutup di Rp16.420 [1].\n- Asing jual Rp1,2 triliun [2]", 1000, 80))
        result = _qp(fake).answer("Kenapa rupiah melemah?", HITS, [], TODAY)
        assert result.status == OK and result.unverified is None
        assert [b.kind for b in result.blocks] == ["p", "ul"]
        assert "Hari ini Rabu, 7 Oktober 2026." in fake.prompts[0]

    def test_a_number_the_articles_lack_is_flagged(self):
        fake = FakeSummarizer(Reply("Rupiah ditutup di Rp16.500 [1].", 1000, 80))
        assert _qp(fake).answer("q", HITS, [], TODAY).unverified == "16.500"


class TestUsage:
    def test_counted_under_its_own_key_with_tokens_and_dollars(self, monkeypatch):
        monkeypatch.setattr(qp_mod, "is_peak", lambda: False)
        usage = _usage()
        _qp(FakeSummarizer(Reply("Jawaban [1].", 2000, 200)), usage).answer("q", HITS, [], TODAY)
        usage.increment_api_call_count.assert_called_once()
        args, kwargs = usage.increment_api_call_count.call_args
        assert args == ("web:deepseek-test",)
        assert kwargs["input_tokens"] == 2000 and kwargs["output_tokens"] == 200
        assert kwargs["cost_usd"] == pytest.approx(qp_mod.cost_usd(2000, 200, False))
        assert kwargs["cost_usd"] > 0

    def test_priced_at_the_peak_rate_in_the_peak_window(self, monkeypatch):
        """DBT-62: in DeepSeek's peak window the answer costs the peak price; priced off-peak at all
        hours, RAG_DAILY_COST_LIMIT_USD would under-count."""
        monkeypatch.setattr(qp_mod, "is_peak", lambda: True)
        usage = _usage()
        result = _qp(FakeSummarizer(Reply("Jawaban [1].", 2000, 200)), usage).answer("q", HITS, [], TODAY)
        assert qp_mod.cost_usd(2000, 200, True) != qp_mod.cost_usd(2000, 200, False)
        assert usage.increment_api_call_count.call_args.kwargs["cost_usd"] == pytest.approx(
            qp_mod.cost_usd(2000, 200, True))
        assert result.cost_usd == pytest.approx(qp_mod.cost_usd(2000, 200, True))

    def test_an_unpriced_provider_costs_nothing(self):
        usage = _usage()
        _qp(FakeSummarizer(Reply("Jawaban.", 2000, 200), priced=False, name="gemini-x"), usage).answer(
            "q", HITS, [], TODAY)
        args, kwargs = usage.increment_api_call_count.call_args
        assert args == ("web:gemini-x",) and kwargs["cost_usd"] == 0.0

    def test_the_daily_cap_stops_the_call(self, monkeypatch):
        monkeypatch.setattr(qp_mod, "RAG_DAILY_COST_LIMIT_USD", 1.0)
        usage = _usage(spent=1.0)
        fake = FakeSummarizer(Reply("x"))
        assert _qp(fake, usage).answer("q", HITS, [], TODAY).status == UNAVAILABLE
        assert fake.prompts == []
        usage.get_today_api_usage.assert_called_once_with("web:deepseek-test")

    def test_under_the_cap_answers(self, monkeypatch):
        monkeypatch.setattr(qp_mod, "RAG_DAILY_COST_LIMIT_USD", 1.0)
        assert _qp(FakeSummarizer(Reply("Jawaban.")), _usage(spent=0.99)).answer("q", HITS, [], TODAY).status == OK

    def test_an_unreadable_ledger_does_not_hide_answers(self):
        usage = _usage()
        usage.get_today_api_usage.side_effect = RuntimeError("db down")
        usage.increment_api_call_count.side_effect = RuntimeError("db down")
        assert _qp(FakeSummarizer(Reply("Jawaban.")), usage).answer("q", HITS, [], TODAY).status == OK


class TestProviderFromConfig:
    def test_rag_llm_provider_selects_the_summarizer(self, monkeypatch):
        seen = {}

        def fake_build(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(name="m", priced=True)
        monkeypatch.setattr(qp_mod, "build_summarizer", fake_build)
        monkeypatch.setattr(qp_mod, "RAG_LLM_PROVIDER", "openai")
        QueryProcessor(MagicMock(), MagicMock(), usage=MagicMock())
        assert seen["provider"] == "openai" and seen["setting"] == "RAG_LLM_PROVIDER"
        assert seen["timeout_s"] == qp_mod.RAG_ANSWER_TIMEOUT_S and "usage" not in seen, \
            "the summarizer must not count calls itself: the page counts them under web:<model>"

    def test_no_key_means_no_summarizer_and_a_warning(self, monkeypatch, caplog):
        monkeypatch.setattr(qp_mod, "build_summarizer", lambda **k: None)
        qp = QueryProcessor(MagicMock(), MagicMock(), usage=MagicMock())
        assert qp.summarizer is None
        assert any("without an AI answer" in r.getMessage() for r in caplog.records)


class TestJsonQuery:
    def test_shape_and_reader_names(self):
        qp = _qp(FakeSummarizer(Reply("Jawaban [1].")))
        qp.retrieve = lambda question, filters=None, today=None, history=(): [dict(h) for h in HITS]
        out = qp.query("q", [], today=TODAY)
        assert out["answer_status"] == OK and out["answer"] == "Jawaban [1]."
        assert out["numbers_unverified"] is False
        first = out["sources"][0]
        assert first["outlet"] == "Kontan" and first["date"] == "Senin, 5 Okt 2026"
        assert first["posted_date"] == "2026-10-05" and first["n"] == 1
