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
