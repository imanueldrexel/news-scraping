"""DBT-10 (#45): FAISS.save_local writes index.faiss then index.pkl directly
into the live directory, with no temp-file + rename -- a crash, OOM, or
disk-full mid-write (or between the two files) leaves the only copy of the
vector store truncated, or the two files mismatched (index.faiss with more
vectors than index.pkl's docstore has entries for, or vice versa).

ChunkFAISSDatasource._atomic_save_local writes the full pair into a sibling
temp directory (never touching the live files while save_local runs), then
swaps each file in with os.replace, pkl before faiss, keeping the previous
pair as *.bak for one generation. These tests use real FAISS indexes (via
FakeEmbeddings -- no HF model download needed) and real filesystem
operations, not mocks, since the whole point is real crash-window behavior.
"""
import os
import pickle
from unittest.mock import patch

from langchain_community.embeddings import FakeEmbeddings
from langchain_community.vectorstores import FAISS

from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
    ChunkFAISSDatasource,
)


def _vs(texts, size=8):
    return FAISS.from_texts(texts, FakeEmbeddings(size=size))


def _load(db_name, size=8):
    return FAISS.load_local(db_name, FakeEmbeddings(size=size), allow_dangerous_deserialization=True)


class TestAtomicSaveLocalBasics:
    def test_first_save_creates_index_files_no_bak(self, tmp_path):
        db_name = str(tmp_path / "L1")
        vs = _vs(["a", "b"])

        ChunkFAISSDatasource._atomic_save_local(vs, db_name)

        assert os.path.exists(os.path.join(db_name, "index.faiss"))
        assert os.path.exists(os.path.join(db_name, "index.pkl"))
        assert not os.path.exists(os.path.join(db_name, "index.faiss.bak"))
        assert not os.path.exists(os.path.join(db_name, "index.pkl.bak"))

    def test_reloaded_index_is_usable_and_has_the_right_vector_count(self, tmp_path):
        db_name = str(tmp_path / "L1")
        vs = _vs(["a", "b", "c"])

        ChunkFAISSDatasource._atomic_save_local(vs, db_name)
        reloaded = _load(db_name)

        assert reloaded.index.ntotal == 3

    def test_second_save_creates_bak_from_the_first_generation(self, tmp_path):
        db_name = str(tmp_path / "L1")
        vs1 = _vs(["a"])
        ChunkFAISSDatasource._atomic_save_local(vs1, db_name)
        with open(os.path.join(db_name, "index.faiss"), "rb") as f:
            first_faiss_bytes = f.read()

        vs2 = _vs(["a", "b"])
        ChunkFAISSDatasource._atomic_save_local(vs2, db_name)

        assert os.path.exists(os.path.join(db_name, "index.faiss.bak"))
        assert os.path.exists(os.path.join(db_name, "index.pkl.bak"))
        with open(os.path.join(db_name, "index.faiss.bak"), "rb") as f:
            assert f.read() == first_faiss_bytes
        # live index now reflects the second save
        assert _load(db_name).index.ntotal == 2

    def test_third_save_only_keeps_one_generation_of_backup(self, tmp_path):
        db_name = str(tmp_path / "L1")
        ChunkFAISSDatasource._atomic_save_local(_vs(["a"]), db_name)
        with open(os.path.join(db_name, "index.faiss"), "rb") as f:
            gen1_bytes = f.read()
        ChunkFAISSDatasource._atomic_save_local(_vs(["a", "b"]), db_name)
        ChunkFAISSDatasource._atomic_save_local(_vs(["a", "b", "c"]), db_name)

        with open(os.path.join(db_name, "index.faiss.bak"), "rb") as f:
            bak_bytes = f.read()
        assert bak_bytes != gen1_bytes, "the .bak must be gen2, not gen1 -- only one generation kept"
        assert _load(db_name).index.ntotal == 3

    def test_tmp_directory_is_cleaned_up_after_a_successful_save(self, tmp_path):
        db_name = str(tmp_path / "L1")
        ChunkFAISSDatasource._atomic_save_local(_vs(["a"]), db_name)
        assert not os.path.exists(f"{db_name}.tmp")

    def test_stale_tmp_directory_from_a_previous_crash_is_removed_first(self, tmp_path):
        db_name = str(tmp_path / "L1")
        stale_tmp = f"{db_name}.tmp"
        os.makedirs(stale_tmp)
        with open(os.path.join(stale_tmp, "garbage.txt"), "w") as f:
            f.write("leftover from an interrupted save")

        ChunkFAISSDatasource._atomic_save_local(_vs(["a"]), db_name)

        assert not os.path.exists(os.path.join(stale_tmp, "garbage.txt"))
        assert _load(db_name).index.ntotal == 1


