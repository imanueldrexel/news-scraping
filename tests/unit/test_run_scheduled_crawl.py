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
# The real exclusion list, read before any test isolates itself from it.
REAL_EXCLUDED = dict(rc.DEFAULT_EXCLUDED)


@pytest.fixture(autouse=True)
def _no_default_exclusions(monkeypatch):
    """The run-loop tests use real source names (TEMPO, CNBC, ...) as stand-ins;
    which sources the owner has paused must not change what they test. Tests of
    the exclusion list itself read REAL_EXCLUDED."""
    monkeypatch.setattr(rc, "DEFAULT_EXCLUDED", {})

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
        for name, why in REAL_EXCLUDED.items():
            assert "#" in why, "every exclusion cites the ticket that justifies it: %s" % name

    def test_tempo_is_paused_under_src56(self, monkeypatch):
        """Owner decision 2026-10-03: TEMPO (Cloudflare fingerprint block) is
        paused, not retired, until Tempo grants access."""
        monkeypatch.setattr(rc, "DEFAULT_EXCLUDED", REAL_EXCLUDED)
        sources, skipped = rc._scheduled_sources(["KOMPAS", "TEMPO"])
        assert sources == ["KOMPAS"] and "#205" in skipped["TEMPO"]


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

    def __init__(self, outcomes, on_run=None):
        self.outcomes = outcomes
        self.on_run = on_run
        self.calls = []
        self.timeouts = {}
        self.alive = False
        self.spawned = 0
        self.closed = False
        self.lock_holder_at_start = "not started"

    def start(self):
        from newscrawler.tools import run_lock
        self.lock_holder_at_start = run_lock.holder()
        self.alive = True
        self.spawned += 1

    def run(self, website, task, timeout):
        if not self.alive:
            self.start()
        self.calls.append((website, task))
        self.timeouts[website] = timeout
        if self.on_run:
            self.on_run(website, task)
        status, detail = self.outcomes.get((website, task), ("ok", ""))
        if status in ("timeout", "init_failed") or "worker process" in detail:
            self.alive = False
        return status, detail

    def close(self):
        self.closed = True
        self.alive = False


