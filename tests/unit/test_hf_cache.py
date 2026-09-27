"""OPS-32 (#193): the crawler must build from the local Hugging Face cache when
huggingface.co cannot be reached. On 2026-09-27 every worker respawn failed on
`huggingface.co ... getaddrinfo failed` with both models on disk, and 27 of 28
sources were lost. A cached model is loaded from its snapshot directory, which
is the one form transformers 4.57.3 loads without calling model_info().
"""
import os
from unittest.mock import patch

import pytest

from newscrawler.core.utils import hf_cache


def _cache(tmp_path, repo_id, revision="abc123", files=("modules.json", "config.json"), ref=True):
    folder = tmp_path / ("models--" + repo_id.replace("/", "--"))
    snap = folder / "snapshots" / revision
    snap.mkdir(parents=True)
    for name in files:
        (snap / name).write_text("{}")
    if ref:
        (folder / "refs").mkdir()
        (folder / "refs" / "main").write_text(revision + "\n")
    return str(snap)


class TestResolveModel:
    def test_a_cached_model_resolves_to_its_snapshot_directory(self, tmp_path):
        snap = _cache(tmp_path, "intfloat/multilingual-e5-large")
        assert hf_cache.resolve_model("intfloat/multilingual-e5-large", str(tmp_path)) == snap

    def test_a_bare_sentence_transformers_name_is_found_under_its_org(self, tmp_path):
        snap = _cache(tmp_path, "sentence-transformers/all-MiniLM-L6-v2")
        assert hf_cache.resolve_model("all-MiniLM-L6-v2", str(tmp_path)) == snap

    def test_the_snapshot_main_points_at_is_the_one_used(self, tmp_path):
        """MiniLM's cache holds two snapshots; the Hub's `main` picks one."""
        _cache(tmp_path, "org/m", revision="new")
        old = tmp_path / "models--org--m" / "snapshots" / "old"
        old.mkdir()
        (old / "modules.json").write_text("{}")
        assert hf_cache.resolve_model("org/m", str(tmp_path)).endswith(os.path.join("snapshots", "new"))

    @pytest.mark.parametrize("how", ["no refs/main", "empty snapshot", "not there"])
    def test_an_incomplete_or_missing_model_stays_a_hub_id(self, tmp_path, how, caplog):
        if how == "no refs/main":
            _cache(tmp_path, "org/m", ref=False)
        elif how == "empty snapshot":
            _cache(tmp_path, "org/m", files=())
        assert hf_cache.resolve_model("org/m", str(tmp_path)) == "org/m"
        assert "not in the local Hugging Face cache" in caplog.text

    def test_a_local_directory_is_used_as_is(self, tmp_path):
        assert hf_cache.resolve_model(str(tmp_path)) == str(tmp_path)

    def test_the_cache_dir_follows_the_hub_env_vars(self, monkeypatch, tmp_path):
        for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("HF_HOME", str(tmp_path / "home"))
        assert hf_cache.hub_cache_dir() == str(tmp_path / "home" / "hub")
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "direct"))
        assert hf_cache.hub_cache_dir() == str(tmp_path / "direct")


class TestEveryCrawlerModelLoadGoesThroughTheCache:
    """The three places the pipeline builds a SentenceTransformer."""

    def test_the_faiss_embedding_model(self, monkeypatch):
        import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as fmod
        seen = {}
        monkeypatch.setattr(fmod, "resolve_model", lambda m: "LOCAL:" + m)
        monkeypatch.setattr(fmod, "HuggingFaceEmbeddings", lambda **kw: seen.update(kw) or object())
        monkeypatch.setattr(fmod.ChunkFAISSDatasource, "_load_or_create", lambda self, db: None)
        fmod.ChunkFAISSDatasource()
        assert seen["model_name"] == "LOCAL:" + fmod.EMBEDDING_MODEL_HF

    def test_the_probe_encoder_keeps_its_hub_name_for_the_prefix(self, monkeypatch):
        import newscrawler.core.importance_filter as imf
        loaded = []

        class _Model:
            def __init__(self, name):
                loaded.append(name)

            def get_sentence_embedding_dimension(self):
                return imf.ImportanceProbe.load(imf.PROBE_DIR).dim

        monkeypatch.setattr(imf, "resolve_model", lambda m: "LOCAL:" + m)
        monkeypatch.setattr(imf, "SentenceTransformer", _Model)
        f = imf.SemanticImportanceFilter()
        assert loaded == ["LOCAL:intfloat/multilingual-e5-large"]
        assert f.model_name == "intfloat/multilingual-e5-large"

    def test_the_newsletter_model(self, monkeypatch):
        import sentence_transformers
        import newscrawler.core.newsletter_generator as ng
        loaded = []

        class _Model:
            def __init__(self, name):
                loaded.append(name)

            def encode(self, texts, **kw):
                return [[0.0]] * len(texts)

        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", _Model)
        with patch.object(hf_cache, "resolve_model", lambda m: "LOCAL:" + m):
            gen = ng.NewsletterGenerator.__new__(ng.NewsletterGenerator)
            gen._embedding_model = None
            gen._encode(["x"])
        assert loaded == ["LOCAL:" + ng.EMBEDDING_MODEL_HF]
