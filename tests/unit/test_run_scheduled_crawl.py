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
    # An exclusion is exercised with an explicit list: VIVA's own (SRC-33) ended
    # 2026-09-26, and the mechanism must keep working for the next one.
    EXCLUDED = {"VIVA": "SRC-00 (#0) example -- a source under an open ticket"}

    def test_an_excluded_source_is_skipped_with_its_reason(self):
        sources, skipped = rc._scheduled_sources(HEALTHY, excluded=self.EXCLUDED)
        assert "VIVA" not in sources
        assert "VIVA" in skipped and "#0" in skipped["VIVA"]

    def test_everything_else_is_scheduled_in_order(self):
        sources, _ = rc._scheduled_sources(HEALTHY, excluded=self.EXCLUDED)
        assert sources == ["ANTARANEWS", "CNBC", "KOMPAS", "WARTAEKONOMI"]

    def test_an_override_still_cannot_smuggle_an_excluded_source_in(self):
        """--website is an operator convenience, not a way past an exclusion."""
        sources, skipped = rc._scheduled_sources(HEALTHY, website_override="KOMPAS,VIVA", excluded=self.EXCLUDED)
        assert sources == ["KOMPAS"] and "VIVA" in skipped

    def test_viva_is_scheduled_now_that_src33_landed(self):
        sources, skipped = rc._scheduled_sources(HEALTHY)
        assert "VIVA" in sources and skipped == {}

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
    """run_one is a thin guard over SourceWorker.run; the process behaviour itself
    (the timeout frees the caller, the killed source stops writing) is
    tests/unit/test_source_worker.py, against real child processes."""

    class _Worker:
        def __init__(self, result=None, exc=None):
            self.result, self.exc = result, exc

        def run(self, website, task, timeout):
            if self.exc:
                raise self.exc
            return self.result

    def test_passes_the_worker_result_through(self):
        assert rc.run_one(self._Worker(("ok", "")), "KOMPAS", "sitemap") == ("ok", "")
        assert rc.run_one(self._Worker(("timeout", "x")), "TEMPO", "sitemap", timeout=1) == ("timeout", "x")

    def test_a_worker_error_is_a_failed_source_not_a_crashed_run(self):
        status, detail = rc.run_one(self._Worker(exc=OSError("pipe closed")), "KOMPAS", "sitemap")
        assert status == "failed" and "OSError" in detail and "pipe closed" in detail


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeClient:
    def get_session(self):
        return _FakeSession()