CLEAN_COUNTS = {"chunks_pending_embedding": 0, "chunks_not_in_faiss": 0}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """_run with every DB, model and Telegram touch replaced; returns what it saw.
    `seen["last_runs"]`, `seen["store"]` and `seen["pending"]` script the
    crawl_log history, the store check and the NULL-embedding query."""
    import newscrawler.infrastructure.network.clients.sqlalchemy_client as sac
    seen = {"closed_rows": [], "notified": [], "last_runs": {}, "store": (CLEAN_COUNTS, [], "r.json"),
            "pending": {}, "store_checks": 0}
    monkeypatch.setattr(sac, "SQLAlchemyClient", _FakeClient)
    monkeypatch.setattr(rc, "_healthy_list", lambda: ["KOMPAS", "TEMPO", "CNBC"])
    monkeypatch.setattr(rc, "_counts", lambda session: {})
    monkeypatch.setattr(rc, "zero_save_sources", lambda session: [])
    monkeypatch.setattr(rc, "hours_since_last_crawl", lambda session: 1.0)
    monkeypatch.setattr(rc, "db_now", lambda session: "T0")
    monkeypatch.setattr(rc, "_close_abandoned_log_rows",
                        lambda session, w, t, since, reason: seen["closed_rows"].append((w, t, since, reason)) or 1)
    monkeypatch.setattr(rc, "_notify", seen["notified"].append)
    monkeypatch.setattr(rc, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(rc, "last_full_text_runs", lambda session: dict(seen["last_runs"]))
    monkeypatch.setattr(rc, "null_embedding_by_source", lambda session: seen["pending"])

    def store_check():
        seen["store_checks"] += 1
        return seen["store"]
    monkeypatch.setattr(rc, "_store_check", store_check)

    def run(outcomes=None, argv=("--phase", "sitemap"), worker=None):
        worker = worker or _ScriptedWorker(outcomes or {})
        monkeypatch.setattr(rc, "_make_worker", lambda log_path=None: worker)
        seen["rc"] = rc.main(list(argv))
        seen["worker"] = worker
        return seen
    run.seen = seen
    return run


class TestRunLoop:
    def test_a_timed_out_source_does_not_stop_the_next_and_its_log_row_is_closed(self, harness):
        seen = harness({("TEMPO", "sitemap"): ("timeout", "exceeded 900s; worker process killed")})
        assert seen["worker"].calls == [("KOMPAS", "sitemap"), ("TEMPO", "sitemap"), ("CNBC", "sitemap")]
        assert seen["closed_rows"] == [("TEMPO", "sitemap", "T0",
                                        "killed by run_scheduled_crawl: exceeded 900s; worker process killed")]
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

    def test_a_crashed_child_is_not_said_to_be_killed_and_points_at_the_log(self, harness):
        """SYS-52 (#178): crawl_log row 710 read "killed by run_scheduled_crawl:
        worker process died (exit code 3221225477)". Nothing had killed it."""
        detail = "worker process crashed (exit code 3221225477 = 0xC0000005 access violation)"
        seen = harness({("KOMPAS", "sitemap"): ("failed", detail)})
        (website, _, _, reason), = seen["closed_rows"]
        assert website == "KOMPAS" and reason.startswith(detail)
        assert "killed" not in reason and "faulthandler" in reason and "scheduled_crawl_" in reason

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


class TestFailedStartsStopTheRun:
    """OPS-32 (#193): on 2026-09-27 the crawler could not be rebuilt after one
    timeout kill, and each of 27 sources then spent ~3.5 min failing to start."""

    CANNOT = ("init_failed", "crawler could not start: ConnectionError: huggingface.co getaddrinfo failed")

    def test_two_failed_starts_in_a_row_stop_the_run_with_one_clear_failure(self, harness):
        seen = harness({("KOMPAS", "sitemap"): self.CANNOT, ("TEMPO", "sitemap"): self.CANNOT},
                       argv=("--phase", "both"))
        assert seen["worker"].calls == [("KOMPAS", "sitemap"), ("TEMPO", "sitemap")]
        line = seen["notified"][-1]
        assert "STOPPED: the crawler could not start 2 times in a row (ConnectionError: huggingface.co" in line
        assert "4 source run(s) not started" in line      # CNBC/sitemap + the three full_text runs
        assert seen["rc"] == 1
        assert seen["closed_rows"] == [], "a source that never started opened no crawl_log row"

    def test_a_successful_start_in_between_resets_the_count(self, harness):
        seen = harness({("KOMPAS", "sitemap"): self.CANNOT, ("CNBC", "sitemap"): self.CANNOT})
        assert [c[0] for c in seen["worker"].calls] == ["KOMPAS", "TEMPO", "CNBC"]
        assert "STOPPED" not in seen["notified"][-1]
        assert "FAILED: CNBC, KOMPAS" in seen["notified"][-1]

    def test_a_source_failing_on_its_own_does_not_count(self, harness):
        seen = harness({("KOMPAS", "sitemap"): ("failed", "RuntimeError: boom"),
                        ("TEMPO", "sitemap"): ("failed", "RuntimeError: boom")})
        assert len(seen["worker"].calls) == 3 and "STOPPED" not in seen["notified"][-1]


class TestOverBudget:
    def test_boundaries(self):
        assert not rc.over_budget(0, 900, budget=900)
        assert rc.over_budget(1, 900, budget=900)

    def test_default_budget_leaves_room_under_the_4h_task_limit(self):
        assert rc.RUN_BUDGET + rc.SOURCE_TIMEOUT < 4 * 3600
        # A source starts only if it can finish inside the budget, so the
        # summary goes out before Task Scheduler's 4 h kill whatever its timeout.
        assert rc.RUN_BUDGET < 4 * 3600 - 600

    def test_the_default_timeouts_cover_a_capped_source_plus_one_burst(self):
        """OPS-28 (2026-09-28): DETIK took 583-624 s, then 885 of 900 s when a
        four-minute ConnectionError burst hit one batch (SYS-62)."""
        assert rc.SOURCE_TIMEOUT >= 624 + 300
        assert rc.timeout_for("MEDIAINDONESIA", rc.SOURCE_TIMEOUT) >= 947 + 300


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


class TestAbandonReason:
    def test_only_a_timeout_is_a_kill(self):
        assert rc.abandon_reason("timeout", "exceeded 900s; worker process killed") == \
            "killed by run_scheduled_crawl: exceeded 900s; worker process killed"
        assert rc.abandon_reason("failed", "worker process crashed (exit code 5)") == \
            "worker process crashed (exit code 5)"
        assert rc.abandon_reason("failed", "x", log_path="logs/a.log") == "x; stack (faulthandler) in logs/a.log"


class TestRunLock:
    """OPS-26 (#175): the lock covers the whole run, the model load included."""

    def test_the_lock_is_held_while_the_worker_starts_and_released_after(self, harness):
        from newscrawler.tools import run_lock
        seen = harness()
        assert seen["worker"].lock_holder_at_start is not None
        assert seen["worker"].lock_holder_at_start["pid"] == os.getpid()
        assert run_lock.holder() is None

    def test_the_lock_is_released_when_the_worker_cannot_start(self, harness):
        from newscrawler.tools import run_lock

        class _NoStart(_ScriptedWorker):
            def start(self):
                raise RuntimeError("probe artifact missing")
        seen = harness(worker=_NoStart({}))
        assert seen["rc"] == 1 and seen["worker"].closed
        assert run_lock.holder() is None

    def test_a_run_already_holding_the_lock_refuses_a_second_one(self, harness):
        import json
        from newscrawler.tools import run_lock
        with open(run_lock.LOCK_PATH, "w") as f:
            json.dump({"pid": os.getppid(), "started_at": "07:00"}, f)
        seen = harness()
        assert seen["rc"] == 1 and seen["worker"].calls == []
        assert seen["worker"].lock_holder_at_start == "not started", "the worker was started under a held lock"
        assert "RunLockHeld" in seen["notified"][-1]


class TestRunLog:
    """OPS-27 (#176): the run writes a log file, and says where it is."""

    def _log(self, tmp_path):
        logs = list((tmp_path / "logs").glob("scheduled_crawl_*.log"))
        assert len(logs) == 1
        return logs[0]

    def test_the_run_log_holds_the_per_source_lines_and_the_summary(self, harness, tmp_path):
        seen = harness({("TEMPO", "sitemap"): ("failed", "RuntimeError: boom")})
        text = self._log(tmp_path).read_text(encoding="utf-8")
        assert "[sitemap 2/3] TEMPO -> failed (RuntimeError: boom)" in text
        assert "SUMMARY:" in text
        assert "log %s" % self._log(tmp_path) in seen["notified"][-1]

    def test_the_handler_is_detached_after_the_run(self, harness, tmp_path):
        import logging
        harness()
        assert not [h for h in logging.getLogger().handlers
                    if getattr(h, "baseFilename", "").startswith(str(tmp_path))]

    def test_a_dry_run_writes_no_log(self, harness, tmp_path):
        harness(argv=("--dry-run",))
        assert not (tmp_path / "logs").exists()

    def test_old_logs_are_pruned_to_the_newest_keep(self, tmp_path):
        import logging
        for day in range(1, 6):
            (tmp_path / ("scheduled_crawl_2026-09-0%d_0700.log" % day)).write_text("x")
        path, handler = rc.open_run_log(str(tmp_path), keep=3)
        logging.getLogger().removeHandler(handler)
        handler.close()
        left = sorted(p.name for p in tmp_path.glob("scheduled_crawl_*.log"))
        assert os.path.basename(path) in left and len(left) == 3
        assert "scheduled_crawl_2026-09-05_0700.log" in left and "scheduled_crawl_2026-09-01_0700.log" not in left

    def test_a_child_exceptions_traceback_lands_in_the_run_log(self, harness, monkeypatch, tmp_path):
        """End to end through a real SourceWorker child (stub crawler): the
        child's traceback and the parent's SUMMARY end up in the same file."""
        from newscrawler.tools.source_worker import SourceWorker
        from . import sched_worker_stubs as stubs
        monkeypatch.setattr(rc, "_healthy_list", lambda: ["RAISE", "KOMPAS"])
        monkeypatch.setattr(rc, "validate_sources", lambda sources: None)  # RAISE is a stub name
        workers = []

        def make(log_path=None):
            workers.append(SourceWorker(factory=stubs.stub_factory, init_timeout=60, log_path=log_path))
            return workers[-1]
        monkeypatch.setattr(rc, "_make_worker", make)
        assert rc.main(["--phase", "sitemap"]) == 1
        text = self._log(tmp_path).read_text(encoding="utf-8")
        assert "RAISE/sitemap failed" in text and "Traceback (most recent call last)" in text
        assert "RuntimeError: boom" in text and "SUMMARY:" in text


class TestStoreCheck:
    """OPS-29 (#180): the store check runs after every scheduled run, and a
    crashed source's stranded vectors reach the Telegram line."""

    def test_every_run_checks_the_stores(self, harness):
        seen = harness()
        assert seen["store_checks"] == 1
        assert "vectors pending" not in seen["notified"][-1] and "STORE" not in seen["notified"][-1]

    def test_a_crashed_source_is_named_with_its_null_embedding_count(self, harness):
        """The 2026-09-26 morning run: PIKIRANRAKYAT's worker crashed, 269 saved
        articles / 666 chunk rows had no vector, and Telegram said only
        "FAILED: PIKIRANRAKYAT"."""
        crash = "worker process crashed (exit code 3221225477 = 0xC0000005 access violation)"
        harness.seen["pending"] = {"TEMPO": (269, 666)}
        harness.seen["store"] = ({"chunks_pending_embedding": 666, "chunks_not_in_faiss": 269},
                                 ["chunks_pending_embedding", "chunks_not_in_faiss"], "r.json")
        seen = harness(outcomes={("TEMPO", "full_text"): ("failed", crash)}, argv=("--phase", "full_text"))
        line = seen["notified"][-1]
        assert "FAILED: TEMPO" in line
        assert "vectors pending (re-embedded on the source's next full_text): TEMPO 269 articles/666 chunk rows" in line
        assert "STORE DIVERGENT" not in line

    def test_store_note_pending_heals_divergence_is_named(self):
        counts = {"chunks_pending_embedding": 666, "chunks_not_in_faiss": 269, "l1_no_articles_terminal": 4}
        note = rc.store_note(counts, ["l1_no_articles_terminal", "chunks_pending_embedding", "chunks_not_in_faiss"],
                             {"PIKIRANRAKYAT": (269, 666)})
        assert "PIKIRANRAKYAT 269 articles/666 chunk rows" in note
        assert "STORE DIVERGENT: l1_no_articles_terminal 4" in note
        assert "chunks_not_in_faiss" not in note, "the pending sitemaps explain all 269"

    def test_chunks_not_in_faiss_beyond_the_pending_ones_is_divergence(self):
        counts = {"chunks_pending_embedding": 10, "chunks_not_in_faiss": 50}
        note = rc.store_note(counts, ["chunks_pending_embedding", "chunks_not_in_faiss"], {"TEMPO": (5, 10)})
        assert "STORE DIVERGENT: chunks_not_in_faiss 50" in note

    def test_nothing_to_act_on_is_silent(self):
        assert rc.store_note(CLEAN_COUNTS, [], {}) == ""

    def test_a_failing_store_check_is_reported_not_fatal(self, harness, monkeypatch):
        def boom():
            raise OSError("NEWS_L1/index.pkl missing")
        monkeypatch.setattr(rc, "_store_check", boom)
        seen = harness()
        assert seen["rc"] == 0
        assert "store check FAILED: OSError: NEWS_L1/index.pkl missing" in seen["notified"][-1]


class TestStarvationOrder:
    """OPS-28 (#179): the first scheduled run skipped WARTAEKONOMI, last in a
    fixed alphabetical order, and the next run would have skipped it again."""

    T = __import__("datetime").datetime

    def test_never_completed_first_then_oldest_completion_first(self):
        last = {"ANTARANEWS": (self.T(2026, 9, 26, 7), 55.0), "CNBC": (self.T(2026, 9, 26, 8), 519.0),
                "WARTAEKONOMI": (self.T(2026, 6, 2, 0), 12.0)}
        order = rc.starvation_order(["ANTARANEWS", "CNBC", "EMITENNEWS", "WARTAEKONOMI"], last)
        assert order == ["EMITENNEWS", "WARTAEKONOMI", "ANTARANEWS", "CNBC"]

    def test_ties_keep_the_given_order(self):
        assert rc.starvation_order(["B", "A", "C"], {}) == ["B", "A", "C"]

    def test_projected_uses_last_durations_and_the_timeout_when_unmeasured(self):
        last = {"A": (self.T(2026, 9, 26), 100.0), "B": (self.T(2026, 9, 26), None)}
        assert rc.projected_seconds(["A", "B", "C"], last, 900) == 100 + 900 + 900

    def test_timeout_for_gives_mediaindonesia_its_own_timeout(self):
        assert rc.timeout_for("MEDIAINDONESIA", 900) == 1500
        assert rc.timeout_for("KOMPAS", 900) == 900
        assert rc.timeout_for("MEDIAINDONESIA", 1800) == 1800, "never below the run's --timeout"

    # DBT-44 (#186): the test above covers only the pure helper. Replacing its one
    # call in the run loop with `timeout = args.timeout` passed every test, and
    # MEDIAINDONESIA (947 s on 2026-09-26 19:00) would have been killed at 900 s.

    def _fleet(self, monkeypatch):
        monkeypatch.setattr(rc, "_healthy_list", lambda: ["KOMPAS", "MEDIAINDONESIA", "CNBC"])
        monkeypatch.setattr(rc, "SOURCE_TIMEOUTS", {"MEDIAINDONESIA": 1200})

    def test_the_run_loop_gives_each_source_its_own_timeout(self, harness, monkeypatch):
        self._fleet(monkeypatch)
        seen = harness(argv=("--phase", "full_text", "--timeout", "900"))
        assert seen["worker"].timeouts == {"KOMPAS": 900, "MEDIAINDONESIA": 1200, "CNBC": 900}

    def test_the_budget_counts_a_sources_own_timeout(self, harness, monkeypatch):
        """With 1,000 s left, a 900 s source may start and a 1,200 s one may not.
        Only MEDIAINDONESIA's own timeout makes that difference."""
        self._fleet(monkeypatch)
        monkeypatch.setattr(rc, "RUN_BUDGET", 1000)
        monkeypatch.setattr(rc.time, "monotonic", lambda: 0.0)
        seen = harness(argv=("--phase", "full_text", "--timeout", "900"))
        assert [w for w, _ in seen["worker"].calls] == ["KOMPAS", "CNBC"]
        assert any("MEDIAINDONESIA" in note for note in seen["notified"]), seen["notified"]

    def test_the_source_skipped_by_the_budget_goes_first_next_run(self, harness, monkeypatch):
        """Budget fits two of three sources. Run 1 skips the third. Run 2 starts
        with it -- and whichever source it then skips ran most recently."""
        clock = {"t": 0.0}
        monkeypatch.setattr(rc.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(rc, "RUN_BUDGET", 2800)
        stamp = {"n": 0}
        runs_done = {}

        def on_run(website, task):
            clock["t"] += 1000  # each source takes 1,000 s
            stamp["n"] += 1
            runs_done[website] = (self.T(2026, 9, 26, 7, stamp["n"]), 1000.0)

        def one_run():
            clock["t"] = 0.0
            w = _ScriptedWorker({}, on_run=on_run)
            harness(argv=("--phase", "full_text", "--timeout", "900"), worker=w)
            return [c[0] for c in w.calls]

        assert one_run() == ["KOMPAS", "TEMPO"]            # CNBC skipped
        assert "CNBC/full_text (run budget" in harness.seen["notified"][-1]
        # crawl_log now says KOMPAS and TEMPO completed; CNBC never did.
        harness.seen["last_runs"] = dict(runs_done)
        assert one_run() == ["CNBC", "KOMPAS"]             # TEMPO, the most recent, waits

    def test_the_projection_is_in_the_summary_when_it_does_not_fit(self, harness, monkeypatch):
        monkeypatch.setattr(rc, "RUN_BUDGET", 1000)
        seen = harness(argv=("--phase", "full_text", "--timeout", "900"))
        assert "full_text projected 2700s > budget 1000s" in seen["notified"][-1]


class _FlakyWorker(_ScriptedWorker):
    """Like _ScriptedWorker, but `sequences[(site, task)]` is a list of outcomes played in order,
    the last one repeating: a source that fails once and then works."""

    def __init__(self, sequences):
        super().__init__({})
        self.sequences = {k: list(v) for k, v in sequences.items()}

    def run(self, website, task, timeout):
        if not self.alive:
            self.start()
        self.calls.append((website, task))
        queue = self.sequences.get((website, task), [("ok", "")])
        status, detail = queue.pop(0) if len(queue) > 1 else queue[0]
        return status, detail


DNS = ("failed", "SitemapIndexUnavailable: sitemap index did not load: NameResolutionError after 3 retries")


class TestIsTransientFailure:
    """SYS-79 (#234): which failures are worth one more try."""

    @pytest.mark.parametrize("detail", [
        "SitemapIndexUnavailable: sitemap index did not load: NameResolutionError after 3 retries",
        "SitemapIndexUnavailable: sitemap index did not load: HTTP 503",
        "SitemapIndexUnavailable: sitemap index did not load: HTTP 500",
        "OSError: Connection aborted.",
        "ConnectionError: reset by peer",
        "ReadTimeout: HTTPSConnectionPool timed out",
        "SitemapIndexUnavailable: sitemap index did not load: HTTP 429",
    ])
    def test_a_failure_that_clears_on_its_own(self, detail):
        assert rc.is_transient_failure("failed", detail)

    @pytest.mark.parametrize("detail", [
        "SitemapIndexUnavailable: sitemap index did not load: HTTP 403",
        "SitemapIndexUnavailable: sitemap index did not load: HTTP 404",
        "AttributeError: 'NoneType' object has no attribute 'find_all'",
        "ValueError: unknown website",
        "",
    ])
    def test_a_failure_that_would_repeat(self, detail):
        assert not rc.is_transient_failure("failed", detail)

    @pytest.mark.parametrize("status", ["timeout", "init_failed", "ok"])
    def test_only_a_failed_source_is_retried(self, status):
        assert not rc.is_transient_failure(status, "NameResolutionError after 3 retries")


class TestRetryTransientFailures:
    def test_a_recovered_source_is_ok_and_reported_with_its_first_reason(self):
        results = {"A": ("failed", "NameResolutionError x"), "B": ("ok", ""), "C": ("failed", "HTTP 403")}
        reran = []
        recovered = rc.retry_transient_failures(results, lambda s: reran.append(s) or ("ok", ""), lambda s: True)
        assert reran == ["A"] and recovered == {"A": "NameResolutionError x"}
        assert results == {"A": ("ok", ""), "B": ("ok", ""), "C": ("failed", "HTTP 403")}

    def test_a_source_that_fails_again_stays_failed_with_the_new_reason(self):
        results = {"A": ("failed", "NameResolutionError x")}
        recovered = rc.retry_transient_failures(results, lambda s: ("failed", "HTTP 503"), lambda s: True)
        assert recovered == {} and results == {"A": ("failed", "HTTP 503")}

    def test_each_source_is_tried_once_only(self):
        calls = []
        rc.retry_transient_failures({"A": ("failed", "NameResolutionError x")},
                                    lambda s: calls.append(s) or ("failed", "NameResolutionError y"), lambda s: True)
        assert calls == ["A"]

    def test_the_budget_can_forbid_a_retry(self):
        results = {"A": ("failed", "NameResolutionError x")}
        assert rc.retry_transient_failures(results, lambda s: pytest.fail("started"), lambda s: False) == {}
        assert results["A"][0] == "failed"


class TestSitemapRetryInTheRun:
    """SYS-79: the 2026-10-05 07:00 crawl lost ANTARANEWS, BERITASATU, CNBC and CNN to a DNS outage of
    about 90 seconds at its start; the run never tried them again."""

    @pytest.fixture(autouse=True)
    def _no_pause(self, monkeypatch):
        self.pauses = []
        monkeypatch.setattr(rc.time, "sleep", self.pauses.append)

    def test_sources_that_failed_on_dns_are_retried_and_the_summary_says_so(self, harness):
        worker = _FlakyWorker({("KOMPAS", "sitemap"): [DNS, ("ok", "")], ("CNBC", "sitemap"): [DNS, ("ok", "")]})
        seen = harness(worker=worker)
        assert seen["rc"] == 0
        assert worker.calls == [("KOMPAS", "sitemap"), ("TEMPO", "sitemap"), ("CNBC", "sitemap"),
                                ("KOMPAS", "sitemap"), ("CNBC", "sitemap")], "TEMPO was fine and is not retried"
        summary = seen["notified"][-1]
        assert "FAILED" not in summary and "recovered on retry: CNBC, KOMPAS" in summary
        assert self.pauses == [rc.RETRY_PAUSE_S], "one pause before the retries"

    def test_a_403_is_not_retried_and_stays_failed(self, harness):
        worker = _FlakyWorker({("CNBC", "sitemap"): [("failed", "SitemapIndexUnavailable: sitemap index did not load: HTTP 403")]})
        seen = harness(worker=worker)
        assert seen["rc"] == 1 and "FAILED: CNBC" in seen["notified"][-1]
        assert worker.calls.count(("CNBC", "sitemap")) == 1 and self.pauses == []

    def test_a_source_that_fails_twice_is_failed_and_not_reported_as_recovered(self, harness):
        worker = _FlakyWorker({("CNBC", "sitemap"): [DNS]})
        seen = harness(worker=worker)
        assert seen["rc"] == 1 and "FAILED: CNBC" in seen["notified"][-1]
        assert "recovered on retry" not in seen["notified"][-1]
        assert worker.calls.count(("CNBC", "sitemap")) == 2

    def test_a_timeout_is_not_retried(self, harness):
        worker = _FlakyWorker({("CNBC", "sitemap"): [("timeout", "killed after 1200s")]})
        seen = harness(worker=worker)
        assert worker.calls.count(("CNBC", "sitemap")) == 1 and "FAILED: CNBC" in seen["notified"][-1]

    def test_no_retry_starts_past_the_run_budget(self, harness, monkeypatch):
        checks = []
        monkeypatch.setattr(rc, "over_budget", lambda elapsed, timeout, budget=None: checks.append(1) or len(checks) > 2)
        worker = _FlakyWorker({("KOMPAS", "sitemap"): [DNS, ("ok", "")]})
        seen = harness(worker=worker)
        assert worker.calls.count(("KOMPAS", "sitemap")) == 1 and "FAILED: KOMPAS" in seen["notified"][-1]

    def test_a_healthy_run_pauses_and_retries_nothing(self, harness):
        worker = _FlakyWorker({})
        seen = harness(worker=worker)
        assert seen["rc"] == 0 and len(worker.calls) == 3 and self.pauses == []
        assert "recovered on retry" not in seen["notified"][-1]

    def test_the_full_text_phase_is_not_retried(self, harness):
        worker = _FlakyWorker({("CNBC", "full_text"): [("failed", "OSError: Connection aborted.")]})
        seen = harness(worker=worker, argv=("--phase", "both"))
        assert worker.calls.count(("CNBC", "full_text")) == 1 and "FAILED: CNBC" in seen["notified"][-1]
