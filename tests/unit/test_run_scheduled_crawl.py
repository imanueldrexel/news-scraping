"""OPS-19 (#132): the scheduled crawl wrapper's decisions, offline.

Everything here is the part that decides WHAT runs and what the operator is told.
The crawl itself is the pipeline's; this file guards the schedule's judgement --
including the one rule that is not a preference: VIVA must not be crawled while
SRC-33 (#119) is open.
"""
import importlib.util
import os
import sys

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "run_scheduled_crawl.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("run_scheduled_crawl", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["run_scheduled_crawl.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


rc = _load()

HEALTHY = ["ANTARANEWS", "CNBC", "KOMPAS", "VIVA", "WARTAEKONOMI"]


class TestScheduledSources:
    def test_viva_is_excluded_with_its_reason(self):
        """Standing hard rule, not a preference: SRC-33 (#119) is open, VIVA still
        keeps all 53 branches, and one crawl adds ~53k rows onto a 39k backlog
        that is 97.8% non-finance."""
        sources, skipped = rc._scheduled_sources(HEALTHY)
        assert "VIVA" not in sources
        assert "VIVA" in skipped and "SRC-33" in skipped["VIVA"]

    def test_everything_else_is_scheduled_in_order(self):
        sources, _ = rc._scheduled_sources(HEALTHY)
        assert sources == ["ANTARANEWS", "CNBC", "KOMPAS", "WARTAEKONOMI"]

    def test_an_override_still_cannot_smuggle_viva_in(self):
        """--website is an operator convenience, not a way past the hard rule."""
        sources, skipped = rc._scheduled_sources(HEALTHY, website_override="KOMPAS,VIVA")
        assert sources == ["KOMPAS"] and "VIVA" in skipped

    def test_the_override_is_normalised(self):
        sources, _ = rc._scheduled_sources(HEALTHY, website_override=" kompas , cnbc ")
        assert sources == ["KOMPAS", "CNBC"]

    def test_the_exclusion_list_is_documented_per_source(self):
        for name, why in rc.DEFAULT_EXCLUDED.items():
            assert "#" in why, "every exclusion cites the ticket that justifies it: %s" % name


class TestFullTextSelection:
    def test_unset_means_every_scheduled_source(self, monkeypatch):
        """SYS-37 landed 2026-09-22, so the gate this variable enforced is gone --
        unset now means all, and it stays the way to stage a source listing-only."""
        monkeypatch.delenv("SCHEDULE_FULL_TEXT_WEBSITES", raising=False)
        assert rc.full_text_sources(["KOMPAS", "CNBC"]) == ["KOMPAS", "CNBC"]

    def test_a_list_limits_it_and_preserves_order(self, monkeypatch):
        monkeypatch.setenv("SCHEDULE_FULL_TEXT_WEBSITES", "cnbc")
        assert rc.full_text_sources(["KOMPAS", "CNBC"]) == ["CNBC"]

    def test_an_unscheduled_name_in_the_list_is_ignored(self, monkeypatch):
        monkeypatch.setenv("SCHEDULE_FULL_TEXT_WEBSITES", "VIVA,KOMPAS")
        assert rc.full_text_sources(["KOMPAS", "CNBC"]) == ["KOMPAS"]


class TestRunOne:
    def test_ok(self):
        class _Api:
            def crawl_website(self, w, t): return None
        assert rc.run_one(_Api(), "KOMPAS", "sitemap") == ("ok", "")

    def test_a_failure_is_recorded_and_does_not_raise(self):
        class _Api:
            def crawl_website(self, w, t): raise RuntimeError("boom")
        status, detail = rc.run_one(_Api(), "KOMPAS", "sitemap")
        assert status == "failed" and "RuntimeError" in detail and "boom" in detail

    def test_a_hung_source_times_out_instead_of_eating_the_window(self):
        import time

        class _Api:
            def crawl_website(self, w, t): time.sleep(5)
        status, detail = rc.run_one(_Api(), "TEMPO", "sitemap", timeout=0.3)
        assert status == "timeout" and "0s" in detail or "exceeded" in detail


class TestSummaryLine:
    def _phases(self, statuses):
        return {"sitemap": {s: (st, "") for s, st in statuses.items()}}

    def test_counts_first(self):
        line = rc.summary_line(
            self._phases({"KOMPAS": "ok", "CNBC": "ok"}),
            {"KOMPAS": {"sitemaps": 100, "articles": 20}, "CNBC": {"sitemaps": 50, "articles": 5}},
            [], {},
        )
        assert line.startswith("2 sources, +150 sitemaps, +25 articles, 0 with 0 saved")

    def test_failures_are_named(self):
        line = rc.summary_line(
            self._phases({"KOMPAS": "ok", "TEMPO": "timeout"}),
            {"KOMPAS": {"sitemaps": 1, "articles": 1}, "TEMPO": {"sitemaps": 0, "articles": 0}},
            [], {},
        )
        assert "FAILED: TEMPO" in line and "1 with 0 saved" in line

    def test_a_persistent_zero_saver_is_called_out(self):
        line = rc.summary_line(
            self._phases({"KOMPAS": "ok"}), {"KOMPAS": {"sitemaps": 10, "articles": 0}},
            ["GRIDID"], {},
        )
        assert "0 saved for %d runs: GRIDID" % rc.ZERO_SAVE_RUNS_BEFORE_ALERT in line

    def test_skipped_sources_are_reported(self):
        line = rc.summary_line(self._phases({"KOMPAS": "ok"}), {"KOMPAS": {"sitemaps": 1, "articles": 1}},
                               [], rc.DEFAULT_EXCLUDED)
        assert "skipped: VIVA" in line


class TestZeroSaveWindow:
    """The alert must describe the last few days, not the last few rows.

    The first live run of this wrapper flagged EMITENNEWS and WARTAEKONOMI from
    `full_text` rows dated 2026-06-02 -- and WARTAEKONOMI holds 2,695 articles.
    Verified against the live DB at the time: 0 flagged within 7 days, both
    flagged with the window widened to 3650.
    """

    class _Session:
        def __init__(self, rows):
            self.rows = rows
            self.params = None

        def execute(self, statement, params=None):
            self.params = params
            assert "within_days" in str(statement), "the query must be time-bounded"
            rows = self.rows

            class _Result:
                def fetchall(self_inner):
                    return rows

            return _Result()

    def _row(self, website, count):
        from types import SimpleNamespace
        return SimpleNamespace(website=website, article_count=count)

    def test_a_source_with_three_zero_runs_is_flagged(self):
        s = self._Session([self._row("GRIDID", 0) for _ in range(3)])
        assert rc.zero_save_sources(s) == ["GRIDID"]

    def test_one_non_zero_run_clears_it(self):
        s = self._Session([self._row("KOMPAS", 0), self._row("KOMPAS", 5), self._row("KOMPAS", 0)])
        assert rc.zero_save_sources(s) == []

    def test_too_few_runs_in_the_window_is_not_evidence(self):
        s = self._Session([self._row("EMITENNEWS", 0)])
        assert rc.zero_save_sources(s) == []

    def test_the_window_is_passed_to_the_query(self):
        s = self._Session([])
        rc.zero_save_sources(s, within_days=14)
        assert s.params["within_days"] == 14 and s.params["runs"] == rc.ZERO_SAVE_RUNS_BEFORE_ALERT

    def test_null_article_count_counts_as_zero(self):
        s = self._Session([self._row("X", None) for _ in range(3)])
        assert rc.zero_save_sources(s) == ["X"]
