#!/usr/bin/env python3
"""
SYS-37 (#121): train the importance probe -- a multinomial logistic regression
over the MiniLM embedding the pipeline already computes -- on the SYS-36 gold
set, evaluate it against the ticket's gates, and (only if every gate passes)
write the artifact the live filter loads.

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

Status 2026-09-21: on the SYS-36 gold set NO probe shape reaches the gates
(EXPERIMENTS.md, 2026-09-21 SYS-37 entry; scripts/experiments/probe_design_sweep.py
has the design sweep). The artifact is therefore not written and the live
filter still runs the cosine score; --backfill needs the runtime switch-over
(SemanticImportanceFilter.classify_batch) and says so until it lands.

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
    PROBE_DIR, PROBE_MODEL_NAME, PROBE_SIDECAR, PROBE_WEIGHTS, UNCERTAIN_BAND,
    ImportanceProbe, build_check_text, embed_for_probe, sha256_of_file,
)

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


# ── data ─────────────────────────────────────────────────────────────────────
def read_gold(path: str = GOLD_PATH) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def texts_of(rows: Sequence[dict]) -> List[str]:
    return [build_check_text(r["headline"], r.get("body_head")) for r in rows]


# ── the decision, as the live filter makes it ────────────────────────────────
def live_decision(probs: np.ndarray, categories: Sequence[Optional[str]], tau: float, soft_idx: int) -> np.ndarray:
    """is_news per row under the full live rule: a `deny` category is rejected
    before the probe; everything else is news iff P(soft) < tau."""
    p_soft = probs[:, soft_idx]
    denied = np.array([category_gate(c) == "deny" for c in categories])
    return (p_soft < tau) & ~denied


def topic_of(probs: np.ndarray, classes: List[str]) -> np.ndarray:
    """Best NEWS class per row (soft excluded), as ImportanceProbe.decide does."""
    news = probs.copy()
    news[:, classes.index(TOPIC_SOFT)] = -1.0
    return np.array(classes)[news.argmax(axis=1)]


def _rate(num: int, den: int) -> Optional[float]:
    return (num / den) if den else None


def gate_metrics(rows: Sequence[dict], probs: np.ndarray, tau: float, classes: List[str]) -> Dict[str, Optional[float]]:
    """The five gates plus the per-stratum table, for one split at one tau."""
    soft_idx = classes.index(TOPIC_SOFT)
    y = np.array([bool(r["is_news"]) for r in rows])
    pred = live_decision(probs, [r.get("category") for r in rows], tau, soft_idx)
    strata = np.array([r["stratum"] for r in rows])
    allow = np.array([category_gate(r.get("category")) == "allow" for r in rows])

    def recall(mask):
        m = mask & y
        return _rate(int((pred & m).sum()), int(m.sum()))

    def precision(mask):
        m = mask & pred
        return _rate(int((y & m).sum()), int(m.sum()))

    fin = np.isin(strata, FINANCE_STRATA)
    gen = np.isin(strata, GENERAL_STRATA)
    mixed = np.isin(strata, MIXED_STRATA)
    topic_pred = topic_of(probs, classes)
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
        "uncertain_band_share": float(((probs[:, soft_idx] >= UNCERTAIN_BAND[0]) & (probs[:, soft_idx] <= UNCERTAIN_BAND[1])).mean()),
        "n": int(len(rows)),
    }
    per_stratum = {}
    for s in sorted(set(strata)):
        m = strata == s
        per_stratum[s] = {"n": int(m.sum()), "recall": recall(m), "precision": precision(m),
                          "kept": int((pred & m).sum()), "news": int((y & m).sum())}
    out["per_stratum"] = per_stratum
    return out


def gates_pass(metrics: Dict[str, Optional[float]]) -> Tuple[bool, List[str]]:
    failures = []
    for name, floor in GATES.items():
        value = metrics.get(name)
        if value is None or value < floor:
            failures.append(f"{name}={value if value is None else f'{value:.3f}'} < {floor:.2f}")
    return not failures, failures


def choose_threshold(rows: Sequence[dict], cv_probs: np.ndarray, classes: List[str],
                     grid=np.round(np.arange(0.30, 0.81, 0.01), 2)) -> Tuple[float, Dict]:
    """The tau that satisfies every gate on the cross-validated train
    predictions with the largest minimum slack; 0.5 (and a report of the
    shortfalls) when none does."""
    best_tau, best_slack, best_metrics = None, -1.0, None
    for tau in grid:
        m = gate_metrics(rows, cv_probs, float(tau), classes)
        ok, _ = gates_pass(m)
        if not ok:
            continue
        slack = min((m[name] - floor) for name, floor in GATES.items())
        if slack > best_slack:
            best_tau, best_slack, best_metrics = float(tau), slack, m
    if best_tau is None:
        return 0.5, gate_metrics(rows, cv_probs, 0.5, classes)
    return best_tau, best_metrics


# ── training ─────────────────────────────────────────────────────────────────
def fit(X: np.ndarray, y: List[str], seed: int = SEED, C: float = 1.0):
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression(C=C, class_weight="balanced", max_iter=2000, random_state=seed)
    clf.fit(X, y)
    return clf


def cross_val_probs(X: np.ndarray, y: List[str], classes: List[str], seed: int = SEED, folds: int = 5) -> np.ndarray:
    from sklearn.model_selection import StratifiedKFold
    y_arr = np.array(y)
    out = np.zeros((len(y), len(classes)), dtype=np.float64)
    for train_idx, val_idx in StratifiedKFold(folds, shuffle=True, random_state=seed).split(X, y_arr):
        clf = fit(X[train_idx], list(y_arr[train_idx]), seed)
        probs = clf.predict_proba(X[val_idx])
        # align to `classes` order (sklearn orders classes_ lexically)
        col = [list(clf.classes_).index(c) for c in classes]
        out[val_idx] = probs[:, col]
    return out


def aligned_weights(clf, classes: List[str]) -> Tuple[np.ndarray, np.ndarray]:
    order = [list(clf.classes_).index(c) for c in classes]
    return clf.coef_[order].astype(np.float64), clf.intercept_[order].astype(np.float64)


def confusion(rows: Sequence[dict], probs: np.ndarray, classes: List[str]) -> Dict[str, Dict[str, int]]:
    pred = topic_of(probs, classes)
    table: Dict[str, Dict[str, int]] = {c: collections.Counter() for c in classes if c != TOPIC_SOFT}
    for r, p in zip(rows, pred):
        if r["is_news"]:
            table[r["topic"]][str(p)] += 1
    return {k: dict(v) for k, v in table.items()}


def macro_f1(rows: Sequence[dict], probs: np.ndarray, classes: List[str]) -> float:
    from sklearn.metrics import f1_score
    news = [i for i, r in enumerate(rows) if r["is_news"]]
    if not news:
        return 0.0
    pred = topic_of(probs[news], classes)
    true = [rows[i]["topic"] for i in news]
    return float(f1_score(true, pred, average="macro", zero_division=0))


def print_report(title: str, m: Dict) -> None:
    logger.info("%s: n=%d  recall_all=%.3f precision_all=%.3f  uncertain-band=%.1f%%", title, m["n"],
                m["recall_all"], m["precision_all"], 100 * m["uncertain_band_share"])
    for name, floor in GATES.items():
        v = m[name]
        flag = "PASS" if v is not None and v >= floor else "FAIL"
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
    logger.info("gold %s: %d rows (train %d / test %d), sha256 %s", os.path.relpath(args.gold, REPO_ROOT),
                len(gold), len(train), len(test), sha256_of_file(args.gold)[:12])

    model = SentenceTransformer(PROBE_MODEL_NAME)
    X_train = embed_for_probe(model, texts_of(train))
    X_test = embed_for_probe(model, texts_of(test))
    y_train = [r["topic"] for r in train]
    logger.info("embedded: train %s, test %s", X_train.shape, X_test.shape)

    cv = cross_val_probs(X_train, y_train, classes)
    tau, cv_metrics = choose_threshold(train, cv, classes)
    ok_cv, cv_failures = gates_pass(cv_metrics)
    logger.info("soft threshold chosen on 5-fold CV of train: tau=%.2f (%s)", tau,
                "all gates pass on CV" if ok_cv else "NO tau passes every gate on CV; 0.50 reported")
    print_report("train (5-fold CV) at tau", cv_metrics)

    clf = fit(X_train, y_train)
    coef, intercept = aligned_weights(clf, classes)
    probe = ImportanceProbe(coef, intercept, classes, tau)
    probs_test = probe.predict_proba(X_test)
    sk_probs = clf.predict_proba(X_test)[:, [list(clf.classes_).index(c) for c in classes]]
    max_diff = float(np.abs(probs_test - sk_probs).max())
    if max_diff > 1e-6:
        logger.error("npz softmax differs from sklearn predict_proba by %.2e -- refusing to write", max_diff)
        return 3
    test_metrics = gate_metrics(test, probs_test, tau, classes)
    test_metrics["topic_macro_f1"] = macro_f1(test, probs_test, classes)
    ok, failures = gates_pass(test_metrics)
    print_report(f"TEST at tau={tau:.2f}", test_metrics)
    logger.info("  topic macro-F1 on news rows: %.3f", test_metrics["topic_macro_f1"])
    logger.info("  labels' measured noise floor is ~%.0f%% (SYS-46): read every gate as +/-%.2f", 100 * NOISE_FLOOR, NOISE_FLOOR)
    conf = confusion(test, probs_test, classes)
    logger.info("  confusion (gold topic -> predicted, news rows):")
    for true_topic, preds in conf.items():
        top = sorted(preds.items(), key=lambda kv: -kv[1])[:4]
        logger.info("    %-20s %s", true_topic, ", ".join(f"{p}={n}" for p, n in top))

    if not ok:
        logger.error("GATE FAILURE on the test split: %s -- artifact NOT written (do not lower the gate)", "; ".join(failures))
        return 2
    if args.no_write:
        logger.info("[--no-write] gates pass; artifact not written.")
        return 0

    os.makedirs(args.out_dir, exist_ok=True)
    np.savez(os.path.join(args.out_dir, PROBE_WEIGHTS), coef=coef, intercept=intercept, classes=np.array(classes))
    sidecar = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "embedding_model": PROBE_MODEL_NAME,
        "embedding_dim": int(coef.shape[1]),
        "classes": classes,
        "soft_threshold": tau,
        "gold_path": os.path.relpath(args.gold, REPO_ROOT).replace("\\", "/"),
        "gold_sha256": sha256_of_file(args.gold),
        "n_train": len(train), "n_test": len(test),
        "sklearn_version": sklearn.__version__, "numpy_version": np.__version__,
        "estimator": "LogisticRegression(multinomial, lbfgs, class_weight=balanced, C=1.0, max_iter=2000)",
        "seed": SEED,
        "gates": GATES,
        "metrics_test": {k: v for k, v in test_metrics.items() if k != "per_stratum"},
        "metrics_test_per_stratum": test_metrics["per_stratum"],
        "metrics_train_cv": {k: v for k, v in cv_metrics.items() if k != "per_stratum"},
        "confusion_test": conf,
        "noise_floor": NOISE_FLOOR,
    }
    with open(os.path.join(args.out_dir, PROBE_SIDECAR), "w", encoding="utf-8", newline="\n") as f:
        json.dump(sidecar, f, indent=1, ensure_ascii=False)
    # Load it back through the runtime path: what the service will do at start-up.
    ImportanceProbe.load(args.out_dir)
    logger.info("wrote %s and %s (loads back cleanly)", PROBE_WEIGHTS, PROBE_SIDECAR)
    return 0


# ── backfill: topics for existing articles ───────────────────────────────────
_ARTICLES_SQL = """
    SELECT a.articles_id, a.sitemap_id, s.headline, LEFT(a.extracted_text, :n) AS body_head, s.sources, s.category
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

    if not hasattr(SemanticImportanceFilter, "classify_batch"):
        logger.error("--backfill needs the probe wired into SemanticImportanceFilter (classify_batch); "
                     "the runtime switch-over has not landed (SYS-37 is below its gates). Nothing done.")
        return 2
    filt = SemanticImportanceFilter()
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
        decisions.extend(filt.classify_batch(texts[i:i + 256], [r.category for r in rows[i:i + 256]]))
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
    backup = os.path.join(REPO_ROOT, "backups", f"sys37_topic_backfill_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    with open(backup, "w", encoding="utf-8") as f:
        json.dump([{"articles_id": r.articles_id, "topic": d.topic, "topic_confidence": d.topic_confidence,
                    "is_news": d.is_important} for r, d in zip(rows, decisions)], f)
    logger.info("backup of the new values written to %s", backup)
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
    parser.add_argument("--no-write", action="store_true", help="Evaluate only; never write the artifact")
    parser.add_argument("--backfill", action="store_true", help="Tag existing articles with a topic (needs the artifact)")
    parser.add_argument("--all", action="store_true", help="--backfill: re-tag every article, not only topic IS NULL")
    parser.add_argument("--dry-run", action="store_true", help="--backfill: counts and a sample, no write")
    args = parser.parse_args(argv)
    return cmd_backfill(args) if args.backfill else cmd_train(args)


if __name__ == "__main__":
    sys.exit(main())
