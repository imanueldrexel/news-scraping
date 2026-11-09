#!/usr/bin/env python3
"""
SYS-37 (#121) design sweep: which probe shape gets closest to the gates on the
SYS-36 gold set, and where is the ceiling?

Embeds the gold set once (cached to a .npz next to this script), then compares
on 5-fold CV of the train split and on the test split:
  A. one 13-class multinomial LR (the ticket's design), balanced vs unweighted
  B. two heads: a binary soft-vs-news gate + a 12-class topic model on news rows
  C. the same two heads with C tuned
  D. an MLP gate/topic (sklearn MLPClassifier) as a non-linear ceiling check
For each: the tau that maximises the minimum gate slack, the five gate numbers,
and the recall/precision curve on the mixed buckets. Read-only.

    python scripts/experiments/probe_design_sweep.py
"""
import json
import logging
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

from newscrawler.core.filter_rubric import TOPICS, TOPIC_SOFT  # noqa: E402
from newscrawler.core.importance_probe import PROBE_MODEL_NAME, embed_for_probe  # noqa: E402
from newscrawler.core.utils.hf_cache import resolve_model  # noqa: E402
from train_importance_probe import (  # noqa: E402
    FINANCE_STRATA, GATES, GENERAL_STRATA, MIXED_STRATA, SEED, gate_metrics, gates_pass, read_gold, texts_of,
)

logging.basicConfig(format="%(message)s")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_design_sweep_embeddings.npz")


def embeddings(gold):
    if os.path.exists(CACHE):
        with np.load(CACHE) as z:
            if int(z["n"]) == len(gold):
                return z["X"]
    from sentence_transformers import SentenceTransformer
    X = embed_for_probe(SentenceTransformer(resolve_model(PROBE_MODEL_NAME)), texts_of(gold))
    np.savez(CACHE, X=X, n=len(gold))
    return X


def to_13(probs_soft, probs_topic, topic_classes):
    """Assemble a 13-column matrix in TOPICS order from a binary gate and a
    12-class topic model so gate_metrics() can score it: P(soft) from the gate,
    the news columns scaled by (1 - P(soft))."""
    out = np.zeros((len(probs_soft), len(TOPICS)))
    for j, c in enumerate(TOPICS):
        if c == TOPIC_SOFT:
            out[:, j] = probs_soft
        else:
            out[:, j] = (1 - probs_soft) * probs_topic[:, topic_classes.index(c)]
    return out


def cv_two_heads(X, rows, gate_factory, topic_factory, folds=5):
    from sklearn.model_selection import StratifiedKFold
    y_news = np.array([bool(r["is_news"]) for r in rows])
    y_topic = np.array([r["topic"] for r in rows])
    topic_classes = [c for c in TOPICS if c != TOPIC_SOFT]
    ps = np.zeros(len(rows))
    pt = np.zeros((len(rows), len(topic_classes)))
    for tr, va in StratifiedKFold(folds, shuffle=True, random_state=SEED).split(X, y_topic):
        g = gate_factory().fit(X[tr], ~y_news[tr])           # positive class = soft
        ps[va] = g.predict_proba(X[va])[:, list(g.classes_).index(True)]
        news_tr = tr[y_news[tr]]
        t = topic_factory().fit(X[news_tr], y_topic[news_tr])
        p = t.predict_proba(X[va])
        pt[va] = p[:, [list(t.classes_).index(c) for c in topic_classes]]
    return to_13(ps, pt, topic_classes)


def fit_two_heads(X_tr, rows_tr, X_te, gate_factory, topic_factory):
    y_news = np.array([bool(r["is_news"]) for r in rows_tr])
    y_topic = np.array([r["topic"] for r in rows_tr])
    topic_classes = [c for c in TOPICS if c != TOPIC_SOFT]
    g = gate_factory().fit(X_tr, ~y_news)
    ps = g.predict_proba(X_te)[:, list(g.classes_).index(True)]
    t = topic_factory().fit(X_tr[y_news], y_topic[y_news])
    p = t.predict_proba(X_te)
    return to_13(ps, p[:, [list(t.classes_).index(c) for c in topic_classes]], topic_classes)


def best_tau(rows, probs):
    best = (None, -9, None)
    for tau in np.round(np.arange(0.20, 0.91, 0.01), 2):
        m = gate_metrics(rows, probs, float(tau), list(TOPICS))
        slack = min(m[k] - v for k, v in GATES.items() if m[k] is not None)
        if slack > best[1]:
            best = (float(tau), slack, m)
    return best


def report(name, rows_cv, cv_probs, rows_te, te_probs):
    tau, slack, m_cv = best_tau(rows_cv, cv_probs)
    m_te = gate_metrics(rows_te, te_probs, tau, list(TOPICS))
    ok, fails = gates_pass(m_te)
    log.info("%-46s tau=%.2f cv-slack=%+.3f | TEST rec_fin=%.3f rec_gen=%.3f prec_mixed=%.3f prec_allow=%.3f topic=%.3f | %s",
             name, tau, slack, m_te["recall_finance"], m_te["recall_general"], m_te["precision_mixed"],
             m_te["precision_allow"], m_te["topic_accuracy"], "PASS" if ok else "FAIL " + ", ".join(f.split("=")[0] for f in fails))
    return tau, m_te


