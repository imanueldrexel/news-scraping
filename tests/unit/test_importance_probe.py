"""SYS-37 (#121): the probe module (weights + sidecar, softmax, validation) and
the trainer's gate arithmetic. Offline: no embedding model, synthetic weights.
The probe is trained and evaluated but not yet wired into the live filter
(below its gates on 2026-09-21); these tests guard the parts that do not depend
on that decision so the next attempt starts from something that holds."""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

from newscrawler.core.filter_rubric import TOPICS, TOPIC_SOFT  # noqa: E402
from newscrawler.core.importance_probe import (  # noqa: E402
    PROBE_BODY_CHARS, PROBE_MAX_WORDS, PROBE_SIDECAR, PROBE_WEIGHTS, ImportanceProbe, ProbeArtifactError,
    build_check_text, embed_for_probe, encoder_prefix, truncate_for_probe,
)
from train_importance_probe import GATES, choose_threshold, gate_metrics, gates_pass, live_decision, topic_of  # noqa: E402

DIM = 8
rng = np.random.default_rng(0)
COEF = rng.normal(size=(len(TOPICS), DIM))
INTERCEPT = rng.normal(size=len(TOPICS))


def _write_artifact(directory, coef=COEF, intercept=INTERCEPT, classes=None, sidecar_extra=None, model="paraphrase-multilingual-MiniLM-L12-v2"):
    classes = list(TOPICS) if classes is None else classes
    np.savez(os.path.join(directory, PROBE_WEIGHTS), coef=coef, intercept=intercept, classes=np.array(classes))
    sidecar = {"embedding_model": model, "classes": classes, "soft_threshold": 0.5}
    sidecar.update(sidecar_extra or {})
    with open(os.path.join(directory, PROBE_SIDECAR), "w", encoding="utf-8") as f:
        json.dump(sidecar, f)


class TestTextPreparation:
    def test_check_text_is_title_plus_body_head_or_title_alone(self):
        assert build_check_text("Judul", "x" * 700) == "Judul " + "x" * PROBE_BODY_CHARS
        assert build_check_text("Judul", None) == "Judul"
        assert build_check_text("  Judul ", "  ") == "Judul"
        assert build_check_text(None, None) == ""

    def test_truncation_matches_the_old_score_snippet(self):
        assert truncate_for_probe(" ".join(["w"] * 500)).count("w") == PROBE_MAX_WORDS
        assert truncate_for_probe("  a   b \n c ") == "a b c"

    def test_e5_prefix_is_part_of_the_encoder_contract_and_minilm_has_none(self):
        # SYS-47: an E5 model expects "query: " on every input; the trainer and
        # the runtime both go through embed_for_probe(model_name=...) so neither
        # can forget it. MiniLM gets the bare text.
        assert encoder_prefix("intfloat/multilingual-e5-base") == "query: "
        assert encoder_prefix("paraphrase-multilingual-MiniLM-L12-v2") == ""

        class FakeModel:
            def __init__(self): self.seen = None
            def encode(self, texts, **kw):
                self.seen = list(texts)
                return np.ones((len(texts), 4))

        m = FakeModel()
        embed_for_probe(m, ["Judul  satu", "Judul dua"], model_name="intfloat/multilingual-e5-base")
        assert m.seen == ["query: Judul satu", "query: Judul dua"]
        embed_for_probe(m, ["Judul satu"], model_name="paraphrase-multilingual-MiniLM-L12-v2")
        assert m.seen == ["Judul satu"]
        embed_for_probe(m, ["Judul satu"])
        assert m.seen == ["Judul satu"]


class TestImportanceProbe:
    def test_softmax_matches_sklearn_predict_proba(self):
        from sklearn.linear_model import LogisticRegression
        X = rng.normal(size=(200, DIM))
        y = rng.integers(0, len(TOPICS), size=200)
        clf = LogisticRegression(max_iter=2000).fit(X, [TOPICS[i] for i in y])
        order = [list(clf.classes_).index(c) for c in TOPICS]
        probe = ImportanceProbe(clf.coef_[order], clf.intercept_[order], list(TOPICS), 0.5)
        np.testing.assert_allclose(probe.predict_proba(X), clf.predict_proba(X)[:, order], atol=1e-9)

    def test_decide_returns_gate_topic_confidence_and_p_soft(self):
        probe = ImportanceProbe(COEF, INTERCEPT, list(TOPICS), 0.5)
        row = np.full(len(TOPICS), 0.01)
        row[TOPICS.index(TOPIC_SOFT)] = 0.70
        row[TOPICS.index("markets")] = 0.19
        is_news, topic, conf, p_soft = probe.decide(row)
        assert (is_news, topic, p_soft) == (False, "markets", 0.70) and abs(conf - 0.19) < 1e-12
        row[TOPICS.index(TOPIC_SOFT)] = 0.30
        assert probe.decide(row)[0] is True

    def test_threshold_is_strict_less_than(self):
        probe = ImportanceProbe(COEF, INTERCEPT, list(TOPICS), 0.5)
        row = np.zeros(len(TOPICS)); row[TOPICS.index(TOPIC_SOFT)] = 0.5
        assert probe.decide(row)[0] is False

    def test_rejects_wrong_classes_shapes_and_threshold(self):
        with pytest.raises(ProbeArtifactError):
            ImportanceProbe(COEF, INTERCEPT, list(reversed(TOPICS)), 0.5)
        with pytest.raises(ProbeArtifactError):
            ImportanceProbe(COEF[:-1], INTERCEPT, list(TOPICS), 0.5)
        with pytest.raises(ProbeArtifactError):
            ImportanceProbe(COEF, INTERCEPT, list(TOPICS), 1.0)
        with pytest.raises(ProbeArtifactError):
            ImportanceProbe(COEF, INTERCEPT, list(TOPICS), 0.5).predict_proba(np.zeros((2, DIM + 1)))

    def test_load_round_trip_and_every_mismatch_is_a_hard_failure(self, tmp_path):
        d = str(tmp_path)
        with pytest.raises(ProbeArtifactError, match="missing"):
            ImportanceProbe.load(d)
        _write_artifact(d)
        probe = ImportanceProbe.load(d)
        assert probe.dim == DIM and probe.soft_threshold == 0.5 and probe.classes == list(TOPICS)
        assert ImportanceProbe.load(d, soft_threshold=0.3).soft_threshold == 0.3
        with pytest.raises(ProbeArtifactError, match="trained on"):
            ImportanceProbe.load(d, expected_model_name="some-other-model")
        _write_artifact(d, model="other")
        with pytest.raises(ProbeArtifactError, match="trained on"):
            ImportanceProbe.load(d)
        _write_artifact(d, sidecar_extra={"classes": list(reversed(TOPICS))})
        with pytest.raises(ProbeArtifactError, match="disagree"):
            ImportanceProbe.load(d)
        _write_artifact(d, sidecar_extra={"soft_threshold": None})
        with pytest.raises(ProbeArtifactError, match="soft_threshold"):
            ImportanceProbe.load(d)


