"""SYS-53 (#182): a whole-index save may only replace the index it was loaded from.

OPS-26's run lock refuses a foreign save only while the lock is held. A crawl
that loaded NEWS_L1/L2 before or during the scheduled run and saved after it
ended wrote its stale copy over the run's vectors. Real FAISS indexes
(FakeEmbeddings) in tmp_path throughout; the run lock is pointed at tmp_path by
conftest.
"""
import json
import os
import subprocess
import sys
import threading

import pytest
from langchain_community.embeddings import FakeEmbeddings
from langchain_community.vectorstores import FAISS

import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as fmod
from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import StaleIndexError
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl

from tests.unit.test_deferred_embeddings import FakeChunkTable, _chunk, _faiss, _repo

EMB = FakeEmbeddings(size=8)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _texts_on_disk(db):
    return sorted(d.page_content for d in FAISS.load_local(db, EMB, allow_dangerous_deserialization=True)
                  .docstore._dict.values())


@pytest.fixture
def index(tmp_path):
    db = str(tmp_path / "L1")
    seed = FAISS.from_texts(["seed"], EMB)
    index_generation.track(seed, db, None)
    ChunkFAISSDatasource._atomic_save_local(seed, db)
    return db


class TestTheSaveRefusesAStaleCopy:
    def test_a_loads_b_loads_b_saves_a_is_refused_and_b_survives(self, index):
        """The ticket's Done-when (1)."""
        a = index_generation.load_index(index, EMB)
        b = index_generation.load_index(index, EMB)
        b.add_texts(["b"])
        ChunkFAISSDatasource._atomic_save_local(b, index)
        a.add_texts(["a"])
        with pytest.raises(StaleIndexError):
            ChunkFAISSDatasource._atomic_save_local(a, index)
        assert _texts_on_disk(index) == ["b", "seed"]

    def test_a_writer_may_keep_saving_its_own_generation(self, index):
        vs = index_generation.load_index(index, EMB)
        for t in ("one", "two", "three"):
            vs.add_texts([t])
            ChunkFAISSDatasource._atomic_save_local(vs, index)
        assert _texts_on_disk(index) == ["one", "seed", "three", "two"]

    def test_a_copy_that_was_never_loaded_is_refused(self, index):
        with pytest.raises(StaleIndexError, match="not loaded"):
            ChunkFAISSDatasource._atomic_save_local(FAISS.from_texts(["x"], EMB), index)
        assert _texts_on_disk(index) == ["seed"]

    def test_a_copy_loaded_from_one_index_cannot_replace_another(self, index, tmp_path):
        other = str(tmp_path / "L2")
        vs = index_generation.load_index(index, EMB)
        with pytest.raises(StaleIndexError):
            ChunkFAISSDatasource._atomic_save_local(vs, other)
        assert not os.path.exists(other)

    def test_a_new_index_is_refused_where_one_appeared_since(self, tmp_path):
        db = str(tmp_path / "L1")
        mine, theirs = FAISS.from_texts(["mine"], EMB), FAISS.from_texts(["theirs"], EMB)
        index_generation.track(mine, db, None)
        index_generation.track(theirs, db, None)
        ChunkFAISSDatasource._atomic_save_local(theirs, db)
        with pytest.raises(StaleIndexError):
            ChunkFAISSDatasource._atomic_save_local(mine, db)
        assert _texts_on_disk(db) == ["theirs"]

    def test_a_restore_by_file_copy_also_counts_as_a_change(self, index, tmp_path):
        """Why the generation is the files' identity, not a counter only this
        code writes: a restore from backups/ must stale every loaded copy."""
        import shutil
        backup = str(tmp_path / "backup")
        shutil.copytree(index, backup)                   # yesterday's backup
        writer = index_generation.load_index(index, EMB)
        writer.add_texts(["today"])
        ChunkFAISSDatasource._atomic_save_local(writer, index)
        vs = index_generation.load_index(index, EMB)     # a crawl loads today's index
        for name in index_generation.INDEX_FILES:        # the operator restores yesterday's
            shutil.copy2(os.path.join(backup, name), os.path.join(index, name))
        vs.add_texts(["crawl"])
        with pytest.raises(StaleIndexError):
            ChunkFAISSDatasource._atomic_save_local(vs, index)
        assert _texts_on_disk(index) == ["seed"]

    def test_the_check_and_the_swap_run_under_the_save_lock(self, index, monkeypatch):
        """Without the lock, two writers can both pass the check and then swap
        in turn, and they share `<index>.tmp`."""
        vs = index_generation.load_index(index, EMB)
        vs.add_texts(["mine"])
        other = index_generation.save_lock(index)
        other.acquire()
        done = threading.Event()
        t = threading.Thread(target=lambda: (ChunkFAISSDatasource._atomic_save_local(vs, index), done.set()))
        try:
            t.start()
            assert not done.wait(1.0), "saved while another writer held the index's save lock"
        finally:
            other.release()
        t.join(30)
        assert done.is_set() and _texts_on_disk(index) == ["mine", "seed"]


