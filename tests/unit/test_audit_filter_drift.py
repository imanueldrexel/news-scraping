"""OPS-18 (#123): the weekly filter-drift audit's sampling, agreement math and
alert thresholds, offline (no DB, no LLM)."""
import importlib.util
import os
import random
import sys

import pytest

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "scripts", "audit_filter_drift.py")


def _load():
    spec = importlib.util.spec_from_file_location("audit_filter_drift", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved, sys.argv = sys.argv, ["audit_filter_drift.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


audit = _load()


def _row(i, source="KOMPAS", category="news", status="saved", live=True, judge=True, topic="markets", jtopic="markets"):
    return {"sitemap_id": i, "source": source, "category": category, "crawl_status": status, "headline": f"h{i}",
            "live_news": live, "judge_news": judge, "topic": topic, "judge_topic": jtopic}


class TestSampling:
    def test_one_big_source_cannot_fill_the_sample(self):
        rows = [_row(i, "DETIK") for i in range(500)] + [_row(1000 + i, "TIRTO") for i in range(5)]
        sample = audit.spread_sample(rows, 20, random.Random(1))
        assert len(sample) == 20
        assert sum(r["source"] == "TIRTO" for r in sample) == 5

    def test_the_sample_is_reproducible_for_a_seed(self):
        rows = [_row(i, s) for i, s in enumerate(["A", "B", "C"] * 50)]
        a = [r["sitemap_id"] for r in audit.spread_sample(rows, 30, random.Random(7))]
        b = [r["sitemap_id"] for r in audit.spread_sample(rows, 30, random.Random(7))]
        assert a == b

    def test_category_denied_rejects_are_not_the_probes_decision(self):
        rows = [_row(1, "DETIK", "news", "saved"), _row(2, "DETIK", "sport", "rejected_filter"),
                _row(3, "DETIK", "news", "rejected_filter")]
        saved, rejected = audit.split_decisions(rows)
        assert [r["sitemap_id"] for r in saved] == [1]
        assert [r["sitemap_id"] for r in rejected] == [3]


class TestAgreement:
    def test_rates_per_side_and_topic(self):
        judged = ([_row(i) for i in range(9)] + [_row(9, judge=False)]                       # saves: 9/10 agree
                  + [_row(10 + i, status="rejected_filter", live=False, judge=False) for i in range(4)]
                  + [_row(20, status="rejected_filter", live=False, judge=True)]              # rejects: 4/5
                  + [_row(21, jtopic="law_crime")])                                             # topic miss
        s = audit.agreement(judged)
        assert s["n_saved"] == 11 and s["n_rejected"] == 5
        assert s["agree_saved"] == pytest.approx(10 / 11)
        assert s["agree_rejected"] == pytest.approx(0.8)
        assert s["topic_agreement"] == pytest.approx(9 / 10)

    def test_cells_are_source_by_category(self):
        s = audit.agreement([_row(1, "A", "News"), _row(2, "A", "news", judge=False), _row(3, "B", "x")])
        assert s["cells"]["A/news"] == {"n": 2, "agreement": 0.5}


class TestAlerts:
    def _summary(self, saved=0.95, rejected=0.95, cells=None):
        return {"agree_saved": saved, "agree_rejected": rejected, "cells": cells or {}}

    def test_healthy_week_no_alert(self):
        assert audit.alerts(self._summary()) == []

    def test_the_first_weeks_baseline_does_not_alert(self):
        """2026-09-29, a healthy filter: saved 0.87, rejected 0.78."""
        assert audit.alerts(self._summary(saved=0.87, rejected=0.78)) == []

    def test_a_side_below_its_floor_alerts(self):
        found = audit.alerts(self._summary(rejected=0.65))
        assert [a["key"] for a in found] == ["side:rejected"] and found[0]["new"]

    def test_a_cell_alerts_only_with_enough_decisions(self):
        cells = {"IDNTIMES/hype": {"n": 25, "agreement": 0.6}, "TIRTO/bisnis": {"n": 5, "agreement": 0.0}}
        assert [a["key"] for a in audit.alerts(self._summary(cells=cells))] == ["cell:IDNTIMES/hype"]

    def test_a_deliberately_broken_filter_is_caught(self):
        """The Done-when's broken-threshold run, offline: a filter that saves
        everything makes the judge disagree with most saves."""
        judged = [_row(i, "IDNTIMES", "hype", judge=(i % 4 == 0)) for i in range(40)]
        found = audit.alerts(audit.agreement(judged))
        assert {a["key"] for a in found} == {"side:saved", "cell:IDNTIMES/hype"}
        assert "IDNTIMES/hype" in audit.alert_message(audit.agreement(judged), found, judged)

    def test_an_alert_seen_last_week_is_not_new(self):
        found = audit.alerts(self._summary(saved=0.5), previous={"alert_keys": ["side:saved"]})
        assert found[0]["new"] is False


class TestSchedule:
    def _wrapper(self):
        path = os.path.join(os.path.dirname(_SCRIPT), "run_scheduled_health_check.py")
        spec = importlib.util.spec_from_file_location("rshc_ops18", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_due_once_a_week_on_the_configured_day(self, monkeypatch):
        from datetime import date, timedelta
        w = self._wrapper()
        monkeypatch.setattr(w, "FILTER_AUDIT_WEEKDAY", 0)
        week = [date(2026, 9, 28) + timedelta(days=i) for i in range(7)]   # Mon..Sun
        assert [w.filter_audit_due(d) for d in week] == [True] + [False] * 6
        monkeypatch.setattr(w, "FILTER_AUDIT_WEEKDAY", -1)
        assert not any(w.filter_audit_due(d) for d in week)


# ── OPS-37 (#210): the audit never fails silently ───────────────────────────

import types
from unittest.mock import MagicMock


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """main() with no DB and no LLM: 40 saved + 40 probe-rejected decisions,
    a recording crawl_log, a recording Telegram send."""
    rows = ([dict(sitemap_id=i, source=f"S{i % 4}", category="news", headline=f"h{i}", crawl_status="saved",
                  body_head="b", topic="markets") for i in range(40)]
            + [dict(sitemap_id=100 + i, source=f"S{i % 4}", category="news", headline=f"r{i}",
                    crawl_status="rejected_filter", body_head="", topic=None) for i in range(40)])
    monkeypatch.setattr(audit, "load_decisions", lambda days: [dict(r) for r in rows])
    monkeypatch.setattr(audit, "REPORT_DIR", str(tmp_path / "rep"))
    log = MagicMock()
    log.log_crawl_start.return_value = 7
    import newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source as ads
    import newscrawler.infrastructure.network.clients.sqlalchemy_client as client
    monkeypatch.setattr(ads, "SQLAlchemyArticleDataSource", lambda *a, **k: log)
    monkeypatch.setattr(client, "SQLAlchemyClient", lambda *a, **k: None)
    sent = []
    monkeypatch.setitem(sys.modules, "notify_telegram", types.SimpleNamespace(send=lambda msg, **k: sent.append(msg)))
    lfg = types.SimpleNamespace(make_labeller=lambda provider: (object(), "stub-model"))
    monkeypatch.setattr(audit, "labeller_module", lambda: lfg)
    return types.SimpleNamespace(log=log, sent=sent, lfg=lfg)


def _judge_all(agree_saved, agree_rejected):
    """A judge that agrees with the first `agree_*` share of each side."""
    def judge(lfg, labeller, rows):
        out, seen = [], {True: 0, False: 0}
        for r in rows:
            side = r["live_news"]
            n = sum(1 for x in rows if x["live_news"] is side)
            share = agree_saved if side else agree_rejected
            agrees = seen[side] < share * n
            seen[side] += 1
            r["judge_news"] = side if agrees else (not side)
            r["judge_topic"] = r.get("topic")
            out.append(r)
        return out, 4
    return judge


class TestNeverSilent:
    def test_a_labeller_that_judges_nothing_is_a_failed_audit(self, stubbed, monkeypatch):
        monkeypatch.setattr(audit, "judge", lambda lfg, labeller, rows: ([], 4))
        assert audit.main([]) == 1
        stubbed.log.log_crawl_complete.assert_not_called()
        msg = stubbed.log.log_crawl_failed.call_args.args[1]
        assert "judged only 0 of 40 saved rows" in msg and "judged only 0 of 40 rejected rows" in msg

    def test_a_missing_key_still_closes_the_crawl_log_row(self, stubbed):
        def no_key(provider):
            raise SystemExit("OPENAI_API_KEY is not set")
        stubbed.lfg.make_labeller = no_key
        with pytest.raises(SystemExit):
            audit.main([])
        stubbed.log.log_crawl_failed.assert_called_once()
        assert "OPENAI_API_KEY is not set" in stubbed.log.log_crawl_failed.call_args.args[1]

    def test_a_shortfall_on_one_side_fails_too(self):
        sample = [{"live_news": True}] * 10 + [{"live_news": False}] * 10
        judged = [{"live_news": True}] * 10 + [{"live_news": False}] * 4
        assert audit.judged_shortfall(sample, judged) == "judged only 4 of 10 rejected rows"
        assert audit.judged_shortfall(sample, sample) is None


class TestTheAlertIsSent:
    """OPS-18 (#123) send-back item 2: main itself sends the alert it computes."""

    def test_agreement_below_a_floor_sends_one_alert(self, stubbed, monkeypatch):
        monkeypatch.setattr(audit, "judge", _judge_all(0.5, 0.9))
        assert audit.main([]) == 0
        assert len(stubbed.sent) == 1 and "agreement on saved" in stubbed.sent[0]
        stubbed.log.log_crawl_complete.assert_called_once()

    def test_a_healthy_week_sends_nothing(self, stubbed, monkeypatch):
        monkeypatch.setattr(audit, "judge", _judge_all(0.95, 0.95))
        assert audit.main([]) == 0
        assert stubbed.sent == []

    def test_the_window_is_passed_to_the_query(self, monkeypatch):
        seen = {}

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params):
                seen.update(params)
                return []

        import newscrawler.infrastructure.network.clients.sqlalchemy_client as client
        monkeypatch.setattr(client, "SQLAlchemyClient", lambda: types.SimpleNamespace(get_session=Session))
        audit.load_decisions(3)
        assert seen["days"] == 3
        assert "make_interval(days => :days)" in str(audit._DECISIONS_SQL)

    def test_two_seeds_draw_different_samples(self):
        rows = [_row(i, f"S{i % 3}") for i in range(300)]
        a = audit.spread_sample(rows, 30, random.Random(1))
        b = audit.spread_sample(rows, 30, random.Random(2))
        assert {r["sitemap_id"] for r in a} != {r["sitemap_id"] for r in b}


class TestHealthCheckRelaysAFailedAudit:
    def _wrapper(self, monkeypatch, sent):
        path = os.path.join(os.path.dirname(_SCRIPT), "run_scheduled_health_check.py")
        spec = importlib.util.spec_from_file_location("rshc_ops37", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setitem(sys.modules, "notify_telegram", types.SimpleNamespace(send=sent.append))
        return mod

    @pytest.mark.parametrize("rc", [1, 2])
    def test_a_non_zero_exit_is_one_alert(self, monkeypatch, rc):
        sent = []
        w = self._wrapper(monkeypatch, sent)
        monkeypatch.setattr(w.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
            returncode=rc, stdout="", stderr="SystemExit: OPENAI_API_KEY is not set"))
        assert w.run_filter_audit() == rc
        assert len(sent) == 1 and "FAILED" in sent[0] and "OPENAI_API_KEY" in sent[0]

    def test_a_clean_exit_sends_nothing(self, monkeypatch):
        sent = []
        w = self._wrapper(monkeypatch, sent)
        monkeypatch.setattr(w.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="ok",
                                                                                      stderr=""))
        assert w.run_filter_audit() == 0 and sent == []

    def test_a_hung_audit_is_stopped_and_alerted(self, monkeypatch):
        sent = []
        w = self._wrapper(monkeypatch, sent)

        def hang(*a, **k):
            assert k["timeout"] == w.FILTER_AUDIT_TIMEOUT_S
            raise w.subprocess.TimeoutExpired(cmd="audit", timeout=k["timeout"])
        monkeypatch.setattr(w.subprocess, "run", hang)
        assert w.run_filter_audit() == -1
        assert len(sent) == 1 and "FILTER_AUDIT_TIMEOUT_S" in sent[0]
