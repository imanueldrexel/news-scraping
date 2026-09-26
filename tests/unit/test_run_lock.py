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


def _hold(pid):
    """Write the lock as if process `pid` held it."""
    with open(run_lock.LOCK_PATH, "w", encoding="utf-8") as f:
        json.dump({"pid": pid, "started_at": "2026-09-26T12:00:00+00:00"}, f)


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

    def test_release_leaves_someone_elses_lock_alone(self):
        lock = run_lock.RunLock().__enter__()
        _hold(os.getppid())  # replaced under us
        lock.release()
        assert json.load(open(run_lock.LOCK_PATH))["pid"] == os.getppid()


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
        vs = SimpleNamespace(save_local=save_local)
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


def _live_foreign_pid():
    """A live pid that is neither this process nor its parent."""
    import psutil
    mine = {os.getpid(), os.getppid()}
    for p in psutil.process_iter(["pid"]):
        if p.info["pid"] not in mine and p.info["pid"] > 4:
            return p.info["pid"]
    raise RuntimeError("no other live process")


class TestEveryFaissWriterRefuses:
    def test_every_script_that_saves_faiss_checks_the_lock(self):
        """A new FAISS-writing script must refuse before its first write too;
        the chokepoint alone would stop it only after its SQL deletes ran."""
        writers = []
        for path in glob.glob(os.path.join(REPO, "scripts", "*.py")):
            src = open(path, encoding="utf-8").read()
            if "_atomic_save_local" in src:
                writers.append(os.path.basename(path))
                assert "refused_by_run_lock(logger)" in src, "%s writes FAISS without the OPS-26 guard" % path
        assert "repair_store_consistency.py" in writers and "requeue_cascaded_articles.py" in writers

    @pytest.mark.parametrize("script,argv", [
        ("repair_store_consistency", ["--apply"]),
        ("requeue_cascaded_articles", ["--website", "EMITENNEWS", "--apply"]),
        ("dedupe_chunks", []),
        ("cleanup_offtopic_articles", []),
        ("dedupe_sitemap_links", []),
        ("recrawl_faiss_orphans", ["--website", "MEDIAINDONESIA"]),
    ])
    def test_the_write_path_exits_2_before_touching_anything(self, script, argv, monkeypatch):
        import newscrawler.infrastructure.network.clients.sqlalchemy_client as sac

        def no_db(*a, **k):
            raise AssertionError("%s opened the database under a held lock" % script)
        monkeypatch.setattr(sac, "SQLAlchemyClient", no_db)
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