def _rows(spec):
    """spec: list of (is_news, topic, stratum, category)."""
    return [{"is_news": n, "topic": t, "stratum": s, "category": c, "headline": f"h{i}"} for i, (n, t, s, c) in enumerate(spec)]


def _probs(p_soft_list, news_topic="markets"):
    out = np.zeros((len(p_soft_list), len(TOPICS)))
    for i, p in enumerate(p_soft_list):
        out[i, TOPICS.index(TOPIC_SOFT)] = p
        out[i, TOPICS.index(news_topic)] = 1 - p
    return out


class TestGateArithmetic:
    def test_live_decision_applies_the_category_deny_before_the_probe(self):
        probs = _probs([0.1, 0.1, 0.9])
        pred = live_decision(probs, ["hiburan", "bisnis", "bisnis"], 0.5, TOPICS.index(TOPIC_SOFT))
        assert pred.tolist() == [False, True, False]

    def test_topic_of_never_returns_soft(self):
        probs = _probs([0.9])
        assert topic_of(probs, list(TOPICS))[0] == "markets"

    def test_gate_metrics_recall_precision_and_topic_accuracy(self):
        rows = _rows([
            (True, "markets", "finance_reject", "bisnis"),     # kept, right topic
            (True, "markets", "finance_reject", "bisnis"),     # missed (p_soft high)
            (False, "soft", "mixed_bucket", "news"),           # kept -> precision hit on mixed
            (True, "corporate", "mixed_bucket", "news"),       # kept, wrong topic
            (False, "soft", "soft_category", "hiburan"),       # denied by category
        ])
        probs = _probs([0.1, 0.9, 0.2, 0.2, 0.1])
        m = gate_metrics(rows, probs, 0.5, list(TOPICS))
        assert m["recall_finance"] == 0.5
        assert m["recall_general"] is None                     # no general-strata rows
        assert m["precision_mixed"] == 0.5
        assert m["precision_allow"] == 1.0                     # bisnis rows kept: 1 news of 1 kept
        assert m["topic_accuracy"] == pytest.approx(2 / 3)     # 3 news rows, 2 predicted markets (1 right, corporate wrong, missed row counts on topic)
        assert m["per_stratum"]["soft_category"]["kept"] == 0
        ok, failures = gates_pass(m)
        assert not ok and any(f.startswith("recall_finance") for f in failures)

    def test_choose_threshold_prefers_the_widest_margin_and_falls_back_to_half(self):
        # Perfectly separable: soft rows at p_soft 0.9, news at 0.1; every tau in
        # (0.1, 0.9) passes, the widest slack is at a tau that keeps every metric
        # at 1.0 -- the first such tau on the grid is what the max picks.
        rows = _rows([(True, "markets", "finance_reject", "bisnis")] * 5 + [(True, "markets", "hard_news", "nasional")] * 5
                     + [(False, "soft", "mixed_bucket", "news")] * 5 + [(True, "markets", "mixed_bucket", "news")] * 5)
        probs = _probs([0.1] * 5 + [0.1] * 5 + [0.9] * 5 + [0.1] * 5)
        tau, m = choose_threshold(rows, probs, list(TOPICS))
        assert 0.1 < tau < 0.9 and gates_pass(m)[0]
        # Inseparable (every row at 0.5): nothing passes; 0.5 is reported, not shipped.
        tau, m = choose_threshold(rows, _probs([0.5] * 20), list(TOPICS))
        assert tau == 0.5 and not gates_pass(m)[0]

    def test_gates_are_the_ticket_plus_sys45(self):
        assert GATES == {"recall_finance": 0.95, "recall_general": 0.90, "precision_mixed": 0.90,
                         "precision_allow": 0.90, "topic_accuracy": 0.80}
