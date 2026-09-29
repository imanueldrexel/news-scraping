#!/usr/bin/env python3
"""
SYS-37 (#121): train the importance probe -- two logistic-regression heads (a
binary soft-vs-news gate and a 13-class topic head) over the embedding named by
--encoder, `intfloat/multilingual-e5-large` for the committed artifact -- on the
SYS-36 gold set, evaluate it against the ticket's gates, and (only if every gate
passes) write the artifact the live filter loads.

The probe has been live since 2026-09-22; running this script rewrites what the
pipeline uses to decide every article, so a retrain is a deliberate act with a
re-measure and a re-verified artifact behind it (DBT-35 #151), not a routine
step. --encoder defaults to the encoder the committed sidecar names (DBT-49
#203): the sidecar is authoritative, so a retrain on another encoder changes
the encoder production embeds with. Pass --encoder only to do that on purpose;
the run then says so in a WARNING.

What it does, in order:
  1. Load tests/fixtures/filter_gold.jsonl. Build each row's text exactly as the
     service will (importance_probe.build_check_text: title + body[:500], or the
     title alone), embed with importance_probe.embed_for_probe (same model, same
     truncation, same normalisation the runtime will use).
  2. Fit sklearn LogisticRegression (multinomial, class-weighted, fixed seed) on
     the `train` split over the 13 classes of filter_rubric.TOPICS.
  3. Choose the soft threshold on 5-fold cross-validated probabilities of the
     TRAIN split (never on test): the tau that satisfies every gate with the
     largest margin. The full live decision (category gate + probe) is what is
     scored, so `deny` rows are rejected before the probe here too.
  4. Report on the `test` split: gate recall per stratum group, gate precision on
     the mixed buckets and on the allow-set categories (SYS-45), topic accuracy
     and macro-F1 on news rows, the confusion matrix, the uncertain-band size,
     and a +/-0.05 note (the labels' measured noise floor, SYS-46).
  5. If every gate holds: write newscrawler/core/models/importance_probe.npz
     (coef, intercept, classes) + importance_probe.json (gold sha256, model,
     versions, threshold, metrics). The npz softmax is asserted equal to
     sklearn's predict_proba first. Below any gate: print the numbers and exit 2
     without writing -- do not lower a gate to make it pass.

Gates (the ticket's Done-when + SYS-45 #140, owner-approved 2026-09-21):
  gate recall >= 0.95 on the finance-section strata (finance_reject / _saved / _pending, news rows)
  gate recall >= 0.90 on the general-news strata (hard_news, econ_politics_boundary, religion_boundary)
  gate precision >= 0.90 on the mixed buckets (mixed_bucket, viva_general)
  gate precision >= 0.90 on allow-set categories (category_gate == "allow")
  topic accuracy >= 0.80 on news rows

Before SYS-47 (#143), on a single multinomial head over the MiniLM embedding, no
probe shape reached these gates (EXPERIMENTS.md, 2026-09-21 SYS-37 entry;
scripts/experiments/probe_design_sweep.py has the design sweep). Changing the
input -- e5-large plus fetched bodies -- and splitting the head in two is what
moved every gate to its floor, so re-running this on MiniLM will fail the gates
and correctly refuse to write.

Usage:
    python scripts/train_importance_probe.py                 # train, evaluate, write if gates pass
    python scripts/train_importance_probe.py --no-write      # evaluate only
    python scripts/train_importance_probe.py --backfill --dry-run   # topics for existing articles: counts + sample
    python scripts/train_importance_probe.py --backfill             # ... write them (owner-approved, backup first)
"""
import argparse
import collections
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from newscrawler.core.filter_rubric import TOPICS, TOPIC_SOFT  # noqa: E402
from newscrawler.core.importance_filter import category_gate  # noqa: E402
from newscrawler.core.importance_probe import (  # noqa: E402
    DEFAULT_PROBE_ENCODER, PROBE_DIR, PROBE_SIDECAR, PROBE_WEIGHTS, UNCERTAIN_BAND,
    ImportanceProbe, build_check_text, embed_for_probe, sha256_of_file,
)
from newscrawler.core.utils.hf_cache import cached_revision, resolve_model  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "filter_gold.jsonl")
SEED = 20260921
NOISE_FLOOR = 0.05   # SYS-46: three measurements of the labels' is_news disagreement, all ~5%