@pytest.fixture
def paths(tmp_path, monkeypatch):
    l1, l2 = str(tmp_path / "L1"), str(tmp_path / "L2")
    monkeypatch.setattr(fmod, "VECTOR_DB_NAME_L1", l1)
    monkeypatch.setattr(fmod, "VECTOR_DB_NAME_L2", l2)
    return l1, l2


class TestARefusedCrawlBlock:
    """Done-when (3): the refused crawl's rows stay NULL, and its next block
    re-embeds them on top of the other writer's index."""

    def _other_writer_saves(self, paths, text):
        other = _faiss(paths)
        for vs, db in ((other.vs_l1, paths[0]), (other.vs_l2, paths[1])):
            vs.add_texts([text])
            ChunkFAISSDatasource._atomic_save_local(vs, db)

    def test_rows_stay_null_the_other_writers_vectors_survive_and_the_next_block_repairs(self, paths):
        table = FakeChunkTable()
        ds = _faiss(paths)                                # this crawl loads...
        repo = _repo(ds, table)
        with pytest.raises(StaleIndexError):
            with repo.deferred_embeddings("TEST"):
                repo.save_chunk_data([_chunk(1, 1), _chunk(1, 2)])
                self._other_writer_saves(paths, "other")  # ...another process saves...
        # ...and this crawl's flush is refused instead of erasing "other".
        assert "other" in _texts_on_disk(paths[0]) and "other" in _texts_on_disk(paths[1])
        assert all(r["embedding_id"] is None for r in table.rows.values())

        with repo.deferred_embeddings("TEST"):             # the same process's next block
            pass
        assert all(r["embedding_id"] for r in table.rows.values())
        l1 = _texts_on_disk(paths[0])
        assert "other" in l1 and "text 1 1 0" in l1, "the reloaded index must keep the other writer's vector"

    def test_a_refused_blocks_ids_are_not_assigned_by_the_next_sources_flush(self, paths):
        """The worker keeps one repository for every source of a run. The ids
        held for a refused block must not reach SQL at another source's flush:
        their vectors were never saved."""
        table = FakeChunkTable()
        repo = _repo(_faiss(paths), table)
        with pytest.raises(StaleIndexError):
            with repo.deferred_embeddings("SOURCE_A"):
                repo.save_chunk_data([_chunk(1, 1)])
                self._other_writer_saves(paths, "other")
        table.load_unembedded_chunks = lambda website=None: []  # SOURCE_B has no NULL rows of its own
        with repo.deferred_embeddings("SOURCE_B"):
            repo.save_chunk_data([_chunk(2, 1)])
        assert table.rows[(1, 1, 0)]["embedding_id"] is None
        on_disk = FAISS.load_local(paths[0], EMB, allow_dangerous_deserialization=True).docstore._dict
        assert table.rows[(2, 1, 0)]["embedding_id"] in on_disk


class TestTwoSeparateProcesses:
    def test_a_manual_crawl_cannot_overwrite_the_scheduled_run_after_release(self, tmp_path):
        """Done-when (2): the QA reproduction, two sibling processes (neither is
        the other's child) around a real RunLock. Before SYS-53 it ended with
        ['manual', 'seed']: the run's vector was gone."""
        script = os.path.join(REPO, "scripts", "experiments", "repro_stale_index_overwrite.py")
        r = subprocess.run([sys.executable, script, "--dir", str(tmp_path)], cwd=REPO,
                           capture_output=True, text=True, timeout=110)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert out["final_disk"] == ["run", "seed"], out
        assert "manual: save under the lock refused (RunLockHeld)" in out["events"], out
        assert "manual: save after release refused (StaleIndexError)" in out["events"], out
        assert r.returncode == 0, r.stderr[-2000:]
