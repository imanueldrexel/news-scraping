"""SYS-37 (#121): the importance probe -- a multinomial logistic regression over
the MiniLM embedding the pipeline already computes -- and the text/embedding
helpers that give the trainer and the runtime the same input by construction.

Status 2026-09-21: TRAINED AND EVALUATED, NOT WIRED INTO THE LIVE FILTER. On the
SYS-36 gold set no probe shape reaches the ticket's gates (best linear gate:
mixed-bucket precision 0.71 at finance recall 0.95; topic accuracy 0.65 against
labels whose inter-labeller topic agreement is 0.71) -- see the 2026-09-21
SYS-37 entry in EXPERIMENTS.md and the ticket. Per the ticket's rule the
artifact is not written and importance_filter.py keeps the cosine score until
the owner decides how the gates move. What is here is the part that does not
depend on that decision: scripts/train_importance_probe.py imports it.

The artifact is plain weights (.npz) + a JSON sidecar, not a pickle: the runtime
needs numpy, not a matching sklearn; the trainer asserts its softmax reproduces
sklearn's predict_proba before it writes anything. A missing or mismatched
artifact is a ProbeArtifactError, never a silent accept-all/reject-all.
"""
import hashlib
import json
import os
from typing import List, Optional, Sequence

import numpy as np
from sentence_transformers import SentenceTransformer

from newscrawler.core.filter_rubric import TOPICS, TOPIC_SOFT

# SYS-47 (#143): the probe's encoder is a parameter -- the FAISS store stays on
# MiniLM whatever the probe uses. The sidecar records which one trained the
# weights and the runtime refuses to load them behind a different one. E5
# models expect an instruction prefix on every input ("query: " for
# classification/symmetric use); it is part of the encoder's contract, so it
# is applied here for training and serving alike.
PROBE_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
ENCODER_PREFIX = {
    "intfloat/multilingual-e5-base": "query: ",
    "intfloat/multilingual-e5-small": "query: ",
    "intfloat/multilingual-e5-large": "query: ",
}
PROBE_BODY_CHARS = 500     # the body head the service has always scored (title + body[:500])
PROBE_MAX_WORDS = 200      # the old _score's snippet cut, kept so the trainer sees what the service sees
PROBE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
PROBE_WEIGHTS = "importance_probe.npz"
PROBE_SIDECAR = "importance_probe.json"
# SYS-37 fix 4: decisions with P(soft) inside this band are counted per run --
# the input to a possible LLM tie-break for the band only, not filed until the
# number exists.
UNCERTAIN_BAND = (0.35, 0.65)


def build_check_text(title: Optional[str], body: Optional[str]) -> str:
    """The text the filter scores: title + the first PROBE_BODY_CHARS of the
    body, or the title alone when there is no body (a headline-only sitemap
    row; the gold set's `has_body=false` rows)."""
    title = (title or "").strip()
    body = (body or "").strip()
    if body:
        return f"{title} {body[:PROBE_BODY_CHARS]}".strip()
    return title


def truncate_for_probe(text: str) -> str:
    return " ".join((text or "").split()[:PROBE_MAX_WORDS])


def encoder_prefix(model_name: str) -> str:
    return ENCODER_PREFIX.get(model_name, "")


def embed_for_probe(model: SentenceTransformer, texts: Sequence[str], batch_size: int = 64,
                    model_name: Optional[str] = None) -> np.ndarray:
    """L2-normalised embeddings of the truncated texts, shape (n, dim). The
    encoder's instruction prefix (E5) is applied from `model_name`; pass the
    name the model was loaded with -- the same one the sidecar records."""
    prefix = encoder_prefix(model_name or "")
    prepared = [prefix + truncate_for_probe(t) for t in texts]
    return np.asarray(
        model.encode(prepared, batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True,
                     show_progress_bar=False),
        dtype=np.float32,
    )


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ProbeArtifactError(RuntimeError):
    """The committed probe is missing or does not match the code that loads it.
    Raised at CrawlerServiceImpl.__init__ -- never a silent accept-all/reject-all."""