FINANCE_STRATA = ("finance_reject", "finance_saved", "finance_pending")
GENERAL_STRATA = ("hard_news", "econ_politics_boundary", "religion_boundary")
MIXED_STRATA = ("mixed_bucket", "viva_general")
GATES = {
    "recall_finance": 0.95,
    "recall_general": 0.90,
    "precision_mixed": 0.90,
    "precision_allow": 0.90,
    "topic_accuracy": 0.80,
}
# Owner decision 2026-09-22 (SYS-37 #121, after SYS-47 #143): the floors above
# stay as written, and a measured value is accepted when it is within this
# tolerance of its floor. The gold set's 763 single-labeller test rows cannot
# resolve less than this (SE +/-0.015 on a recall of 0.95 over ~200 rows;
# ~4% run-to-run label disagreement): e5-large reads recall_finance 0.946
# against the 0.95 floor -- one row. A real regression (0.02 or more) still
# fails; the floors are not rewritten.
GATE_TOLERANCE = 0.02
# The threshold only moves the gate; topic accuracy is an argmax over the news
# classes and does not depend on tau, so it is evaluated once, not searched.
TAU_GATES = {k: v for k, v in GATES.items() if k != "topic_accuracy"}
GATE_C_GRID = (0.25, 0.5, 1.0, 2.0, 4.0)
TOPIC_C_GRID = (1.0, 2.0, 4.0, 8.0, 16.0)


# ── data ─────────────────────────────────────────────────────────────────────
def read_gold(path: str = GOLD_PATH) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def texts_of(rows: Sequence[dict]) -> List[str]:
    return [build_check_text(r["headline"], r.get("body_head")) for r in rows]


EMBED_CACHE_DIR = os.path.join(REPO_ROOT, "scripts", "experiments")


def _embed_cache_path(encoder: str, revision: str, gold_path: str, train: Sequence[dict], test: Sequence[dict]) -> str:
    import hashlib
    key = hashlib.sha256((encoder + revision + sha256_of_file(gold_path)
                          + "".join(texts_of(train) + texts_of(test))).encode()).hexdigest()[:16]
    return os.path.join(EMBED_CACHE_DIR, f"probe_train_{key}.npz")


def embed_split(encoder: str, gold_path: str, train: Sequence[dict], test: Sequence[dict]):
    """(X_train, X_test, revision): both splits embedded with the encoder the
    crawl resolves (hf_cache.resolve_model), and the revision that is.

    Cached next to the experiment scripts (gitignored) by (encoder, revision,
    gold sha256, the exact texts) -- e5-large takes ~10 min on CPU and the gold
    set changes far less often than the head or the gates. SYS-61 (#198): the
    revision is in the key, so a cache built with another revision is never
    read back as this one's, and the sidecar records it."""
    revision = cached_revision(encoder)
    if revision:
        cache = _embed_cache_path(encoder, revision, gold_path, train, test)
        if os.path.exists(cache):
            with np.load(cache) as z:
                logger.info("embeddings from cache %s (revision %s)", os.path.basename(cache), revision[:12])
                return z["X_train"], z["X_test"], revision
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(resolve_model(encoder))
    # After the load: a model not cached before has just been downloaded.
    revision = cached_revision(encoder)
    if not revision:
        raise RuntimeError(f"{encoder} is not in the local Hugging Face cache after loading it; "
                           "the probe must record the encoder revision it was trained on (SYS-61)")
    X_train = embed_for_probe(model, texts_of(train), model_name=encoder)
    X_test = embed_for_probe(model, texts_of(test), model_name=encoder)
    os.makedirs(EMBED_CACHE_DIR, exist_ok=True)
    np.savez(_embed_cache_path(encoder, revision, gold_path, train, test), X_train=X_train, X_test=X_test)
    return X_train, X_test, revision


def tradeoff_curve(rows: Sequence[dict], p_soft: np.ndarray, topic_pred: np.ndarray,
                   taus=(0.30, 0.35, 0.39, 0.42, 0.45, 0.50, 0.55, 0.60)):
    logger.info("  trade-off on this split (for the owner's operating-point decision; tau is NOT chosen here):")
    logger.info("    tau   rec_fin  rec_gen  prec_mixed  prec_allow  kept")
    for tau in taus:
        m = gate_metrics(rows, p_soft, topic_pred, float(tau))
        kept = sum(d["kept"] for d in m["per_stratum"].values()) / m["n"]
        logger.info("    %.2f   %.3f    %.3f     %.3f       %.3f    %3.0f%%", tau, m["recall_finance"], m["recall_general"],
                    m["precision_mixed"], m["precision_allow"], 100 * kept)


