"""OPS-32 (#193): load a model from the local Hugging Face cache, without huggingface.co.

Given a Hub id, sentence-transformers and transformers query the Hub on every load,
even when the model is in the local cache. On 2026-09-27 a DNS outage started at
07:21. WARTAEKONOMI's worker was killed on timeout, and every respawn then spent
~3.5 min failing on `huggingface.co ... getaddrinfo failed` with both models on
disk. 27 of 28 sources were lost.

HF_HUB_OFFLINE does not fix this with transformers 4.57.3: its
`_patch_mistral_regex` calls `huggingface_hub.model_info()` for every tokenizer
with a vocabulary over 100k (MiniLM-L12 multilingual, e5-large), and in offline
mode that call raises instead of being skipped. Only a local *directory* skips it.
So a cached model is loaded from its snapshot directory, which touches no network
at all and also pins the exact files the probe was trained against.

The cache layout is the one huggingface_hub documents:
`<cache>/models--<org>--<name>/refs/main` names a directory under `snapshots/`.
A model that is not cached is returned as its Hub id and downloaded as before.

SYS-61 (#198): "pinned to the cached snapshot" holds only while refs/main does
not move, and any online load by Hub id moves it when upstream has. So the
probe's sidecar and each FAISS index record the revision they were built with
(cached_revision), and a load that resolves another revision refuses to start
(EncoderRevisionError, ProbeArtifactError) instead of embedding in a new space.
"""
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# A snapshot is usable when sentence-transformers can build the model from it.
_SNAPSHOT_MARKERS = ("modules.json", "config.json")


def hub_cache_dir() -> str:
    """The Hub cache directory, resolved the way huggingface_hub resolves it."""
    for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(var):
            return os.path.expanduser(os.environ[var])
    hf_home = os.environ.get("HF_HOME") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "huggingface")
    return os.path.join(os.path.expanduser(hf_home), "hub")


class EncoderRevisionError(RuntimeError):
    """The encoder resolves to a revision other than the one the vectors or the
    probe were built with: embedding with it would compare vectors from two
    different spaces, silently."""


def _cached(model: str, cache_dir: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """(snapshot directory, revision) of Hub model `model` in the local cache,
    or None when it is not cached. sentence-transformers resolves a bare name
    ("all-MiniLM-L6-v2") to its own org, so that is tried too."""
    cache_dir = cache_dir or hub_cache_dir()
    for repo_id in ([model] if "/" in model else [model, "sentence-transformers/" + model]):
        folder = os.path.join(cache_dir, "models--" + repo_id.replace("/", "--"))
        try:
            with open(os.path.join(folder, "refs", "main"), encoding="utf-8") as f:
                revision = f.read().strip()
        except OSError:
            continue
        snapshot = os.path.join(folder, "snapshots", revision)
        if revision and any(os.path.isfile(os.path.join(snapshot, m)) for m in _SNAPSHOT_MARKERS):
            return snapshot, revision
    return None


def cached_snapshot(model: str, cache_dir: Optional[str] = None) -> Optional[str]:
    """The local snapshot directory of Hub model `model`, or None when it is not
    cached."""
    cached = _cached(model, cache_dir)
    return cached[0] if cached else None


def cached_revision(model: str, cache_dir: Optional[str] = None) -> Optional[str]:
    """SYS-61: the revision (commit hash) resolve_model loads for Hub model
    `model` -- the one refs/main names -- or None when it is not cached. Call it
    after the model is loaded, so a model just downloaded has a revision too."""
    cached = _cached(model, cache_dir)
    return cached[1] if cached else None


def check_revision(model: str, recorded: Optional[str], loaded: Optional[str], built: str) -> None:
    """SYS-61: raise EncoderRevisionError unless the revision of `model` this
    process `loaded` (cached_revision, read right after the load) is `recorded`,
    the one `built` (the probe, a FAISS index) was made with."""
    if loaded != recorded:
        raise EncoderRevisionError(
            "%s was built with %s revision %s, but the cache now resolves it to %s. Embedding with "
            "that would put new vectors in a different space. Point refs/main back at %s, or "
            "retrain / rebuild for the new revision (OPERATIONS.md, \"pick up a newer revision\")."
            % (built, model, recorded, loaded or "no cached revision", recorded))


def resolve_model(model: str, cache_dir: Optional[str] = None) -> str:
    """What to pass to SentenceTransformer / HuggingFaceEmbeddings for `model`:
    a local directory as is, a cached Hub model as its snapshot directory, and
    anything else as the Hub id (downloaded, which needs the network)."""
    if os.path.isdir(model):
        return model
    snapshot = cached_snapshot(model, cache_dir)
    if snapshot:
        return snapshot
    logger.warning("%s is not in the local Hugging Face cache (%s); loading it from huggingface.co",
                   model, cache_dir or hub_cache_dir())
    return model