class ImportanceProbe:
    """Multinomial logistic regression over the MiniLM embedding: softmax(X W^T + b)
    over filter_rubric.TOPICS. Loaded from PROBE_DIR; validated against the
    code's class list, the embedding model name and dimension."""

    def __init__(self, coef: np.ndarray, intercept: np.ndarray, classes: List[str], soft_threshold: float,
                 sidecar: Optional[dict] = None):
        if list(classes) != list(TOPICS):
            raise ProbeArtifactError(f"probe classes {list(classes)} != filter_rubric.TOPICS {list(TOPICS)}")
        coef = np.asarray(coef, dtype=np.float64)
        intercept = np.asarray(intercept, dtype=np.float64)
        if coef.ndim != 2 or coef.shape[0] != len(classes) or intercept.shape != (len(classes),):
            raise ProbeArtifactError(f"probe weights have shape {coef.shape}/{intercept.shape} for {len(classes)} classes")
        if not (0.0 < soft_threshold < 1.0):
            raise ProbeArtifactError(f"soft_threshold {soft_threshold!r} is not in (0, 1)")
        self.coef = coef
        self.intercept = intercept
        self.classes = list(classes)
        self.soft_index = self.classes.index(TOPIC_SOFT)
        self.soft_threshold = float(soft_threshold)
        self.sidecar = sidecar or {}

    @property
    def dim(self) -> int:
        return self.coef.shape[1]

    @classmethod
    def load(cls, directory: str = PROBE_DIR, expected_model_name: str = PROBE_MODEL_NAME,
             soft_threshold: Optional[float] = None) -> "ImportanceProbe":
        weights_path = os.path.join(directory, PROBE_WEIGHTS)
        sidecar_path = os.path.join(directory, PROBE_SIDECAR)
        for path in (weights_path, sidecar_path):
            if not os.path.exists(path):
                raise ProbeArtifactError(
                    f"probe artifact missing: {path} -- run scripts/train_importance_probe.py (SYS-37)")
        with open(sidecar_path, encoding="utf-8") as f:
            sidecar = json.load(f)
        if sidecar.get("embedding_model") != expected_model_name:
            raise ProbeArtifactError(
                f"probe was trained on {sidecar.get('embedding_model')!r}, the filter loads {expected_model_name!r}")
        with np.load(weights_path) as w:
            coef, intercept, classes = w["coef"], w["intercept"], [str(c) for c in w["classes"]]
        if list(classes) != list(sidecar.get("classes", [])):
            raise ProbeArtifactError("probe weights and sidecar disagree on the class list")
        threshold = soft_threshold if soft_threshold is not None else sidecar.get("soft_threshold")
        if threshold is None:
            raise ProbeArtifactError("sidecar has no soft_threshold")
        return cls(coef, intercept, classes, float(threshold), sidecar)

    def predict_proba(self, embeddings: np.ndarray) -> np.ndarray:
        x = np.asarray(embeddings, dtype=np.float64)
        if x.ndim == 1:
            x = x[None, :]
        if x.shape[1] != self.dim:
            raise ProbeArtifactError(f"embedding dim {x.shape[1]} != probe dim {self.dim}")
        logits = x @ self.coef.T + self.intercept
        logits -= logits.max(axis=1, keepdims=True)
        probs = np.exp(logits)
        probs /= probs.sum(axis=1, keepdims=True)
        return probs

    def decide(self, probs_row: np.ndarray):
        """(is_news, topic, topic_confidence, p_soft) for one probability row.
        The topic is the best NEWS class even when the row is soft -- a caller
        that keeps a soft row anyway still gets a topic."""
        p_soft = float(probs_row[self.soft_index])
        news = np.array(probs_row, dtype=np.float64)
        news[self.soft_index] = -1.0
        best = int(news.argmax())
        return p_soft < self.soft_threshold, self.classes[best], float(probs_row[best]), p_soft
