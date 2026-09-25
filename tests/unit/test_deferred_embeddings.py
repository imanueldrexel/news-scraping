"""DBT-10 (#45): one FAISS save per source run instead of one per batch, without
giving up crash consistency.

Real FAISS indexes (FakeEmbeddings) in tmp_path -- the index-path constants are
patched, so nothing here can touch NEWS_L1/NEWS_L2 -- and an in-memory stand-in
for the SQL `chunks` table keyed on the DBT-09 unique key. What is guarded:
  * a deferred block with several batches saves each index ONCE;
  * rows are written unembedded and only get ids after the flush;
  * a "kill" inside the block (the block never exits) leaves no vectors on disk
    and NULL rows, which the next block re-embeds;
  * a kill between flush and id assignment is healed without duplicate vectors;
  * a failed flush assigns no ids; an exception in the body still flushes;
  * outside a block (every script) each save persists, as before.
"""
from unittest.mock import patch

import pytest
from langchain_community.embeddings import FakeEmbeddings
from langchain_community.vectorstores import FAISS

import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as fmod
from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl

EMB = FakeEmbeddings(size=8)


class FakeChunkTable:
    """chunks keyed (sitemap_id, level, index) -> {embedding_id, chunk_status, dto}."""

    def __init__(self):
        self.rows = {}

    def get_existing_sitemap_level_pairs(self, sitemap_ids):
        levels = {}
        for (sid, lvl, _), r in self.rows.items():
            if sid in sitemap_ids:
                levels.setdefault((sid, lvl), []).append(r["embedding_id"])
        return {k for k, ids in levels.items() if all(ids)}

    def save_chunks(self, models):
        for m in models:
            self.rows[(m.sitemap_id, m.chunk_level, m.chunk_index)] = {
                "embedding_id": m.embedding_id, "chunk_status": m.chunk_status, "text": m.text_content}

    def load_unembedded_chunks(self, website=None):
        return [_chunk(k[0], k[1], k[2]) for k, r in self.rows.items() if r["embedding_id"] is None]

    def set_embedding_ids(self, ids_by_key):
        n = 0
        for k, eid in ids_by_key.items():
            if k in self.rows and self.rows[k]["embedding_id"] is None:
                self.rows[k].update(embedding_id=eid, chunk_status="embedded")
                n += 1
        return n


def _chunk(sid, level=1, idx=0):
    return ChunkDTO(sitemap_id=sid, chunk_level=level, chunk_index=idx, chunk_total=1, is_first_chunk=True,
                    is_last_chunk=True, text_content="text %d %d %d" % (sid, level, idx), token_count=3,
                    title="t", source="TEST", category="bisnis", posted_at=20260926)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    l1, l2 = str(tmp_path / "L1"), str(tmp_path / "L2")
    monkeypatch.setattr(fmod, "VECTOR_DB_NAME_L1", l1)
    monkeypatch.setattr(fmod, "VECTOR_DB_NAME_L2", l2)
    return l1, l2


def _faiss(paths):
    """A datasource over the on-disk indexes (fresh ones if none yet)."""
    import os
    ds = ChunkFAISSDatasource.__new__(ChunkFAISSDatasource)
    out = []
    for p in paths:
        if os.path.exists(os.path.join(p, "index.faiss")):
            out.append(FAISS.load_local(p, EMB, allow_dangerous_deserialization=True))
        else:
            vs = FAISS.from_texts(["seed"], EMB, metadatas=[{"seed": True}])
            ChunkFAISSDatasource._atomic_save_local(vs, p)
            out.append(vs)
    ds.vs_l1, ds.vs_l2 = out
    return ds


def _repo(faiss_ds, table):
    repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
    repo.chunk_faiss_datasource = faiss_ds
    repo.sql_alchemy_chunk_datasource = table
    return repo


def _on_disk(path):
    return FAISS.load_local(path, EMB, allow_dangerous_deserialization=True).index.ntotal


def _batches():
    return [[_chunk(1, 1), _chunk(1, 2)], [_chunk(2, 1), _chunk(2, 2)], [_chunk(3, 1), _chunk(3, 2, 0), _chunk(3, 2, 1)]]


class TestOneSavePerBlock:
    def test_three_batches_save_each_index_once(self, paths):
        table, ds = FakeChunkTable(), _faiss(paths)
        repo = _repo(ds, table)
        with patch.object(ChunkFAISSDatasource, "_atomic_save_local", wraps=ChunkFAISSDatasource._atomic_save_local) as save:
            with repo.deferred_embeddings("TEST"):
                for b in _batches():
                    repo.save_chunk_data(b)
                assert save.call_count == 0, "nothing may be written mid-block"
        assert sorted(c.args[1] for c in save.call_args_list) == sorted(paths)
        assert _on_disk(paths[0]) == 1 + 3 and _on_disk(paths[1]) == 1 + 4
        assert all(r["embedding_id"] and r["chunk_status"] == "embedded" for r in table.rows.values())

    def test_rows_are_unembedded_until_the_flush(self, paths):
        table, ds = FakeChunkTable(), _faiss(paths)
        repo = _repo(ds, table)
        with repo.deferred_embeddings("TEST"):
            repo.save_chunk_data(_batches()[0])
            assert all(r["embedding_id"] is None and r["chunk_status"] == "pending_embedding"
                       for r in table.rows.values())

    def test_the_ids_assigned_are_the_ids_on_disk(self, paths):
        table, ds = FakeChunkTable(), _faiss(paths)
        with _repo(ds, table).deferred_embeddings("TEST") as repo:
            repo.save_chunk_data(_batches()[0])
        on_disk = FAISS.load_local(paths[0], EMB, allow_dangerous_deserialization=True).docstore._dict
        assert table.rows[(1, 1, 0)]["embedding_id"] in on_disk