class _ScriptedWorker:
    """Plays back per-source outcomes. `alive` goes False after a timeout or a
    death, the way SourceWorker's does once it has killed or reaped the child."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []
        self.alive = False
        self.spawned = 0
        self.closed = False

    def start(self):
        self.alive = True
        self.spawned += 1

    def run(self, website, task, timeout):
        if not self.alive:
            self.start()
        self.calls.append((website, task))
        status, detail = self.outcomes.get((website, task), ("ok", ""))
        if status == "timeout" or "died" in detail:
            self.alive = False
        return status, detail

    def close(self):
        self.closed = True
        self.alive = False


@pytest.fixture
def harness(monkeypatch):
    """_run with every DB, model and Telegram touch replaced; returns what it saw."""
    import newscrawler.infrastructure.network.clients.sqlalchemy_client as sac
    seen = {"closed_rows": [], "notified": []}
    monkeypatch.setattr(sac, "SQLAlchemyClient", _FakeClient)
    monkeypatch.setattr(rc, "_healthy_list", lambda: ["KOMPAS", "TEMPO", "CNBC"])
    monkeypatch.setattr(rc, "_counts", lambda session: {})
    monkeypatch.setattr(rc, "zero_save_sources", lambda session: [])
    monkeypatch.setattr(rc, "hours_since_last_crawl", lambda session: 1.0)
    monkeypatch.setattr(rc, "db_now", lambda session: "T0")
    monkeypatch.setattr(rc, "_close_abandoned_log_rows",
                        lambda session, w, t, since, reason: seen["closed_rows"].append((w, t, since, reason)) or 1)
    monkeypatch.setattr(rc, "_notify", seen["notified"].append)

    def run(outcomes=None, argv=("--phase", "sitemap"), worker=None):
        worker = worker or _ScriptedWorker(outcomes or {})
        monkeypatch.setattr(rc, "_make_worker", lambda: worker)
        seen["rc"] = rc.main(list(argv))
        seen["worker"] = worker
        return seen
    return run


class TestRunLoop:
    def test_a_timed_out_source_does_not_stop_the_next_and_its_log_row_is_closed(self, harness):
        seen = harness({("TEMPO", "sitemap"): ("timeout", "exceeded 900s; worker process killed")})
        assert seen["worker"].calls == [("KOMPAS", "sitemap"), ("TEMPO", "sitemap"), ("CNBC", "sitemap")]
        assert seen["closed_rows"] == [("TEMPO", "sitemap", "T0", "exceeded 900s; worker process killed")]
        assert seen["rc"] == 1
        assert "FAILED: TEMPO" in seen["notified"][-1]
        assert seen["worker"].closed

    def test_a_plain_failure_leaves_the_log_row_to_the_pipeline(self, harness):
        """The child survived and the pipeline's own log_crawl_failed closed the
        row; rewriting it would overwrite the real error."""
        seen = harness({("TEMPO", "sitemap"): ("failed", "RuntimeError: boom")})
        assert seen["closed_rows"] == []
        assert seen["rc"] == 1

    def test_a_dead_child_is_closed_like_a_timeout(self, harness):
        seen = harness({("KOMPAS", "sitemap"): ("failed", "worker process died (exit code 7)")})
        assert [r[0] for r in seen["closed_rows"]] == ["KOMPAS"]

    def test_the_run_budget_skips_sources_instead_of_being_killed_silently(self, harness, monkeypatch):
        """Task Scheduler's 4 h kill sends nothing. A source is not started once it
        could run past the budget, and the skip is in the summary."""
        clock = iter([0, 0, 0, 5000, 5000, 5000, 5000]).__next__
        monkeypatch.setattr(rc.time, "monotonic", lambda: clock())
        monkeypatch.setattr(rc, "RUN_BUDGET", 5000)
        seen = harness(argv=("--phase", "sitemap", "--timeout", "900"))
        assert seen["worker"].calls == [("KOMPAS", "sitemap")]
        assert "TEMPO/sitemap" in seen["notified"][-1] and "CNBC/sitemap" in seen["notified"][-1]

    def test_the_worker_is_closed_even_when_the_loop_raises(self, harness, monkeypatch):
        def boom(session):
            raise RuntimeError("db gone")
        monkeypatch.setattr(rc, "db_now", boom)
        seen = harness()
        assert seen["rc"] == 1 and seen["worker"].closed
        assert "FAILED to start or complete" in seen["notified"][-1] and "db gone" in seen["notified"][-1]


class TestOverBudget:
    def test_boundaries(self):
        assert not rc.over_budget(0, 900, budget=900)
        assert rc.over_budget(1, 900, budget=900)

    def test_default_budget_leaves_room_under_the_4h_task_limit(self):
        assert rc.RUN_BUDGET + rc.SOURCE_TIMEOUT < 4 * 3600


class TestStartFailureIsReported:
    """A crawler that cannot start (missing probe artifact, corrupt FAISS, OOM)
    fails before any source runs; without main()'s catch the operator got no
    message at all -- only a non-zero exit in Task Scheduler history."""

    def test_notifies_and_exits_1(self, harness, monkeypatch):
        from newscrawler.tools.source_worker import WorkerInitError

        class _Unstartable(_ScriptedWorker):
            def start(self):
                raise WorkerInitError("FileNotFoundError: importance_probe.npz")
        seen = harness(worker=_Unstartable({}))
        assert seen["rc"] == 1 and seen["worker"].calls == []
        assert "FAILED to start or complete" in seen["notified"][-1]
        assert "importance_probe.npz" in seen["notified"][-1]


class TestGapCheck:
    class _Session:
        def __init__(self, value):
            self.value = value

        def execute(self, *a, **k):
            value = self.value

            class _R:
                def scalar(self_inner):
                    return value
            return _R()

    def test_never_crawled_is_none(self):
        assert rc.hours_since_last_crawl(self._Session(None)) is None

    def test_a_naive_utc_timestamp_is_read_as_utc(self):
        from datetime import datetime, timedelta, timezone
        naive = (datetime.now(timezone.utc) - timedelta(hours=40)).replace(tzinfo=None)
        assert rc.hours_since_last_crawl(self._Session(naive)) == pytest.approx(40, abs=0.1)

    def test_a_gap_past_the_threshold_notifies(self, harness, monkeypatch):
        monkeypatch.setattr(rc, "hours_since_last_crawl", lambda session: rc.GAP_ALERT_HOURS + 12.0)
        seen = harness()
        assert any(m.startswith("Scheduled crawl gap:") for m in seen["notified"])

    def test_within_the_threshold_is_silent(self, harness):
        seen = harness()
        assert not any(m.startswith("Scheduled crawl gap:") for m in seen["notified"])


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
            ["TVONENEWS"], {},
        )
        assert "0 saved for %d runs: TVONENEWS" % rc.ZERO_SAVE_RUNS_BEFORE_ALERT in line

    def test_skipped_sources_are_reported(self):
        line = rc.summary_line(self._phases({"KOMPAS": "ok"}), {"KOMPAS": {"sitemaps": 1, "articles": 1}},
                               [], {"VIVA": "SRC-00 (#0) -- example"})
        assert "skipped: VIVA (SRC-00 (#0))" in line


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
        s = self._Session([self._row("TVONENEWS", 0) for _ in range(3)])
        assert rc.zero_save_sources(s) == ["TVONENEWS"]

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


class TestWebsiteNamesAreValidatedFirst:
    """OPS-24 (#167): a typo is a config error, caught before the DB, the ~2 min
    crawler build, or any crawl_log row -- and it fails the run by name."""

    def test_a_typo_in_website_exits_1_naming_it_without_building_the_crawler(self, harness):
        seen = harness(argv=("--website", "KOMPASS", "--phase", "sitemap"))
        assert seen["rc"] == 1
        assert seen["worker"].spawned == 0 and seen["worker"].calls == []
        assert "KOMPASS" in seen["notified"][-1] and "FAILED to start" in seen["notified"][-1]

    def test_a_typo_in_healthy_is_caught_the_same_way(self, harness, monkeypatch):
        monkeypatch.setattr(rc, "_healthy_list", lambda: ["KOMPAS", "CNBCC"])
        seen = harness()
        assert seen["rc"] == 1 and seen["worker"].spawned == 0
        assert "CNBCC" in seen["notified"][-1] and "KOMPAS," not in seen["notified"][-1]

    def test_every_bad_name_is_listed_not_just_the_first(self):
        with pytest.raises(ValueError, match="KOMPASS, TEMPOO"):
            rc.validate_sources(["KOMPASS", "CNBC", "TEMPOO"])

    def test_dry_run_catches_it_too_and_does_not_notify(self, harness):
        """A dry run is how an operator checks a config change, so it must fail on
        a typo; it must not page anyone for it."""
        seen = harness(argv=("--website", "KOMPASS", "--dry-run"))
        assert seen["rc"] == 1 and seen["notified"] == []

    def test_known_names_pass(self):
        rc.validate_sources(["KOMPAS", "CNBC", "DETIK"])

    def test_the_scheduled_list_itself_is_valid(self):
        """The real HEALTHY list, as the scheduler will read it."""
        sources, _ = rc._scheduled_sources(rc._healthy_list())
        rc.validate_sources(sources)