# ── the decision, as the live filter makes it ────────────────────────────────
def live_decision(p_soft: np.ndarray, categories: Sequence[Optional[str]], tau: float,
                  sources: Optional[Sequence[Optional[str]]] = None) -> np.ndarray:
    """is_news per row under the full live rule: a `deny` category is rejected
    before the probe; everything else is news iff P(soft) < tau. `sources`
    scopes SRC-50's per-source soft leaves, as the live filter does."""
    sources = [None] * len(categories) if sources is None else sources
    denied = np.array([category_gate(c, s) == "deny" for c, s in zip(categories, sources)])
    return (np.asarray(p_soft) < tau) & ~denied


def topic_of(probs: np.ndarray, classes: List[str]) -> np.ndarray:
    """Best NEWS class per row (soft excluded), as ImportanceProbe.decide does."""
    news = probs.copy()
    news[:, classes.index(TOPIC_SOFT)] = -1.0
    return np.array(classes)[news.argmax(axis=1)]


def _rate(num: int, den: int) -> Optional[float]:
    return (num / den) if den else None


def gate_metrics(rows: Sequence[dict], p_soft: np.ndarray, topic_pred: np.ndarray, tau: float) -> Dict[str, Optional[float]]:
    """The five gates plus the per-stratum table, for one split at one tau.

    DBT-35 (#151): this used to take a 13-column `probs` matrix and read P(soft)
    out of `probs[:, classes.index("soft")]`. Two different matrices in this
    codebase have a `soft` column -- the topic head's raw softmax and the
    assembled gate matrix -- and only the second is the live rule. Passing the
    wrong one raised nothing and read recall_finance 0.994 instead of 0.946,
    i.e. it moved the numbers UP, which is not the direction that makes anyone
    re-check their work. The two quantities this function actually needs are now
    named arguments, so the confusion is a TypeError rather than a wrong answer:

      p_soft     (n,) the GATE head's P(soft) -- ImportanceProbe.p_soft(X)
      topic_pred (n,) the predicted news class per row -- topic_of(probe.topic_proba(X), classes)
    """
    p_soft = np.asarray(p_soft, dtype=float)
    topic_pred = np.asarray(topic_pred)
    if p_soft.ndim != 1 or topic_pred.ndim != 1:
        raise ValueError(
            f"gate_metrics expects 1-D p_soft and topic_pred, got {p_soft.shape} and {topic_pred.shape} -- "
            "a 2-D array here means a probability matrix was passed where P(soft) belongs (DBT-35)")
    if not (len(p_soft) == len(topic_pred) == len(rows)):
        raise ValueError(f"gate_metrics: {len(rows)} rows, {len(p_soft)} p_soft, {len(topic_pred)} topic_pred")
    y = np.array([bool(r["is_news"]) for r in rows])
    pred = live_decision(p_soft, [r.get("category") for r in rows], tau, [r.get("source") for r in rows])
    strata = np.array([r["stratum"] for r in rows])
    allow = np.array([category_gate(r.get("category"), r.get("source")) == "allow" for r in rows])

    def recall(mask):
        m = mask & y
        return _rate(int((pred & m).sum()), int(m.sum()))

    def precision(mask):
        m = mask & pred
        return _rate(int((y & m).sum()), int(m.sum()))

    fin = np.isin(strata, FINANCE_STRATA)
    gen = np.isin(strata, GENERAL_STRATA)
    mixed = np.isin(strata, MIXED_STRATA)
    topic_true = np.array([r["topic"] for r in rows])
    news_rows = y
    out = {
        "recall_finance": recall(fin),
        "recall_general": recall(gen),
        "precision_mixed": precision(mixed),
        "precision_allow": precision(allow),
        "topic_accuracy": _rate(int((topic_pred[news_rows] == topic_true[news_rows]).sum()), int(news_rows.sum())),
        "recall_all": recall(np.ones_like(y)),
        "precision_all": precision(np.ones_like(y)),
        "uncertain_band_share": float(((p_soft >= UNCERTAIN_BAND[0]) & (p_soft <= UNCERTAIN_BAND[1])).mean()),
        "n": int(len(rows)),
    }
    per_stratum = {}
    for s in sorted(set(strata)):
        m = strata == s
        per_stratum[s] = {"n": int(m.sum()), "recall": recall(m), "precision": precision(m),
                          "kept": int((pred & m).sum()), "news": int((y & m).sum())}
    out["per_stratum"] = per_stratum
    return out


