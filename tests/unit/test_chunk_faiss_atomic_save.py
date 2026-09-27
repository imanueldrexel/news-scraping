"""DBT-10 (#45): FAISS.save_local writes index.faiss then index.pkl directly
into the live directory, with no temp-file + rename -- a crash, OOM, or
disk-full mid-write (or between the two files) leaves the only copy of the
vector store truncated, or the two files mismatched (index.faiss with more
vectors than index.pkl's docstore has entries for, or vice versa).

ChunkFAISSDatasource._atomic_save_local writes the full pair into a sibling
staging directory (never touching the live files while save_local runs),
stages the previous pair beside it as *.bak, commits the lot with one
directory rename and rolls it into place (SYS-56: a kill anywhere leaves one
whole pair, as load_index sees it). These tests use real FAISS indexes (via
FakeEmbeddings -- no HF model download needed) and real filesystem
operations, not mocks, since the whole point is real crash-window behavior.
"""
import os
import shutil
from unittest.mock import patch

import pytest

from langchain_community.embeddings import FakeEmbeddings
from langchain_community.vectorstores import FAISS

from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import (
    CorruptIndexError,
    StaleIndexError,
)
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
    ChunkFAISSDatasource,
)


def _vs(texts, size=8):
    return FAISS.from_texts(texts, FakeEmbeddings(size=size))


def _save(vs, db_name):
    """Save a freshly built index as the next generation of db_name. SYS-53's
    freshness check has its own tests (test_index_generation.py); these are
    about the swap."""
    index_generation.track_disk(vs, db_name)
    ChunkFAISSDatasource._atomic_save_local(vs, db_name)


def _load(db_name, size=8):
    return FAISS.load_local(db_name, FakeEmbeddings(size=size), allow_dangerous_deserialization=True)


class TestAtomicSaveLocalBasics:
    def test_first_save_creates_index_files_no_bak(self, tmp_path):
        db_name = str(tmp_path / "L1")
        vs = _vs(["a", "b"])

        _save(vs, db_name)

        assert os.path.exists(os.path.join(db_name, "index.faiss"))
        assert os.path.exists(os.path.join(db_name, "index.pkl"))
        assert not os.path.exists(os.path.join(db_name, "index.faiss.bak"))
        assert not os.path.exists(os.path.join(db_name, "index.pkl.bak"))

    def test_reloaded_index_is_usable_and_has_the_right_vector_count(self, tmp_path):
        db_name = str(tmp_path / "L1")
        vs = _vs(["a", "b", "c"])

        _save(vs, db_name)
        reloaded = _load(db_name)

        assert reloaded.index.ntotal == 3

    def test_second_save_creates_bak_from_the_first_generation(self, tmp_path):
        db_name = str(tmp_path / "L1")
        vs1 = _vs(["a"])
        _save(vs1, db_name)
        with open(os.path.join(db_name, "index.faiss"), "rb") as f:
            first_faiss_bytes = f.read()

        vs2 = _vs(["a", "b"])
        _save(vs2, db_name)

        assert os.path.exists(os.path.join(db_name, "index.faiss.bak"))
        assert os.path.exists(os.path.join(db_name, "index.pkl.bak"))
        with open(os.path.join(db_name, "index.faiss.bak"), "rb") as f:
            assert f.read() == first_faiss_bytes
        # live index now reflects the second save
        assert _load(db_name).index.ntotal == 2

    def test_third_save_only_keeps_one_generation_of_backup(self, tmp_path):
        db_name = str(tmp_path / "L1")
        _save(_vs(["a"]), db_name)
        with open(os.path.join(db_name, "index.faiss"), "rb") as f:
            gen1_bytes = f.read()
        _save(_vs(["a", "b"]), db_name)
        _save(_vs(["a", "b", "c"]), db_name)

        with open(os.path.join(db_name, "index.faiss.bak"), "rb") as f:
            bak_bytes = f.read()
        assert bak_bytes != gen1_bytes, "the .bak must be gen2, not gen1 -- only one generation kept"
        assert _load(db_name).index.ntotal == 3

    def test_tmp_directory_is_cleaned_up_after_a_successful_save(self, tmp_path):
        db_name = str(tmp_path / "L1")
        _save(_vs(["a"]), db_name)
        assert not os.path.exists(f"{db_name}.tmp")

    def test_stale_tmp_directory_from_a_previous_crash_is_removed_first(self, tmp_path):
        db_name = str(tmp_path / "L1")
        stale_tmp = f"{db_name}.tmp"
        os.makedirs(stale_tmp)
        with open(os.path.join(stale_tmp, "garbage.txt"), "w") as f:
            f.write("leftover from an interrupted save")

        _save(_vs(["a"]), db_name)

        assert not os.path.exists(os.path.join(stale_tmp, "garbage.txt"))
        assert _load(db_name).index.ntotal == 1