def curve(name, rows, probs):
    """Mixed-bucket precision vs finance recall as tau moves -- the trade-off the gates sit on."""
    log.info("  %s: tau  rec_fin  rec_gen  prec_mixed  prec_allow  kept%%", name)
    for tau in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70):
        m = gate_metrics(rows, probs, tau, list(TOPICS))
        kept = sum(d["kept"] for d in m["per_stratum"].values()) / m["n"]
        log.info("        %.2f   %.3f    %.3f     %.3f       %.3f     %3.0f%%", tau, m["recall_finance"], m["recall_general"],
                 m["precision_mixed"], m["precision_allow"], 100 * kept)


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
    from sklearn.model_selection import StratifiedKFold

    gold = read_gold()
    X = embeddings(gold)
    idx_tr = [i for i, r in enumerate(gold) if r["split"] == "train"]
    idx_te = [i for i, r in enumerate(gold) if r["split"] == "test"]
    tr, te = [gold[i] for i in idx_tr], [gold[i] for i in idx_te]
    X_tr, X_te = X[idx_tr], X[idx_te]
    log.info("train %d / test %d; news share train %.1f%%", len(tr), len(te), 100 * np.mean([r["is_news"] for r in tr]))

    # A. single 13-class multinomial
    for cw in ("balanced", None):
        y = np.array([r["topic"] for r in tr])
        cv = np.zeros((len(tr), len(TOPICS)))
        for a, b in StratifiedKFold(5, shuffle=True, random_state=SEED).split(X_tr, y):
            clf = LogisticRegression(C=1.0, class_weight=cw, max_iter=2000, random_state=SEED).fit(X_tr[a], y[a])
            cv[b] = clf.predict_proba(X_tr[b])[:, [list(clf.classes_).index(c) for c in TOPICS]]
        clf = LogisticRegression(C=1.0, class_weight=cw, max_iter=2000, random_state=SEED).fit(X_tr, y)
        te_p = clf.predict_proba(X_te)[:, [list(clf.classes_).index(c) for c in TOPICS]]
        report(f"A. 13-class multinomial LR, class_weight={cw}", tr, cv, te, te_p)

    # B/C. two heads, C grid
    results = {}
    for C_gate in (0.5, 1, 2, 4, 8, 16):
        for cw in (None, "balanced"):
            gf = lambda C_gate=C_gate, cw=cw: LogisticRegression(C=C_gate, class_weight=cw, max_iter=2000, random_state=SEED)
            tf = lambda: LogisticRegression(C=4, max_iter=3000, random_state=SEED)
            cv = cv_two_heads(X_tr, tr, gf, tf)
            te_p = fit_two_heads(X_tr, tr, X_te, gf, tf)
            tau, m = report(f"B. gate LR C={C_gate} cw={cw} + topic LR C=4", tr, cv, te, te_p)
            results[(C_gate, cw)] = (tau, m, cv, te_p)
    # topic head C grid (gate fixed at C=4 unweighted)
    for C_t in (0.5, 1, 2, 4, 8, 16, 32):
        gf = lambda: LogisticRegression(C=4, max_iter=2000, random_state=SEED)
        tf = lambda C_t=C_t: LogisticRegression(C=C_t, max_iter=3000, random_state=SEED)
        cv = cv_two_heads(X_tr, tr, gf, tf)
        te_p = fit_two_heads(X_tr, tr, X_te, gf, tf)
        report(f"C. gate LR C=4 + topic LR C={C_t}", tr, cv, te, te_p)
    # D. non-linear ceiling check
    gf = lambda: MLPClassifier(hidden_layer_sizes=(256,), alpha=1e-3, max_iter=400, random_state=SEED)
    tf = lambda: MLPClassifier(hidden_layer_sizes=(256,), alpha=1e-3, max_iter=400, random_state=SEED)
    cv = cv_two_heads(X_tr, tr, gf, tf)
    te_p = fit_two_heads(X_tr, tr, X_te, gf, tf)
    report("D. MLP(256) gate + MLP(256) topic", tr, cv, te, te_p)

    # the trade-off curve for the best linear gate
    best_key = max(results, key=lambda k: min(results[k][1][g] - v for g, v in GATES.items() if g != "topic_accuracy"))
    log.info("\nbest linear gate by non-topic slack: C=%s cw=%s", *best_key)
    curve("TEST", te, results[best_key][3])
    curve("CV-train", tr, results[best_key][2])
    # what precision on the mixed buckets / allow-set is attainable when recall_finance is held at a floor
    for floor in (0.95, 0.90, 0.85):
        best = None
        for tau in np.round(np.arange(0.05, 0.95, 0.01), 2):
            m = gate_metrics(te, results[best_key][3], float(tau), list(TOPICS))
            if m["recall_finance"] >= floor and (best is None or m["precision_mixed"] > best[1]["precision_mixed"]):
                best = (float(tau), m)
        if best:
            log.info("  recall_finance >= %.2f  ->  best prec_mixed=%.3f prec_allow=%.3f rec_general=%.3f at tau=%.2f",
                     floor, best[1]["precision_mixed"], best[1]["precision_allow"], best[1]["recall_general"], best[0])


if __name__ == "__main__":
    main()