def gates_pass(metrics: Dict[str, Optional[float]], tolerance: float = GATE_TOLERANCE) -> Tuple[bool, List[str]]:
    """Every gate met within `tolerance` of its floor (0 = the floors exactly)."""
    failures = []
    for name, floor in GATES.items():
        value = metrics.get(name)
        if value is None or value < floor - tolerance:
            failures.append(f"{name}={value if value is None else f'{value:.3f}'} < {floor:.2f}-{tolerance:.2f}")
    return not failures, failures


def choose_threshold(rows: Sequence[dict], cv_p_soft: np.ndarray, cv_topic_pred: np.ndarray,
                     grid=np.round(np.arange(0.30, 0.81, 0.01), 2)) -> Tuple[float, Dict]:
    """The tau with the largest minimum slack over the tau-dependent gates on
    the cross-validated train predictions -- the widest margin when every gate
    is met, the least-bad point when none can be. Topic accuracy is not part
    of the search (it does not depend on tau)."""
    best_tau, best_slack, best_metrics = 0.5, -9.0, None
    for tau in grid:
        m = gate_metrics(rows, cv_p_soft, cv_topic_pred, float(tau))
        if any(m.get(name) is None for name in TAU_GATES):
            continue
        # The tau with the largest MINIMUM slack over the tau-dependent gates.
        # When every gate is met that is the widest safety margin; when none
        # can be, it is the least-bad point -- recall margin is traded for
        # precision until the two shortfalls balance, instead of parking at
        # 0.5 with recall far above its floor and precision far below.
        slack = min((m[name] - floor) for name, floor in TAU_GATES.items())
        if slack > best_slack:
            best_tau, best_slack, best_metrics = float(tau), slack, m
    if best_metrics is None:
        best_metrics = gate_metrics(rows, cv_p_soft, cv_topic_pred, best_tau)
    return best_tau, best_metrics


# ── training: two heads, each selected by cross-validation on train ──────────
def _order(clf, classes):
    return [list(clf.classes_).index(c) for c in classes]


def fit_gate(X: np.ndarray, is_news, C: float, seed: int = SEED):
    """Binary logistic regression, positive class = soft."""
    from sklearn.linear_model import LogisticRegression
    y = ~np.asarray(is_news, dtype=bool)
    return LogisticRegression(C=C, max_iter=4000, random_state=seed).fit(X, y)


def fit_topic(X: np.ndarray, topics, C: float, seed: int = SEED):
    """13-class multinomial, class-balanced (the soft rows act as negatives;
    this beat a news-only 12-class head in the SYS-47 sweep)."""
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(C=C, class_weight="balanced", max_iter=4000, random_state=seed).fit(X, topics)


# DBT-35 (#151): assemble() is gone. It existed only to pack the gate head's
# P(soft) and the topic head's softmax into one 13-column matrix for
# gate_metrics, and that matrix was indistinguishable at the call site from the
# topic head's raw softmax -- the ambiguity this ticket removed. gate_metrics
# now takes the two quantities by name. (Scaling the news columns by 1 - P(soft)
# never changed the argmax over news classes, so dropping it changes no number.)


def cv_gate_probs(X, is_news, C, seed: int = SEED, folds: int = 5) -> np.ndarray:
    from sklearn.model_selection import StratifiedKFold
    y = np.asarray(is_news, dtype=bool)
    out = np.zeros(len(y))
    for a, b in StratifiedKFold(folds, shuffle=True, random_state=seed).split(X, y):
        g = fit_gate(X[a], y[a], C, seed)
        out[b] = g.predict_proba(X[b])[:, list(g.classes_).index(True)]
    return out


def cv_topic_probs(X, topics, C, classes, seed: int = SEED, folds: int = 5) -> np.ndarray:
    from sklearn.model_selection import StratifiedKFold
    y = np.asarray(topics)
    out = np.zeros((len(y), len(classes)))
    for a, b in StratifiedKFold(folds, shuffle=True, random_state=seed).split(X, y):
        t = fit_topic(X[a], y[a], C, seed)
        out[b] = t.predict_proba(X[b])[:, _order(t, classes)]
    return out