def _repro():
    """scripts/experiments/repro_torn_pair_after_delete.py: QA's repro and this
    test are one piece of code."""
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "experiments",
                        "repro_torn_pair_after_delete.py")
    spec = importlib.util.spec_from_file_location("repro_torn_pair_after_delete", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestKilledMidSave:
    """SYS-56 (#190): FAISS.delete renumbers index_to_docstore_id, so DBT-10's
    'a torn pair is stale but consistent' argument failed once a save could
    delete (SYS-54). A kill anywhere in a save must leave the old pair or the
    new pair, as load_index sees it, never a mix."""

    def test_qa_kill_point_after_the_index_pkl_replace(self, tmp_path):
        repro = _repro()
        point = repro.qa_kill_point(str(tmp_path / "count"))
        out = repro.run(str(tmp_path / "run"), point)
        assert out["ok"], out
        assert out["ntotal"] == out["mapped"] == 5 and out["generation"] == "new"

    def test_every_kill_point_leaves_one_whole_pair(self, tmp_path):
        repro = _repro()
        n = repro.count_steps(str(tmp_path / "count"))
        assert n == 7, "the save's filesystem steps changed; re-read SYS-56 before updating this"
        generations = []
        for point in range(n):
            out = repro.run(str(tmp_path / ("k%d" % point)), point)
            assert out["ok"], out
            assert out["ntotal"] == out["mapped"], out
            generations.append(out["generation"])
        # The two backup copies come before the commit rename; everything after
        # it is finished by the next load.
        assert generations == ["old", "old"] + ["new"] * 5

    def test_a_kill_before_the_commit_changes_nothing_on_disk(self, tmp_path):
        db_name = str(tmp_path / "L1")
        _save(_vs(["a", "b"]), db_name)
        before = index_generation.disk_generation(db_name)
        real_rename = os.rename

        def killed(src, dst):
            if str(dst).endswith(".commit"):
                raise SystemExit("killed before the commit")
            return real_rename(src, dst)

        with patch("os.rename", side_effect=killed):
            with pytest.raises(SystemExit):
                _save(_vs(["a", "b", "c"]), db_name)
        assert index_generation.disk_generation(db_name) == before
        assert not os.path.exists(index_generation.journal_dir(db_name))
        assert index_generation.load_index(db_name, FakeEmbeddings(size=8)).index.ntotal == 2
        assert not os.path.exists(index_generation.staging_dir(db_name)), "the uncommitted stage is dropped"

    def test_the_backup_is_one_pair_even_when_the_roll_forward_is_killed(self, tmp_path):
        db_name = str(tmp_path / "L1")
        _save(_vs(["a", "b"]), db_name)
        real_replace = os.replace

        def killed(src, dst):
            real_replace(src, dst)
            if str(dst).endswith("index.pkl.bak"):
                raise SystemExit("killed between the two backup moves")

        with patch("os.replace", side_effect=killed):
            with pytest.raises(SystemExit):
                _save(_vs(["a", "b", "c"]), db_name)
        index_generation.load_index(db_name, FakeEmbeddings(size=8))  # rolls forward

        restored = tmp_path / "restored"
        restored.mkdir()
        for name in index_generation.INDEX_FILES:
            shutil.copy2(os.path.join(db_name, name + ".bak"), str(restored / name))
        vs = index_generation.load_index(str(restored), FakeEmbeddings(size=8))
        assert vs.index.ntotal == 2 and len(vs.docstore._dict) == 2

    def test_a_first_save_killed_after_its_commit_is_loaded_not_recreated(self, tmp_path):
        db_name = str(tmp_path / "L1")
        with patch("os.replace", side_effect=SystemExit("killed right after the commit")):
            with pytest.raises(SystemExit):
                _save(_vs(["a", "b", "c"]), db_name)
        assert not os.path.exists(os.path.join(db_name, "index.faiss"))
        assert index_generation.has_index(db_name), "_load_or_create must load it, not start an empty index"
        assert index_generation.load_index(db_name, FakeEmbeddings(size=8)).index.ntotal == 3

    def test_a_save_finishes_a_committed_save_before_its_freshness_check(self, tmp_path):
        """A save committed and then killed is the newest generation, although
        the live files still show the older one. A writer that loaded before it
        must be refused, not allowed to overwrite it."""
        db_name = str(tmp_path / "L1")
        _save(_vs(["a"]), db_name)
        mine = index_generation.load_index(db_name, FakeEmbeddings(size=8))
        theirs = index_generation.load_index(db_name, FakeEmbeddings(size=8))
        theirs.add_texts(["theirs"])
        with patch("os.replace", side_effect=SystemExit("killed after the commit")):
            with pytest.raises(SystemExit):
                ChunkFAISSDatasource._atomic_save_local(theirs, db_name)

        mine.add_texts(["mine"])
        with pytest.raises(StaleIndexError):
            ChunkFAISSDatasource._atomic_save_local(mine, db_name)
        on_disk = index_generation.load_index(db_name, FakeEmbeddings(size=8))
        assert sorted(d.page_content for d in on_disk.docstore._dict.values()) == ["a", "theirs"]


class TestLoadRefusesAMismatchedPair:
    def test_an_old_index_faiss_with_a_new_index_pkl_after_a_delete_is_refused(self, tmp_path):
        """The pre-SYS-56 torn pair, made by hand: load_index fails loudly."""
        db_name = str(tmp_path / "L1")
        _save(_vs(["a", "b", "c"]), db_name)
        old_faiss = str(tmp_path / "old.faiss")
        shutil.copy2(os.path.join(db_name, "index.faiss"), old_faiss)
        vs = index_generation.load_index(db_name, FakeEmbeddings(size=8))
        vs.delete([vs.index_to_docstore_id[0]])
        ChunkFAISSDatasource._atomic_save_local(vs, db_name)
        shutil.copy2(old_faiss, os.path.join(db_name, "index.faiss"))

        with pytest.raises(CorruptIndexError, match="3 vectors but index.pkl maps 2"):
            index_generation.load_index(db_name, FakeEmbeddings(size=8))
        assert "3 vectors" in index_generation.disk_pair_problem(db_name)

    def test_pair_problem_checks_every_position_and_every_mapped_document(self):
        assert index_generation.pair_problem(2, {0: "x", 1: "y"}, {"x": 1, "y": 2}) is None
        assert index_generation.pair_problem(2, {0: "x", 1: "y"}, {"x": 1}) == \
            "1 mapped positions point at no stored document"
        assert index_generation.pair_problem(2, {0: "x", 2: "y"}, {"x": 1, "y": 2}) is not None

    def test_a_journal_left_behind_is_a_disk_problem_until_rolled_forward(self, tmp_path):
        db_name = str(tmp_path / "L1")
        _save(_vs(["a"]), db_name)
        os.makedirs(index_generation.journal_dir(db_name))
        assert "not rolled forward" in index_generation.disk_pair_problem(db_name)
        index_generation.load_index(db_name, FakeEmbeddings(size=8))
        assert index_generation.disk_pair_problem(db_name) is None
