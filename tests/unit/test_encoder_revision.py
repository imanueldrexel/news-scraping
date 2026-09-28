"""
SYS-61 (#198): nothing tied the probe or the FAISS indexes to the encoder
revision they were built with. OPS-32 loads each model from the snapshot the
local cache's refs/main names, but any online load by Hub id moves refs/main
when upstream has moved, and the next crawl would then embed with the new
revision, silently: the probe's tau and gates were measured on the old one,
and new vectors would land in a different space from the stored ones.

Now the probe's sidecar records `embedding_revision` and each FAISS pair
carries `encoder.json`; building either against another revision raises a
named error (ProbeArtifactError / EncoderRevisionError), which the OPS-32
breaker turns into one STOPPED reason.

Offline: a fake Hugging Face cache in tmp_path stands in for the real one.
"""
import json
import os
from unittest.mock import patch

import pytest
from langchain_community.embeddings import FakeEmbeddings

from newscrawler.core.utils import hf_cache
from newscrawler.core.utils.hf_cache import EncoderRevisionError, cached_revision, check_revision
from newscrawler.infrastructure.datasource.dataflow.write.faiss import chunk_faiss_data_source as cfds
from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
from newscrawler.tools import run_lock

E5 = "intfloat/multilingual-e5-large"
MINILM = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
E5_TRAINED = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"  # the committed probe's sidecar


def _snapshot(cache, model, revision):
    folder = cache / ("models--" + model.replace("/", "--"))
    snap = folder / "snapshots" / revision
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "config.json").write_text("{}", encoding="utf-8")
    (folder / "refs").mkdir(exist_ok=True)


def _point_main(cache, model, revision):
    (cache / ("models--" + model.replace("/", "--")) / "refs" / "main").write_text(revision, encoding="utf-8")


@pytest.fixture
def hub(tmp_path, monkeypatch):
    cache = tmp_path / "hub"
    for model, revisions in ((E5, (E5_TRAINED, "e5newer")), (MINILM, ("minilm1", "minilm2"))):
        for rev in revisions:
            _snapshot(cache, model, rev)
    _point_main(cache, E5, E5_TRAINED)
    _point_main(cache, MINILM, "minilm1")
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    return cache


class TestCachedRevision:
    def test_it_follows_refs_main(self, hub):
        assert cached_revision(MINILM) == "minilm1"
        _point_main(hub, MINILM, "minilm2")
        assert cached_revision(MINILM) == "minilm2"

    def test_a_model_not_cached_has_no_revision(self, hub):
        assert cached_revision("org/not-cached") is None

    def test_check_revision_names_both_revisions(self):
        check_revision(MINILM, "a", "a", "NEWS_L1")
        with pytest.raises(EncoderRevisionError, match=r"NEWS_L1 was built with .* revision a, .* resolves it to b"):
            check_revision(MINILM, "a", "b", "NEWS_L1")
        with pytest.raises(EncoderRevisionError, match="no cached revision"):
            check_revision(MINILM, "a", None, "NEWS_L1")


class _StubEncoder:
    """Stands in for the 2.2 GB e5-large: the filter only asks it its dimension here."""

    def __init__(self, path):
        self.path = path

    def get_sentence_embedding_dimension(self):
        return 1024


class TestTheProbeRefusesAnotherEncoderRevision:
    def _build(self, monkeypatch, probe=None):
        from newscrawler.core import importance_filter
        monkeypatch.setattr(importance_filter, "SentenceTransformer", _StubEncoder)
        return importance_filter.SemanticImportanceFilter(probe=probe)

    def test_the_committed_probe_records_its_encoder_revision(self):
        from newscrawler.core.importance_probe import ImportanceProbe
        assert ImportanceProbe.load().encoder_revision == E5_TRAINED

    def test_it_builds_on_the_revision_it_was_trained_on(self, hub, monkeypatch):
        filt = self._build(monkeypatch)
        assert filt.model.path.endswith(E5_TRAINED)

    def test_refs_main_moved_to_another_snapshot_stops_the_build(self, hub, monkeypatch):
        from newscrawler.core.importance_probe import ProbeArtifactError
        _point_main(hub, E5, "e5newer")
        with pytest.raises(ProbeArtifactError, match=f"revision {E5_TRAINED}.*resolves it to e5newer"):
            self._build(monkeypatch)
        _point_main(hub, E5, E5_TRAINED)
        self._build(monkeypatch)

    def test_a_sidecar_without_a_revision_stops_the_build(self, hub, monkeypatch):
        from newscrawler.core.importance_probe import ImportanceProbe, ProbeArtifactError
        probe = ImportanceProbe.load()
        probe.sidecar = {k: v for k, v in probe.sidecar.items() if k != "embedding_revision"}
        with pytest.raises(ProbeArtifactError, match="records no embedding_revision"):
            self._build(monkeypatch, probe=probe)