def select_heads(X_train, train, classes):
    """Model selection on CV of train only. Gate: the (C, tau) with the widest
    minimum slack over the tau-dependent gates. Topic: the C with the best CV
    topic accuracy on news rows. Returns (C_gate, tau, C_topic, cv_metrics)."""
    is_news = [bool(r["is_news"]) for r in train]
    topics = [r["topic"] for r in train]
    best_topic = (None, -1.0, None)
    for C in TOPIC_C_GRID:
        cv_t = cv_topic_probs(X_train, topics, C, classes)
        pred = topic_of(cv_t, classes)
        acc = float(np.mean([p == t for p, t, n in zip(pred, topics, is_news) if n]))
        logger.info("  topic head C=%-4s  cv topic accuracy %.3f", C, acc)
        if acc > best_topic[1]:
            best_topic = (C, acc, cv_t)
    C_topic, _, cv_topic = best_topic
    best_gate = (None, None, -9.0, None)
    for C in GATE_C_GRID:
        cv_g = cv_gate_probs(X_train, is_news, C)
        tau, m = choose_threshold(train, cv_g, topic_of(cv_topic, classes))
        ok = all(m.get(k) is not None and m[k] >= v for k, v in TAU_GATES.items())
        slack = min(m[k] - v for k, v in TAU_GATES.items() if m[k] is not None)
        logger.info("  gate head C=%-5s tau=%.2f  cv rec_fin=%.3f rec_gen=%.3f prec_mixed=%.3f prec_allow=%.3f  %s",
                    C, tau, m["recall_finance"], m["recall_general"], m["precision_mixed"], m["precision_allow"],
                    "feasible" if ok else "infeasible")
        if slack > best_gate[2]:
            best_gate = (C, tau, slack, m)
    C_gate, tau, _, cv_metrics = best_gate
    return C_gate, tau, C_topic, cv_metrics


def confusion(rows: Sequence[dict], topic_pred: np.ndarray, classes: List[str]) -> Dict[str, Dict[str, int]]:
    pred = topic_pred
    table: Dict[str, Dict[str, int]] = {c: collections.Counter() for c in classes if c != TOPIC_SOFT}
    for r, p in zip(rows, pred):
        if r["is_news"]:
            table[r["topic"]][str(p)] += 1
    return {k: dict(v) for k, v in table.items()}


def macro_f1(rows: Sequence[dict], topic_pred: np.ndarray) -> float:
    from sklearn.metrics import f1_score
    news = [i for i, r in enumerate(rows) if r["is_news"]]
    if not news:
        return 0.0
    pred = np.asarray(topic_pred)[news]
    true = [rows[i]["topic"] for i in news]
    return float(f1_score(true, pred, average="macro", zero_division=0))


def print_report(title: str, m: Dict) -> None:
    logger.info("%s: n=%d  recall_all=%.3f precision_all=%.3f  uncertain-band=%.1f%%", title, m["n"],
                m["recall_all"], m["precision_all"], 100 * m["uncertain_band_share"])
    for name, floor in GATES.items():
        v = m[name]
        if v is None:
            flag = "n/a"
        elif v >= floor:
            flag = "PASS"
        elif v >= floor - GATE_TOLERANCE:
            flag = f"PASS within tolerance (-{floor - v:.3f}; owner decision 2026-09-22)"
        else:
            flag = "FAIL"
        logger.info("  %-18s %s  (gate >= %.2f)  %s", name, "  n/a" if v is None else f"{v:.3f}", floor, flag)
    logger.info("  %-24s %5s %5s %5s %8s %10s", "stratum", "n", "news", "kept", "recall", "precision")
    for s, d in sorted(m["per_stratum"].items(), key=lambda kv: -kv[1]["n"]):
        r = "  n/a" if d["recall"] is None else f"{d['recall']:.3f}"
        p = "  n/a" if d["precision"] is None else f"{d['precision']:.3f}"
        logger.info("  %-24s %5d %5d %5d %8s %10s", s, d["n"], d["news"], d["kept"], r, p)


