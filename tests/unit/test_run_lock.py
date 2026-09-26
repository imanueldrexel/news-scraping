"""OPS-26 (#175): the scheduled crawl's run-level lock, and every FAISS writer's
refusal while it is held.

The QA mutation run replaced repair_store_consistency's guard with `running = 0`
and the suite stayed green. These tests fail when any of the guards is removed.
"""
import glob
import importlib.util
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from newscrawler.tools import run_lock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _hold(pid, **fields):
    """Write the lock as if process `pid` held it (its real creation time
    unless `fields` say otherwise)."""
    import psutil
    try:
        created = psutil.Process(pid).create_time()
    except psutil.NoSuchProcess:
        created = 0.0
    info = {"pid": pid, "create_time": created, "started_at": "2026-09-26T12:00:00+00:00"}
    info.update(fields)
    info = {k: v for k, v in info.items() if v is not None}
    with open(run_lock.LOCK_PATH, "w", encoding="utf-8") as f:
        json.dump(info, f)


@pytest.fixture
def fresh_process():
    """A live process created just now: what a reused pid looks like."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        yield p.pid
    finally:
        p.kill()
        p.wait()


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, "scripts", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLock:
    def test_held_for_the_block_and_released_after(self):
        with run_lock.RunLock():
            assert run_lock.holder()["pid"] == os.getpid()
        assert run_lock.holder() is None and not os.path.exists(run_lock.LOCK_PATH)

    def test_released_when_the_block_raises(self):
        with pytest.raises(RuntimeError):
            with run_lock.RunLock():
                raise RuntimeError("worker failed to start")
        assert not os.path.exists(run_lock.LOCK_PATH)

    def test_a_live_holder_refuses_a_second_run(self):
        _hold(os.getppid())  # a live process that is not us
        with pytest.raises(run_lock.RunLockHeld):
            with run_lock.RunLock():
                pass
        assert json.load(open(run_lock.LOCK_PATH))["pid"] == os.getppid(), "the holder's lock was taken"

    def test_a_dead_holder_is_stale_and_taken_over(self):
        """Task Scheduler's ExecutionTimeLimit kills the run without `finally`."""
        _hold(_dead_pid())
        assert run_lock.holder() is None
        with run_lock.RunLock():
            assert run_lock.holder()["pid"] == os.getpid()

    def test_two_runs_that_both_found_no_lock_do_not_both_get_it(self, monkeypatch):
        """The check and the write are not one step: os.link refuses to replace
        a lock that another run wrote in between."""
        real_link = os.link

        def another_run_gets_there_first(src, dst):
            _hold(os.getppid())
            return real_link(src, dst)
        monkeypatch.setattr(os, "link", another_run_gets_there_first)
        with pytest.raises(run_lock.RunLockHeld):
            run_lock.RunLock().__enter__()
        assert json.load(open(run_lock.LOCK_PATH))["pid"] == os.getppid()

    def test_release_leaves_someone_elses_lock_alone(self):
        lock = run_lock.RunLock().__enter__()
        _hold(os.getppid())  # replaced under us
        lock.release()
        assert json.load(open(run_lock.LOCK_PATH))["pid"] == os.getppid()