class TestKills:
    def test_a_kill_inside_the_block_leaves_nothing_on_disk_and_null_rows_that_the_next_run_repairs(self, paths):
        table = FakeChunkTable()
        killed = _repo(_faiss(paths), table)
        killed.chunk_faiss_datasource.begin_deferred()      # the block starts...
        killed.save_chunk_data(_batches()[0])               # ...commits SQL rows...
        # ...and the process dies: no end_deferred, no flush.
        assert _on_disk(paths[0]) == 1 and _on_disk(paths[1]) == 1
        assert all(r["embedding_id"] is None for r in table.rows.values())

        # Next run: a fresh process over the same disk and table.
        with _repo(_faiss(paths), table).deferred_embeddings("TEST"):
            pass
        assert _on_disk(paths[0]) == 2 and _on_disk(paths[1]) == 2
        assert all(r["embedding_id"] for r in table.rows.values())

    def test_a_kill_between_flush_and_id_assignment_heals_without_duplicate_vectors(self, paths):
        table = FakeChunkTable()
        repo = _repo(_faiss(paths), table)
        with patch.object(DataFlowRepositoryImpl, "_assign_pending_embedding_ids"):  # "dies" after the flush
            with repo.deferred_embeddings("TEST"):
                repo.save_chunk_data(_batches()[0])
        assert _on_disk(paths[0]) == 2 and all(r["embedding_id"] is None for r in table.rows.values())

        with _repo(_faiss(paths), table).deferred_embeddings("TEST"):
            pass
        assert _on_disk(paths[0]) == 2 and _on_disk(paths[1]) == 2, "vectors re-added: duplicates"
        assert all(r["embedding_id"] for r in table.rows.values())


class TestFailures:
    def test_a_failed_flush_assigns_no_ids(self, paths):
        table = FakeChunkTable()
        repo = _repo(_faiss(paths), table)
        with patch.object(ChunkFAISSDatasource, "_atomic_save_local", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                with repo.deferred_embeddings("TEST"):
                    repo.save_chunk_data(_batches()[0])
        assert all(r["embedding_id"] is None for r in table.rows.values())

    def test_an_exception_in_the_body_still_flushes_and_assigns(self, paths):
        table = FakeChunkTable()
        repo = _repo(_faiss(paths), table)
        with pytest.raises(RuntimeError):
            with repo.deferred_embeddings("TEST"):
                repo.save_chunk_data(_batches()[0])
                raise RuntimeError("source failed after batch 1")
        assert _on_disk(paths[0]) == 2
        assert all(r["embedding_id"] for r in table.rows.values())


class TestOutsideABlock:
    def test_every_save_persists_as_before(self, paths):
        table = FakeChunkTable()
        repo = _repo(_faiss(paths), table)
        with patch.object(ChunkFAISSDatasource, "_atomic_save_local", wraps=ChunkFAISSDatasource._atomic_save_local) as save:
            for b in _batches():
                repo.save_chunk_data(b)
        assert save.call_count == 6   # 3 batches x 2 levels
        assert all(r["embedding_id"] and r["chunk_status"] == "embedded" for r in table.rows.values())


class TestKeyCache:
    def test_a_delete_outside_the_class_invalidates_the_cache(self, paths):
        ds = _faiss(paths)
        table = FakeChunkTable()
        repo = _repo(ds, table)
        repo.save_chunk_data([_chunk(9, 1)])
        eid = table.rows[(9, 1, 0)]["embedding_id"]
        ds.vs_l1.delete([eid])                      # dedupe_chunks.py's shape
        table.rows.clear()
        repo.save_chunk_data([_chunk(9, 1)])        # must re-add, not reuse the deleted id
        assert table.rows[(9, 1, 0)]["embedding_id"] != eid
        assert table.rows[(9, 1, 0)]["embedding_id"] in ds.vs_l1.docstore._dict


def test_the_service_runs_each_source_inside_one_block():
    from unittest.mock import MagicMock
    from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.crawler_dict = {"TEST": MagicMock()}
    svc.data_flow_repo.load_sitemap_data.return_value = []
    svc.crawl_newsdetails("TEST")
    svc.data_flow_repo.deferred_embeddings.assert_called_once_with("TEST")