# ── main: train / evaluate / write ───────────────────────────────────────────
def cmd_train(args) -> int:
    from sentence_transformers import SentenceTransformer
    import sklearn

    gold = read_gold(args.gold)
    train = [r for r in gold if r["split"] == "train"]
    test = [r for r in gold if r["split"] == "test"]
    classes = list(TOPICS)
    logger.info("gold %s: %d rows (train %d / test %d), sha256 %s; encoder %s", os.path.relpath(args.gold, REPO_ROOT),
                len(gold), len(train), len(test), sha256_of_file(args.gold)[:12], args.encoder)

    X_train, X_test, revision = embed_split(args.encoder, args.gold, train, test)
    y_train = [r["topic"] for r in train]
    logger.info("embedded: train %s, test %s", X_train.shape, X_test.shape)

    logger.info("model selection on 5-fold CV of train:")
    C_gate, tau, C_topic, cv_metrics = select_heads(X_train, train, classes)
    logger.info("selected: gate C=%s tau=%.2f, topic C=%s", C_gate, tau, C_topic)
    print_report("train (5-fold CV) at tau", cv_metrics)

    is_news_train = [bool(r["is_news"]) for r in train]
    gate = fit_gate(X_train, is_news_train, C_gate)
    topic = fit_topic(X_train, y_train, C_topic)
    gate_coef = gate.coef_.reshape(-1).astype(np.float64)
    gate_intercept = float(gate.intercept_[0])
    topic_coef = topic.coef_[_order(topic, classes)].astype(np.float64)
    topic_intercept = topic.intercept_[_order(topic, classes)].astype(np.float64)
    # sklearn's coefficients predict its classes_[1]; the probe's sigmoid must be P(soft)
    if list(gate.classes_) != [False, True]:
        gate_coef, gate_intercept = -gate_coef, -gate_intercept
    probe = ImportanceProbe(gate_coef, gate_intercept, topic_coef, topic_intercept, classes, tau)
    # parity: our sigmoid/softmax must reproduce sklearn before anything is written
    sk_soft = gate.predict_proba(X_test)[:, list(gate.classes_).index(True)]
    sk_topic = topic.predict_proba(X_test)[:, _order(topic, classes)]
    max_diff = max(float(np.abs(probe.p_soft(X_test) - sk_soft).max()),
                   float(np.abs(probe.topic_proba(X_test) - sk_topic).max()))
    if max_diff > 1e-6:
        logger.error("npz heads differ from sklearn predict_proba by %.2e -- refusing to write", max_diff)
        return 3
    p_soft_test = probe.p_soft(X_test)
    topic_pred_test = topic_of(probe.topic_proba(X_test), classes)
    test_metrics = gate_metrics(test, p_soft_test, topic_pred_test, tau)
    test_metrics["topic_macro_f1"] = macro_f1(test, topic_pred_test)
    ok, failures = gates_pass(test_metrics)
    print_report(f"TEST at tau={tau:.2f}", test_metrics)
    logger.info("  topic macro-F1 on news rows: %.3f", test_metrics["topic_macro_f1"])
    tradeoff_curve(test, p_soft_test, topic_pred_test)
    logger.info("  labels' measured noise floor is ~%.0f%% (SYS-46): read every gate as +/-%.2f", 100 * NOISE_FLOOR, NOISE_FLOOR)
    conf = confusion(test, topic_pred_test, classes)
    logger.info("  confusion (gold topic -> predicted, news rows):")
    for true_topic, preds in conf.items():
        top = sorted(preds.items(), key=lambda kv: -kv[1])[:4]
        logger.info("    %-20s %s", true_topic, ", ".join(f"{p}={n}" for p, n in top))

    if not ok:
        logger.error("GATE FAILURE on the test split: %s -- artifact NOT written (do not lower the gate)", "; ".join(failures))
        return 2
    exact_ok, within = gates_pass(test_metrics, tolerance=0.0)
    if not exact_ok:
        logger.warning("gates met within GATE_TOLERANCE=%.2f, not exactly: %s (owner decision 2026-09-22, SYS-37)",
                       GATE_TOLERANCE, "; ".join(within))
    if args.no_write:
        logger.info("[--no-write] gates pass; artifact not written.")
        return 0

    os.makedirs(args.out_dir, exist_ok=True)
    np.savez(os.path.join(args.out_dir, PROBE_WEIGHTS), gate_coef=gate_coef, gate_intercept=np.array([gate_intercept]),
             topic_coef=topic_coef, topic_intercept=topic_intercept, classes=np.array(classes))
    sidecar = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "embedding_model": args.encoder,
        "embedding_revision": revision,
        "embedding_dim": int(topic_coef.shape[1]),
        "classes": classes,
        "soft_threshold": tau,
        "gold_path": os.path.relpath(args.gold, REPO_ROOT).replace("\\", "/"),
        "gold_sha256": sha256_of_file(args.gold),
        "n_train": len(train), "n_test": len(test),
        "sklearn_version": sklearn.__version__, "numpy_version": np.__version__,
        "estimator": {"gate": f"LogisticRegression(binary soft-vs-news, C={C_gate})",
                      "topic": f"LogisticRegression(13-class, class_weight=balanced, C={C_topic})",
                      "selection": "5-fold CV on train; tau over the tau-dependent gates; topic C by CV accuracy"},
        "seed": SEED,
        "gates": GATES,
        "gate_tolerance": GATE_TOLERANCE,
        "gates_met_exactly": exact_ok,
        "metrics_test": {k: v for k, v in test_metrics.items() if k != "per_stratum"},
        "metrics_test_per_stratum": test_metrics["per_stratum"],
        "metrics_train_cv": {k: v for k, v in cv_metrics.items() if k != "per_stratum"},
        "confusion_test": conf,
        "noise_floor": NOISE_FLOOR,
    }
    with open(os.path.join(args.out_dir, PROBE_SIDECAR), "w", encoding="utf-8", newline="\n") as f:
        json.dump(sidecar, f, indent=1, ensure_ascii=False)
    # Load it back through the runtime path: what the service will do at start-up.
    written = ImportanceProbe.load(args.out_dir, expected_model_name=args.encoder)
    if written.encoder_revision != revision:  # SYS-61: the filter refuses a probe without it
        raise RuntimeError(f"the written sidecar records embedding_revision {written.encoder_revision!r}, not {revision!r}")
    logger.info("wrote %s and %s (loads back cleanly)", PROBE_WEIGHTS, PROBE_SIDECAR)
    return 0