class TestReusedPid:
    """OPS-31 (#184): a run killed without `finally` leaves its lock, and Windows
    hands its pid to another process. pid_exists said "held" and every run
    after it failed until the file was deleted by hand."""

    def test_a_lock_whose_pid_now_belongs_to_a_newer_process_is_taken_over(self, fresh_process):
        import psutil
        created = psutil.Process(fresh_process).create_time()
        _hold(fresh_process, create_time=created - 3600)   # the owner was created an hour earlier
        assert run_lock.holder() is None
        with run_lock.RunLock():
            assert run_lock.holder()["pid"] == os.getpid()

    def test_a_pre_ops31_lock_is_stale_when_its_pid_was_created_after_it(self, fresh_process):
        _hold(fresh_process, create_time=None, started_at="2026-09-26T00:00:00+00:00")
        assert run_lock.holder() is None
        with run_lock.RunLock():
            pass

    def test_a_pre_ops31_lock_still_holds_when_its_process_predates_it(self):
        from datetime import datetime, timezone
        _hold(os.getppid(), create_time=None, started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        with pytest.raises(run_lock.RunLockHeld):
            run_lock.RunLock().__enter__()

    def test_the_real_owner_still_holds_it(self, fresh_process):
        _hold(fresh_process)
        assert run_lock.holder()["pid"] == fresh_process
        with pytest.raises(run_lock.RunLockHeld):
            run_lock.RunLock().__enter__()

    def test_the_lock_records_its_owners_creation_time(self):
        import psutil
        with run_lock.RunLock():
            info = json.load(open(run_lock.LOCK_PATH))
        assert info["create_time"] == psutil.Process().create_time()

    def test_the_refusal_names_the_holder_and_how_to_clear_a_stale_lock(self, fresh_process):
        import psutil
        _hold(fresh_process)
        with pytest.raises(run_lock.RunLockHeld) as e:
            run_lock.refuse_if_running()
        msg = str(e.value)
        assert psutil.Process(fresh_process).name() in msg and str(fresh_process) in msg
        assert "stale: delete %s by hand" % run_lock.LOCK_PATH in msg


class TestFaissSaveChokepoint:
    def _save(self, tmp_path):
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource,
        )
        saved = []

        def save_local(d):
            os.makedirs(d, exist_ok=True)
            for name in ("index.pkl", "index.faiss"):
                open(os.path.join(d, name), "wb").close()
            saved.append(d)
        from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
        vs = SimpleNamespace(save_local=save_local)
        index_generation.track_disk(vs, str(tmp_path / "NEWS_L1"))
        ChunkFAISSDatasource._atomic_save_local(vs, str(tmp_path / "NEWS_L1"))
        return saved

    def test_a_foreign_process_cannot_save_while_a_scheduled_crawl_runs(self, tmp_path):
        _hold(_live_foreign_pid())
        with pytest.raises(run_lock.RunLockHeld):
            self._save(tmp_path)

    def test_the_run_itself_and_its_worker_may_save(self, tmp_path):
        _hold(os.getpid())
        assert self._save(tmp_path)
        _hold(os.getppid())  # the worker's parent holds it
        assert self._save(tmp_path)

    def test_no_lock_no_refusal(self, tmp_path):
        assert self._save(tmp_path)


# Every FAISS-writing script's write path (not its dry run).
WRITE_PATHS = [
    ("repair_store_consistency", ["--apply"]),
    ("requeue_cascaded_articles", ["--website", "EMITENNEWS", "--apply"]),
    ("dedupe_chunks", []),
    ("cleanup_offtopic_articles", []),
    ("dedupe_sitemap_links", []),
    ("recrawl_faiss_orphans", ["--website", "MEDIAINDONESIA"]),
    ("backfill_missing_articles", ["--website", "VIVA"]),
    ("backfill_orphan_chunks", ["--website", "VIVA"]),
    ("backfill_pending_embeddings", ["--website", "VIVA"]),
]


def _live_foreign_pid():
    """A live pid that is neither this process nor its parent."""
    import psutil
    mine = {os.getpid(), os.getppid()}
    for p in psutil.process_iter(["pid"]):
        if p.info["pid"] not in mine and p.info["pid"] > 4:
            return p.info["pid"]
    raise RuntimeError("no other live process")


# What a script must touch to write NEWS_L1/L2. DBT-43: grepping for the save
# chokepoint alone missed three scripts that reach it through the datasource,
# the repository or the crawl service.
FAISS_WRITER_MARKERS = ("_atomic_save_local", "ChunkFAISSDatasource", "DataFlowRepositoryImpl", "load_index",
                        "init_crawler", "process_event")
# It takes the lock itself; its worker is the lock owner's child.
LOCK_OWNER = "run_scheduled_crawl.py"


def _faiss_writing_scripts():
    for path in sorted(glob.glob(os.path.join(REPO, "scripts", "*.py"))):
        src = open(path, encoding="utf-8").read()
        if os.path.basename(path) != LOCK_OWNER and any(m in src for m in FAISS_WRITER_MARKERS):
            yield os.path.basename(path), src