class TestCrashBetweenTheTwoFileSwaps:
    def test_crash_after_pkl_swap_before_faiss_swap_leaves_a_loadable_stale_pair(self, tmp_path):
        """The dangerous window: os.replace succeeds for index.pkl, then the
        process dies before index.faiss is swapped. Live pair becomes
        (OLD index.faiss, NEW index.pkl). Because FAISS.add_documents only
        appends, the new docstore/index_to_docstore_id still correctly maps
        every internal id the smaller, old index.faiss actually contains --
        this must load without error and return the OLD (stale) vector count,
        not raise and not silently misalign vectors from text.
        """
        db_name = str(tmp_path / "L1")
        ChunkFAISSDatasource._atomic_save_local(_vs(["a", "b"]), db_name)

        real_replace = os.replace
        calls = []

        def flaky_replace(src, dst):
            calls.append(dst)
            if str(dst).endswith("index.faiss") and not str(dst).endswith(".bak"):
                raise OSError("simulated crash between the two swaps")
            return real_replace(src, dst)

        vs2 = _vs(["a", "b", "c", "d"])
        with patch("os.replace", side_effect=flaky_replace):
            try:
                ChunkFAISSDatasource._atomic_save_local(vs2, db_name)
            except OSError:
                pass

        # index.pkl was swapped (new, 4 docs); index.faiss was not (old, 2 vectors).
        reloaded = _load(db_name)
        assert reloaded.index.ntotal == 2, "index.faiss must still be the OLD, smaller index"
        with open(os.path.join(db_name, "index.pkl"), "rb") as f:
            docstore, index_to_docstore_id = pickle.load(f)
        assert len(docstore._dict) == 4, "index.pkl was already swapped to the NEW docstore"
        # The old index's internal ids (0, 1) must still resolve in the new
        # mapping -- proving a search against the stale index would not KeyError.
        for internal_id in range(reloaded.index.ntotal):
            assert index_to_docstore_id[internal_id] in docstore._dict

    def test_reverse_swap_order_would_have_left_unresolvable_internal_ids(self, tmp_path):
        """Documents the reasoning, not the shipped code: swapping index.faiss
        BEFORE index.pkl is the unsafe order this fix deliberately avoids --
        a crash between the two would leave a NEW (larger) index.faiss paired
        with the OLD (smaller) docstore, so the new vectors' internal ids
        would have no entry in index_to_docstore_id at all."""
        db_name = str(tmp_path / "L1")
        ChunkFAISSDatasource._atomic_save_local(_vs(["a", "b"]), db_name)
        with open(os.path.join(db_name, "index.pkl"), "rb") as f:
            old_docstore, old_mapping = pickle.load(f)

        vs2 = _vs(["a", "b", "c", "d"])
        new_index_ntotal = vs2.index.ntotal  # 4

        # The unsafe order would leave: new index.faiss (4 vectors) + old
        # index.pkl (2 entries) -- internal ids 2 and 3 have no mapping.
        assert new_index_ntotal > len(old_mapping)
        assert 2 not in old_mapping and 3 not in old_mapping