# ── backfill: topics for existing articles ───────────────────────────────────
_ARTICLES_SQL = """
    SELECT a.articles_id, a.sitemap_id, s.headline, LEFT(a.extracted_text, :n) AS body_head, s.sources, s.category,
           a.topic AS prev_topic, a.topic_confidence AS prev_topic_confidence
    FROM articles a JOIN sitemaps s USING (sitemap_id)
    WHERE (:only_missing = FALSE OR a.topic IS NULL)
    ORDER BY a.articles_id
"""


def cmd_backfill(args) -> int:
    from sqlalchemy import text
    from sentence_transformers import SentenceTransformer
    from newscrawler.core.importance_probe import PROBE_BODY_CHARS
    from newscrawler.core.importance_filter import SemanticImportanceFilter
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    from newscrawler.core.constants import SOFT_THRESHOLD
    from newscrawler.core.importance_probe import artifact_identity

    # DBT-37 (#153): the live service is built as
    # SemanticImportanceFilter(soft_threshold=SOFT_THRESHOLD). Constructing it
    # without the override here would write articles.topic at the sidecar's tau
    # while the pipeline runs at the env's -- same probe, different decision.
    filt = SemanticImportanceFilter(soft_threshold=SOFT_THRESHOLD)
    identity = artifact_identity(soft_threshold=filt.probe.soft_threshold)
    logger.info("probe: %s tau=%.2f gold=%s artifact=%s", identity["embedding_model"], identity["soft_threshold"],
                (identity["gold_sha256"] or "?")[:12], identity["artifact_sha256"][:12])
    client = SQLAlchemyClient()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        rows = session.execute(text(_ARTICLES_SQL), {"n": PROBE_BODY_CHARS, "only_missing": not args.all}).fetchall()
    logger.info("%d article(s) to tag%s", len(rows), "" if args.all else " (topic IS NULL)")
    if not rows:
        return 0
    texts = [build_check_text(r.headline, r.body_head) for r in rows]
    decisions = []
    for i in range(0, len(rows), 256):
        chunk = rows[i:i + 256]
        batch = filt.classify_batch(texts[i:i + 256], [r.category for r in chunk], [r.sources for r in chunk])
        # DBT-36 (#152): `zip(rows, decisions)` below writes articles.topic for
        # 11.8k rows in one transaction. One short batch would write the wrong
        # topic to every row after the gap, so the length is asserted here too.
        if len(batch) != len(chunk):
            raise RuntimeError(f"classify_batch returned {len(batch)} decisions for {len(chunk)} article(s)")
        decisions.extend(batch)
    topics = collections.Counter(d.topic for d in decisions)
    soft = [(r, d) for r, d in zip(rows, decisions) if not d.is_important]
    logger.info("topic distribution: %s", ", ".join(f"{t}={n}" for t, n in topics.most_common()))
    logger.info("%d of %d saved articles the probe would now call soft (%.1f%%) -- reported, NOT changed here "
                "(SYS-45's cleanup is its own dry-run -> ask)", len(soft), len(rows), 100 * len(soft) / len(rows))
    import random
    rng = random.Random(SEED)
    sample = rng.sample(list(zip(rows, decisions)), min(20, len(rows)))
    for r, d in sample:
        logger.info("  %-14s %-16s %-20s %.2f  %s", r.sources, (r.category or "")[:16], d.topic, d.topic_confidence or 0, (r.headline or "")[:70])
    if args.dry_run:
        logger.info("[dry-run] would UPDATE articles.topic/topic_confidence on %d row(s). Nothing written.", len(rows))
        return 0
    os.makedirs(os.path.join(REPO_ROOT, "backups"), exist_ok=True)
    # DBT-34 (#150): two changes to what this file is.
    #  (1) `meta` records WHICH probe produced these verdicts. cleanup_soft_by_probe.py
    #      deletes production articles on them by default; without an identity a
    #      retrain or a threshold move leaves it deleting on stale verdicts and
    #      saying nothing. A file without `meta` is refused there.
    #  (2) the rows carry the PREVIOUS topic/topic_confidence as well as the new
    #      ones, so the name "backup" is true -- the first run's values were all
    #      NULL, a second run after a retrain used to overwrite 11.8k topics with
    #      no record of what they were. Named *_applied_* for the same reason.
    backup = os.path.join(REPO_ROOT, "backups",
                          f"sys37_topic_backfill_applied_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    with open(backup, "w", encoding="utf-8") as f:
        json.dump({
            "meta": dict(identity, applied_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         n_rows=len(rows), scope="all" if args.all else "topic IS NULL"),
            "rows": [{"articles_id": r.articles_id, "topic": d.topic, "topic_confidence": d.topic_confidence,
                      "is_news": d.is_important, "prev_topic": r.prev_topic,
                      "prev_topic_confidence": float(r.prev_topic_confidence) if r.prev_topic_confidence is not None else None}
                     for r, d in zip(rows, decisions)],
        }, f)
    logger.info("backup (previous + new values, with the probe's identity) written to %s", backup)
    with client.get_session() as session:
        n = 0
        for r, d in zip(rows, decisions):
            n += session.execute(
                text("UPDATE articles SET topic = :t, topic_confidence = :c WHERE articles_id = :id"),
                {"t": d.topic, "c": d.topic_confidence, "id": r.articles_id},
            ).rowcount
        session.commit()
    logger.info("updated %d article(s) in one transaction.", n)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold", default=GOLD_PATH)
    parser.add_argument("--out-dir", default=PROBE_DIR)
    parser.add_argument("--encoder", default=None,
                        help="sentence-transformers model for the probe; default: the committed sidecar's "
                             "(DBT-49), recorded in the sidecar. Another one changes production's encoder.")
    parser.add_argument("--no-write", action="store_true", help="Evaluate only; never write the artifact")
    parser.add_argument("--backfill", action="store_true", help="Tag existing articles with a topic (needs the artifact)")
    parser.add_argument("--all", action="store_true", help="--backfill: re-tag every article, not only topic IS NULL")
    parser.add_argument("--dry-run", action="store_true", help="--backfill: counts and a sample, no write")
    args = parser.parse_args(argv)
    args.encoder = resolve_encoder(args.encoder, args.out_dir)
    return cmd_backfill(args) if args.backfill else cmd_train(args)


def committed_encoder(out_dir: str):
    """The encoder the committed sidecar in `out_dir` names, or None."""
    path = os.path.join(out_dir, PROBE_SIDECAR)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("embedding_model")
    except (OSError, ValueError):
        return None


def resolve_encoder(requested, out_dir: str) -> str:
    """DBT-49 (#203): no flag = retrain on the encoder production runs; a
    different one is allowed, loudly."""
    committed = committed_encoder(out_dir)
    if requested is None:
        return committed or DEFAULT_PROBE_ENCODER
    if committed and requested != committed:
        logger.warning("--encoder %s differs from the committed sidecar's %s: a written artifact CHANGES the "
                       "encoder production embeds with (the sidecar is authoritative)", requested, committed)
    return requested


if __name__ == "__main__":
    sys.exit(main())