class TestEveryFaissWriterRefuses:
    def test_every_script_that_writes_faiss_checks_the_lock(self):
        """A new FAISS-writing script must refuse before its first write too;
        the chokepoint alone would stop it only after its fetches, embedding
        and SQL deletes ran."""
        writers = dict(_faiss_writing_scripts())
        unguarded = sorted(n for n, src in writers.items() if "refused_by_run_lock(logger)" not in src)
        assert unguarded == [], "these write FAISS without the OPS-26 guard: %s" % unguarded
        assert {"repair_store_consistency.py", "requeue_cascaded_articles.py", "backfill_missing_articles.py",
                "backfill_orphan_chunks.py", "backfill_pending_embeddings.py"} <= set(writers)

    def test_every_guarded_script_is_in_the_exit_2_test(self):
        """So a new writer gets the behavioural test below, not only the grep."""
        tested = {s + ".py" for s, _ in WRITE_PATHS}
        assert {n for n, _ in _faiss_writing_scripts()} == tested

    @pytest.mark.parametrize("script,argv", WRITE_PATHS)
    def test_the_write_path_exits_2_before_touching_anything(self, script, argv, monkeypatch):
        import newscrawler.infrastructure.network.clients.sqlalchemy_client as sac
        import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as cfd

        def no_db(*a, **k):
            raise AssertionError("%s opened the database under a held lock" % script)

        def no_faiss(*a, **k):
            raise AssertionError("%s loaded FAISS under a held lock" % script)
        monkeypatch.setattr(sac, "SQLAlchemyClient", no_db)
        monkeypatch.setattr(cfd, "ChunkFAISSDatasource", no_faiss)
        _hold(_live_foreign_pid())
        mod = _load_script(script)
        monkeypatch.setattr(sys, "argv", [script + ".py"] + argv)
        rc = mod.main(argv) if _takes_argv(mod) else mod.main()
        assert rc == 2


def _takes_argv(mod):
    import inspect
    return len(inspect.signature(mod.main).parameters) > 0


class TestRepairCrawlLogGuard:
    """The second guard: a manual crawl takes no lock, but it has a `started`
    crawl_log row. QA's surviving mutant was `running = 0` here."""

    def test_a_started_crawl_log_row_refuses_the_apply(self, monkeypatch, tmp_path):
        rsc = _load_script("repair_store_consistency")
        # If the guard is broken the repair runs on: keep it off the real stores.
        monkeypatch.setattr(rsc, "VECTOR_DB_NAME_L1", str(tmp_path / "NEWS_L1"))
        monkeypatch.setattr(rsc, "VECTOR_DB_NAME_L2", str(tmp_path / "NEWS_L2"))
        monkeypatch.setattr(rsc, "BACKUP_DIR", str(tmp_path / "backups"))
        for d in ("NEWS_L1", "NEWS_L2"):
            (tmp_path / d).mkdir()
        doc = SimpleNamespace(metadata={"sitemap_id": 7, "chunk_level": 1, "chunk_index": 0}, page_content="x")
        deleted = []

        class _VS:
            docstore = SimpleNamespace(_dict={"v7": doc})

            def delete(self, ids):
                deleted.append(ids)

            def save_local(self, path):
                raise AssertionError("repair saved FAISS under a running crawl")

        import langchain_community.vectorstores as lcv
        monkeypatch.setattr(lcv.FAISS, "load_local", staticmethod(lambda *a, **k: _VS()))

        class _Result(list):
            def scalar(self):
                return self[0][0]

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=None):
                q = str(sql)
                if "current_database" in q:
                    return _Result([("newsaggregator",)])
                if "FROM crawl_log" in q:
                    return _Result([(1,)])  # one crawl still 'started'
                if "FROM sitemaps" in q:
                    return _Result([SimpleNamespace(sitemap_id=7, crawl_status="rejected_filter", fetch_failures=0)])
                return _Result([])

            def commit(self):
                raise AssertionError("repair committed under a running crawl")

        import newscrawler.infrastructure.network.clients.sqlalchemy_client as sac
        monkeypatch.setattr(sac, "SQLAlchemyClient", lambda: SimpleNamespace(get_session=_Session))
        assert rsc.main(["--apply"]) == 2
        assert deleted == [], "vectors were deleted under a running crawl"
