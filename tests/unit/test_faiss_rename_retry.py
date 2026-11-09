"""SYS-64 (#208): the FAISS commit rename (`NEWS_L*.tmp` -> `NEWS_L*.commit`)
and the roll-forward's file moves are retried on a transient PermissionError
(Windows WinError 5 while a scanner holds a file). Three scheduled runs lost a
source to it on 2026-09-29/30, after their articles were already committed.
"""
import os

import pytest
from langchain_community.embeddings import FakeEmbeddings
from langchain_community.vectorstores import FAISS

from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource

EMB = FakeEmbeddings(size=8)


def _texts_on_disk(db):
    return sorted(d.page_content for d in FAISS.load_local(db, EMB, allow_dangerous_deserialization=True)
                  .docstore._dict.values())


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(index_generation, "_sleep", calls.append)
    return calls


@pytest.fixture
def index(tmp_path):
    db = str(tmp_path / "L1")
    seed = FAISS.from_texts(["seed"], EMB)
    index_generation.track(seed, db, None)
    ChunkFAISSDatasource._atomic_save_local(seed, db)
    return db


def _deny(monkeypatch, name, times, match):
    """Make os.<name> raise WinError-5-style PermissionError `times` times for
    calls whose destination ends with `match`, then behave normally."""
    real = getattr(os, name)
    state = {"denied": 0}

    def flaky(src, dst, *a, **kw):
        if str(dst).endswith(match) and state["denied"] < times:
            state["denied"] += 1
            raise PermissionError(5, "Access is denied", str(src))
        return real(src, dst, *a, **kw)

    flaky.__name__ = name
    monkeypatch.setattr(os, name, flaky)
    return state


class TestCommitRenameRetry:
    def test_a_denied_commit_rename_is_retried_and_the_save_lands(self, index, monkeypatch, sleeps):
        vs = index_generation.load_index(index, EMB)
        vs.add_texts(["new"])
        state = _deny(monkeypatch, "rename", 2, ".commit")

        ChunkFAISSDatasource._atomic_save_local(vs, index)

        assert state["denied"] == 2
        assert sleeps == [index_generation.RENAME_BACKOFF_S, index_generation.RENAME_BACKOFF_S * 2]
        assert _texts_on_disk(index) == ["new", "seed"]
        # SYS-60: the writer still owns the generation it committed.
        vs.add_texts(["again"])
        ChunkFAISSDatasource._atomic_save_local(vs, index)
        assert _texts_on_disk(index) == ["again", "new", "seed"]

    def test_a_rename_that_stays_denied_raises_and_leaves_the_old_pair(self, index, monkeypatch, sleeps):
        vs = index_generation.load_index(index, EMB)
        vs.add_texts(["lost"])
        state = _deny(monkeypatch, "rename", 10 ** 6, ".commit")

        with pytest.raises(PermissionError):
            ChunkFAISSDatasource._atomic_save_local(vs, index)

        assert state["denied"] == index_generation.RENAME_RETRIES + 1
        assert len(sleeps) == index_generation.RENAME_RETRIES
        monkeypatch.undo()
        assert _texts_on_disk(index) == ["seed"]

    def test_other_errors_are_not_retried(self, monkeypatch, sleeps):
        def boom(src, dst):
            raise FileNotFoundError(src)
        with pytest.raises(FileNotFoundError):
            index_generation._retry_on_permission_error(boom, "a", "b")
        assert sleeps == []


class TestRollForwardRetry:
    def test_a_denied_move_into_place_is_retried(self, index, monkeypatch, sleeps):
        vs = index_generation.load_index(index, EMB)
        vs.add_texts(["rolled"])
        state = _deny(monkeypatch, "replace", 1, "index.faiss")

        ChunkFAISSDatasource._atomic_save_local(vs, index)

        assert state["denied"] == 1 and sleeps
        assert not os.path.isdir(index_generation.journal_dir(index))
        assert _texts_on_disk(index) == ["rolled", "seed"]