@pytest.fixture
def faiss_paths(tmp_path, monkeypatch, hub):
    l1, l2 = str(tmp_path / "NEWS_L1"), str(tmp_path / "NEWS_L2")
    monkeypatch.setattr(cfds, "VECTOR_DB_NAME_L1", l1)
    monkeypatch.setattr(cfds, "VECTOR_DB_NAME_L2", l2)
    monkeypatch.setattr(cfds, "EMBEDDING_MODEL_HF", MINILM)
    monkeypatch.setattr(cfds, "HuggingFaceEmbeddings", lambda **kwargs: FakeEmbeddings(size=8))
    monkeypatch.setattr(run_lock, "LOCK_PATH", str(tmp_path / "scheduled_crawl.lock"))
    return l1, l2


def _build_and_save(texts):
    ds = cfds.ChunkFAISSDatasource()
    for vs, db in ((ds.vs_l1, cfds.VECTOR_DB_NAME_L1), (ds.vs_l2, cfds.VECTOR_DB_NAME_L2)):
        vs.add_texts(texts)
        ds._persist(vs, db)
    return ds


class TestTheFaissIndexRefusesAnotherEncoderRevision:
    def test_a_save_commits_the_encoder_with_the_pair(self, faiss_paths):
        _build_and_save(["a"])
        for db in faiss_paths:
            assert index_generation.read_encoder(db) == {"model": MINILM, "revision": "minilm1"}

    def test_refs_main_moved_to_another_snapshot_stops_the_build(self, faiss_paths, hub):
        _build_and_save(["a"])
        _point_main(hub, MINILM, "minilm2")
        with pytest.raises(EncoderRevisionError, match="revision minilm1.*resolves it to minilm2"):
            cfds.ChunkFAISSDatasource()
        _point_main(hub, MINILM, "minilm1")
        ds = cfds.ChunkFAISSDatasource()
        assert ds.vs_l1.index.ntotal == 1

    def test_an_index_embedded_with_another_model_is_refused(self, faiss_paths):
        _build_and_save(["a"])
        with open(os.path.join(faiss_paths[0], index_generation.ENCODER_FILE), "w", encoding="utf-8") as f:
            json.dump({"model": "org/other", "revision": "minilm1"}, f)
        with pytest.raises(EncoderRevisionError, match="embedded with org/other"):
            cfds.ChunkFAISSDatasource()

    def test_an_index_saved_before_sys61_loads_and_its_next_save_records_the_encoder(self, faiss_paths, caplog):
        _build_and_save(["a"])
        for db in faiss_paths:
            os.remove(os.path.join(db, index_generation.ENCODER_FILE))
        with caplog.at_level("WARNING"):
            ds = cfds.ChunkFAISSDatasource()
        assert "records no encoder revision" in caplog.text
        ds.vs_l1.add_texts(["b"])
        ds._persist(ds.vs_l1, faiss_paths[0])
        assert index_generation.read_encoder(faiss_paths[0])["revision"] == "minilm1"

    def test_a_save_that_embeds_nothing_keeps_the_record(self, faiss_paths):
        """The repair and dedupe scripts save through _atomic_save_local
        without an encoder: the pair keeps the record it had."""
        ds = _build_and_save(["a", "b"])
        vs = ds.vs_l1
        vs.delete([vs.index_to_docstore_id[0]])
        cfds.ChunkFAISSDatasource._atomic_save_local(vs, faiss_paths[0])
        assert index_generation.read_encoder(faiss_paths[0]) == {"model": MINILM, "revision": "minilm1"}

    def test_the_record_travels_in_the_journal(self, faiss_paths):
        """Committed with the pair (SYS-56): a save killed right after its
        commit leaves the record in the journal, and the next load finishes it."""
        ds = _build_and_save(["a"])
        with open(os.path.join(faiss_paths[0], index_generation.ENCODER_FILE), "w", encoding="utf-8") as f:
            json.dump({"model": MINILM, "revision": "stale"}, f)
        ds.vs_l1.add_texts(["b"])
        with patch.object(index_generation, "roll_forward", return_value=False):  # killed after the commit
            cfds.ChunkFAISSDatasource._atomic_save_local(ds.vs_l1, faiss_paths[0], encoder=ds.encoder_record)
        journal = index_generation.journal_dir(faiss_paths[0])
        with open(os.path.join(journal, index_generation.ENCODER_FILE), encoding="utf-8") as f:
            assert json.load(f)["revision"] == "minilm1"
        assert index_generation.read_encoder(faiss_paths[0])["revision"] == "stale"
        assert index_generation.load_index(faiss_paths[0], FakeEmbeddings(size=8)).index.ntotal == 2
        assert index_generation.read_encoder(faiss_paths[0])["revision"] == "minilm1"


class TestTheTrainerKeysItsEmbeddingsByRevision:
    """train_importance_probe.embed_split caches e5-large embeddings of the gold
    set. Keyed without the revision, a retrain after refs/main moved would read
    the old revision's embeddings back and record the new revision."""

    def test_another_revision_is_another_cache_file(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "scripts"))
        import train_importance_probe as trainer
        gold = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "filter_gold.jsonl")
        rows = [{"headline": "Harga minyak naik", "body_head": "Harga minyak dunia naik."}]
        a = trainer._embed_cache_path(E5, "rev-a", gold, rows, rows)
        assert a == trainer._embed_cache_path(E5, "rev-a", gold, rows, rows)
        assert a != trainer._embed_cache_path(E5, "rev-b", gold, rows, rows)
