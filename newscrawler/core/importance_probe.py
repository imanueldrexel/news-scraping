"""SYS-37 (#121): the importance probe -- two logistic-regression heads over the
`intfloat/multilingual-e5-large` embedding of title + body[:500] -- and the
text/embedding helpers that give the trainer and the runtime the same input by
construction.

Status: LIVE since 2026-09-22 (`e44de43`). This probe is the one news-worthy
decision in the pipeline. The artifact is committed in newscrawler/core/models/,
`SemanticImportanceFilter` loads exactly the encoder its sidecar names, and the
cosine-vs-INTERESTS score it replaced is deleted, not disabled. tau = 0.39, with
an owner-accepted +/-0.02 tolerance on the five gates (2026-09-22). SOFT_THRESHOLD
is the only runtime knob; anything else is a retrain.

The encoder is NOT the MiniLM the FAISS store uses. Before SYS-47 (#143) the
probe was a single multinomial head over MiniLM, and on that input no shape
reached the gates (mixed-bucket precision 0.71 at finance recall 0.95; topic
accuracy 0.65) -- SYS-47 changed the input (e5-large, 1024-d, fetched bodies for
95% of the gold set) and split the head in two, which is what moved every gate
to its floor. The 2.2 GB e5-large download is therefore a runtime dependency of
the crawler, next to MiniLM.

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
PROBE_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"      # the FAISS/chunk embedding model; the old cosine filter's
DEFAULT_PROBE_ENCODER = "intfloat/multilingual-e5-base"        # SYS-47: what the probe trains and serves on (sidecar is authoritative)
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


def artifact_identity(directory: str = PROBE_DIR, soft_threshold: Optional[float] = None) -> dict:
    """DBT-34 (#150): who decided. Any verdict derived from the probe and cached
    to disk carries this block, and any script that acts on cached verdicts --
    `cleanup_soft_by_probe.py` deletes production articles on them -- compares it
    with the artifact committed now and refuses on a mismatch.

    `soft_threshold` is the EFFECTIVE tau, not the sidecar's: `constants.SOFT_THRESHOLD`
    overrides it for the live service, so passing it here is what makes an
    operating-point move visible to the comparison (DBT-37 #153). Pass what the
    filter was actually constructed with.

    `artifact_sha256` is the weights file itself, so a half-trained checkpoint or
    an artifact copied from an experiment branch is caught even when the encoder,
    the threshold and the gold hash all still agree."""
    weights = os.path.join(directory, PROBE_WEIGHTS)
    sidecar_path = os.path.join(directory, PROBE_SIDECAR)
    with open(sidecar_path, encoding="utf-8") as f:
        sidecar = json.load(f)
    return {
        "embedding_model": sidecar.get("embedding_model"),
        "soft_threshold": float(soft_threshold if soft_threshold is not None else sidecar.get("soft_threshold")),
        "gold_sha256": sidecar.get("gold_sha256"),
        "trained_at": sidecar.get("trained_at"),
        "artifact_sha256": sha256_of_file(weights),
    }


class ProbeArtifactError(RuntimeError):
    """The committed probe is missing or does not match the code that loads it.
    Raised at CrawlerServiceImpl.__init__ -- never a silent accept-all/reject-all."""


class ImportanceProbe:
    """Two linear heads over the same embedding (SYS-47: a single balanced
    13-class softmax cannot be both a calibrated gate and a topic classifier):

      gate  -- binary logistic regression, P(soft) = sigmoid(x . g + b_g);
               the row is news iff P(soft) < soft_threshold.
      topic -- 13-class multinomial logistic regression; the topic is the
               argmax over the 12 NEWS classes, its confidence the softmax mass
               of that class renormalised over the news classes.

    Loaded from PROBE_DIR; validated against the code's class list, the
    encoder name in the sidecar and the embedding dimension."""

    def __init__(self, gate_coef: np.ndarray, gate_intercept: float, topic_coef: np.ndarray, topic_intercept: np.ndarray,
                 classes: List[str], soft_threshold: float, sidecar: Optional[dict] = None):
        if list(classes) != list(TOPICS):
            raise ProbeArtifactError(f"probe classes {list(classes)} != filter_rubric.TOPICS {list(TOPICS)}")
        gate_coef = np.asarray(gate_coef, dtype=np.float64).reshape(-1)
        topic_coef = np.asarray(topic_coef, dtype=np.float64)
        topic_intercept = np.asarray(topic_intercept, dtype=np.float64)
        if topic_coef.ndim != 2 or topic_coef.shape[0] != len(classes) or topic_intercept.shape != (len(classes),):
            raise ProbeArtifactError(f"topic weights have shape {topic_coef.shape}/{topic_intercept.shape} for {len(classes)} classes")
        if gate_coef.shape != (topic_coef.shape[1],):
            raise ProbeArtifactError(f"gate weights have shape {gate_coef.shape}, topic dim is {topic_coef.shape[1]}")
        if not (0.0 < soft_threshold < 1.0):
            raise ProbeArtifactError(f"soft_threshold {soft_threshold!r} is not in (0, 1)")
        self.gate_coef = gate_coef
        self.gate_intercept = float(np.asarray(gate_intercept).reshape(-1)[0])
        self.topic_coef = topic_coef
        self.topic_intercept = topic_intercept
        self.classes = list(classes)
        self.soft_index = self.classes.index(TOPIC_SOFT)
        self.news_indices = [i for i, c in enumerate(self.classes) if c != TOPIC_SOFT]
        self.soft_threshold = float(soft_threshold)
        self.sidecar = sidecar or {}

    @property
    def dim(self) -> int:
        return self.topic_coef.shape[1]

    @classmethod
    def load(cls, directory: str = PROBE_DIR, expected_model_name: Optional[str] = None,
             soft_threshold: Optional[float] = None) -> "ImportanceProbe":
        weights_path = os.path.join(directory, PROBE_WEIGHTS)
        sidecar_path = os.path.join(directory, PROBE_SIDECAR)
        for path in (weights_path, sidecar_path):
            if not os.path.exists(path):
                raise ProbeArtifactError(
                    f"probe artifact missing: {path} -- run scripts/train_importance_probe.py (SYS-37)")
        with open(sidecar_path, encoding="utf-8") as f:
            sidecar = json.load(f)
        if not sidecar.get("embedding_model"):
            raise ProbeArtifactError("sidecar has no embedding_model")
        if expected_model_name is not None and sidecar["embedding_model"] != expected_model_name:
            raise ProbeArtifactError(
                f"probe was trained on {sidecar['embedding_model']!r}, the filter loads {expected_model_name!r}")
        with np.load(weights_path) as w:
            missing = {"gate_coef", "gate_intercept", "topic_coef", "topic_intercept", "classes"} - set(w.files)
            if missing:
                raise ProbeArtifactError(f"probe weights lack {sorted(missing)}")
            gate_coef, gate_intercept = w["gate_coef"], w["gate_intercept"]
            topic_coef, topic_intercept = w["topic_coef"], w["topic_intercept"]
            classes = [str(c) for c in w["classes"]]
        if list(classes) != list(sidecar.get("classes", [])):
            raise ProbeArtifactError("probe weights and sidecar disagree on the class list")
        threshold = soft_threshold if soft_threshold is not None else sidecar.get("soft_threshold")
        if threshold is None:
            raise ProbeArtifactError("sidecar has no soft_threshold")
        return cls(gate_coef, gate_intercept, topic_coef, topic_intercept, classes, float(threshold), sidecar)

    @property
    def encoder_name(self) -> str:
        return self.sidecar.get("embedding_model", "")

    def _check(self, embeddings: np.ndarray) -> np.ndarray:
        x = np.asarray(embeddings, dtype=np.float64)
        if x.ndim == 1:
            x = x[None, :]
        if x.shape[1] != self.dim:
            raise ProbeArtifactError(f"embedding dim {x.shape[1]} != probe dim {self.dim}")
        return x

    def p_soft(self, embeddings: np.ndarray) -> np.ndarray:
        x = self._check(embeddings)
        z = x @ self.gate_coef + self.gate_intercept
        return 1.0 / (1.0 + np.exp(-z))

    def topic_proba(self, embeddings: np.ndarray) -> np.ndarray:
        """Softmax over all 13 topic-head classes, shape (n, 13)."""
        x = self._check(embeddings)
        logits = x @ self.topic_coef.T + self.topic_intercept
        logits -= logits.max(axis=1, keepdims=True)
        probs = np.exp(logits)
        probs /= probs.sum(axis=1, keepdims=True)
        return probs

    def predict(self, embeddings: np.ndarray):
        """List of (is_news, topic, topic_confidence, p_soft) per row."""
        ps = self.p_soft(embeddings)
        tp = self.topic_proba(embeddings)
        out = []
        for p, row in zip(ps, tp):
            news = row[self.news_indices]
            best = int(news.argmax())
            confidence = float(news[best] / news.sum()) if news.sum() > 0 else 0.0
            out.append((bool(p < self.soft_threshold), self.classes[self.news_indices[best]], confidence, float(p)))
        return out
