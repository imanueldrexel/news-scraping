"""NLI scoring of a hypothesis against quoted premises (SYS-198 #428, ADR-024).

`best_verdict(scorer, premises, hypothesis)` pairs the hypothesis with every
premise sentence (and every two adjacent sentences, which a sentence of an arc
often joins) and returns the pair the model finds most entailed. The model sits
behind `Scorer`, so tests and replays inject a stub and never load one;
`HfScorer` is the real one, loaded on first use -- nothing at import time.

Shadow only: a missing model, a failed load or a failed batch is "no verdict"
(None), never an exception into the edition.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, Tuple

from newscrawler.core.causal_check import sentences

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_PREMISES = 60          # pairs scored per hypothesis; a story's quotes are a few dozen sentences
MAX_LENGTH = 256
BATCH = 16


@dataclass(frozen=True)
class NliVerdict:
    p_entail: float
    p_neutral: float
    p_contradict: float
    premise: str
    revision: str


class Scorer(Protocol):
    revision: str

    def score(self, pairs: Sequence[Tuple[str, str]]) -> List[Tuple[float, float, float]]:
        """(premise, hypothesis) pairs -> (p_entail, p_neutral, p_contradict) each."""


def premise_units(texts: Sequence[str]) -> List[str]:
    """Each text's sentences and its adjacent sentence pairs, in order, de-duplicated, at most MAX_PREMISES."""
    units: List[str] = []
    seen = set()
    for text in texts:
        sents = [s.strip() for s in sentences(text) if s.strip()]
        for i, s in enumerate(sents):
            for unit in (s, f"{s} {sents[i + 1]}" if i + 1 < len(sents) else None):
                if unit and unit not in seen:
                    seen.add(unit)
                    units.append(unit)
    return units[:MAX_PREMISES]


def best_verdict(scorer: Optional[Scorer], premises: Sequence[str], hypothesis: str) -> Optional[NliVerdict]:
    """The most entailed (premise unit, hypothesis) pair, or None: no scorer, nothing to pair, or a failure."""
    if scorer is None or not hypothesis.strip():
        return None
    units = premise_units(premises)
    if not units:
        return None
    try:
        scores = scorer.score([(u, hypothesis) for u in units])
    except Exception as e:  # noqa: BLE001 -- shadow: a model failure is "no verdict", never the edition's failure
        logger.warning(f"NLI scoring failed: {type(e).__name__}: {e}")
        return None
    if len(scores) != len(units):
        logger.warning(f"NLI scorer returned {len(scores)} scores for {len(units)} pairs")
        return None
    best = max(range(len(units)), key=lambda i: scores[i][0])
    e, n, c = scores[best]
    return NliVerdict(float(e), float(n), float(c), units[best], scorer.revision)


class HfScorer:
    """A Hugging Face sequence-classification NLI model; loaded on the first `score` call."""

    def __init__(self, model_name: str, device: Optional[str] = None):
        self.model_name = model_name
        self.revision = model_name          # replaced by name@commit once loaded
        self._device = device
        self._tokenizer = None
        self._model = None
        self._order = None                  # indexes of (entailment, neutral, contradiction) in the logits

    def _load(self) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        self._device = self._device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model.to(self._device).eval()
        labels = {int(i): str(name).lower() for i, name in self._model.config.id2label.items()}
        try:
            self._order = [next(i for i, name in labels.items() if name.startswith(prefix))
                           for prefix in ("entail", "neutral", "contradict")]
        except StopIteration:
            raise ValueError(f"{self.model_name}: labels {labels} are not entailment/neutral/contradiction")
        commit = getattr(self._model.config, "_commit_hash", None)
        self.revision = f"{self.model_name}@{commit[:10]}" if commit else self.model_name

    def score(self, pairs: Sequence[Tuple[str, str]]) -> List[Tuple[float, float, float]]:
        import torch
        if self._model is None:
            self._load()
        out: List[Tuple[float, float, float]] = []
        for start in range(0, len(pairs), BATCH):
            chunk = pairs[start:start + BATCH]
            enc = self._tokenizer([p for p, _ in chunk], [h for _, h in chunk], truncation=True,
                                  max_length=MAX_LENGTH, padding=True, return_tensors="pt").to(self._device)
            with torch.no_grad():
                probs = torch.softmax(self._model(**enc).logits.float(), dim=-1).cpu().tolist()
            out += [tuple(row[i] for i in self._order) for row in probs]
        return out
