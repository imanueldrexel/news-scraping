#!/usr/bin/env python3
"""
SYS-47 (#143): does changing the probe's INPUT move it past SYS-37's gates?

Four cells on the same test split: {MiniLM, multilingual-e5-base} encoders x
{gold as frozen (73% headline-only), gold with fetched bodies + re-labels}.
Each cell: the ticket's 13-class multinomial LR AND the two-head design
(binary gate LR + 12-class topic LR), tau chosen on 5-fold CV of train, all
five gates on test, plus the precision attainable at finance recall >= 0.95 /
0.90 -- the number the decision turns on. Embeddings are cached per
(encoder, gold sha256) next to this script. Read-only.

    python scripts/experiments/probe_input_matrix.py --gold-frozen PATH --gold-bodies PATH [--encoders a,b]
"""
import argparse
import hashlib
import logging
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

from newscrawler.core.filter_rubric import TOPICS, TOPIC_SOFT  # noqa: E402
from newscrawler.core.importance_probe import PROBE_MODEL_NAME, embed_for_probe, sha256_of_file  # noqa: E402
from train_importance_probe import GATES, SEED, gate_metrics, gates_pass, read_gold, texts_of  # noqa: E402

logging.basicConfig(format="%(message)s")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
HERE = os.path.dirname(os.path.abspath(__file__))
E5 = "intfloat/multilingual-e5-base"


def embeddings(encoder, gold_path, gold):
    key = hashlib.sha256((encoder + sha256_of_file(gold_path) + "".join(texts_of(gold))).encode()).hexdigest()[:16]
    cache = os.path.join(HERE, f"probe_matrix_{key}.npz")
    if os.path.exists(cache):
        with np.load(cache) as z:
            return z["X"]
    from sentence_transformers import SentenceTransformer
    X = embed_for_probe(SentenceTransformer(encoder), texts_of(gold), model_name=encoder)
    np.savez(cache, X=X)
    return X


def order(clf, classes):
    return [list(clf.classes_).index(c) for c in classes]


def multinomial(X_tr, y_tr, X_va):
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000, random_state=SEED).fit(X_tr, y_tr)
    return clf.predict_proba(X_va)[:, order(clf, TOPICS)]


def two_heads(X_tr, rows_tr, X_va, C_gate=1.0, C_topic=4.0):
    from sklearn.linear_model import LogisticRegression
    y_news = np.array([bool(r["is_news"]) for r in rows_tr])
    y_topic = np.array([r["topic"] for r in rows_tr])
    news_classes = [c for c in TOPICS if c != TOPIC_SOFT]
    g = LogisticRegression(C=C_gate, max_iter=3000, random_state=SEED).fit(X_tr, ~y_news)
    ps = g.predict_proba(X_va)[:, list(g.classes_).index(True)]
    t = LogisticRegression(C=C_topic, max_iter=4000, random_state=SEED).fit(X_tr[y_news], y_topic[y_news])
    pt = t.predict_proba(X_va)[:, order(t, news_classes)]
    out = np.zeros((len(X_va), len(TOPICS)))
    for j, c in enumerate(TOPICS):
        out[:, j] = ps if c == TOPIC_SOFT else (1 - ps) * pt[:, news_classes.index(c)]
    return out


def cv_probs(X, rows, fn):
    from sklearn.model_selection import StratifiedKFold
    y = np.array([r["topic"] for r in rows])
    out = np.zeros((len(rows), len(TOPICS)))
    for a, b in StratifiedKFold(5, shuffle=True, random_state=SEED).split(X, y):
        out[b] = fn(X[a], [rows[i] for i in a], X[b])
    return out


def best_tau(rows, probs):
    best = (0.5, -9.0)
    for tau in np.round(np.arange(0.10, 0.91, 0.01), 2):
        m = gate_metrics(rows, probs, float(tau), list(TOPICS))
        slack = min(m[k] - v for k, v in GATES.items() if m[k] is not None)
        if slack > best[1]:
            best = (float(tau), slack)
    return best[0]


def precision_at(rows, probs, floor):
    best = None
    for tau in np.round(np.arange(0.02, 0.99, 0.01), 2):
        m = gate_metrics(rows, probs, float(tau), list(TOPICS))
        if m["recall_finance"] is not None and m["recall_finance"] >= floor:
            if best is None or m["precision_mixed"] > best["precision_mixed"]:
                best = dict(m, tau=float(tau))
    return best


def run_cell(name, encoder, gold_path):
    gold = read_gold(gold_path)
    X = embeddings(encoder, gold_path, gold)
    tr_i = [i for i, r in enumerate(gold) if r["split"] == "train"]
    te_i = [i for i, r in enumerate(gold) if r["split"] == "test"]
    tr, te = [gold[i] for i in tr_i], [gold[i] for i in te_i]
    X_tr, X_te = X[tr_i], X[te_i]
    with_body = sum(1 for r in gold if r["has_body"])
    log.info("\n=== %s  (%s; %d rows, %d with body = %.0f%%; %d test)", name, encoder, len(gold), with_body,
             100 * with_body / len(gold), len(te))
    designs = {
        "13-class multinomial (ticket)": lambda a, ra, b: multinomial(a, [r["topic"] for r in ra], b),
        "two heads (gate LR C=1 + topic LR C=4)": lambda a, ra, b: two_heads(a, ra, b),
        "two heads (gate LR C=4 + topic LR C=4)": lambda a, ra, b: two_heads(a, ra, b, C_gate=4.0),
    }
    results = {}
    for dname, fn in designs.items():
        cv = cv_probs(X_tr, tr, fn)
        tau = best_tau(tr, cv)
        te_p = fn(X_tr, tr, X_te)
        m = gate_metrics(te, te_p, tau, list(TOPICS))
        ok, fails = gates_pass(m)
        p95 = precision_at(te, te_p, 0.95)
        p90 = precision_at(te, te_p, 0.90)
        log.info("  %-40s tau=%.2f  rec_fin=%.3f rec_gen=%.3f prec_mixed=%.3f prec_allow=%.3f topic=%.3f  %s",
                 dname, tau, m["recall_finance"], m["recall_general"], m["precision_mixed"], m["precision_allow"],
                 m["topic_accuracy"], "PASS" if ok else "FAIL " + ",".join(f.split("=")[0] for f in fails))
        log.info("  %-40s at rec_fin>=0.95: prec_mixed=%.3f prec_allow=%.3f rec_gen=%.3f (tau %.2f) | at >=0.90: prec_mixed=%.3f prec_allow=%.3f (tau %.2f)",
                 "", p95["precision_mixed"], p95["precision_allow"], p95["recall_general"], p95["tau"],
                 p90["precision_mixed"], p90["precision_allow"], p90["tau"])
        results[dname] = (m, p95, p90)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold-frozen", required=True, help="gold file as it was before SYS-47 (headline-only rows)")
    parser.add_argument("--gold-bodies", required=True, help="gold file after merge-bodies + re-label")
    parser.add_argument("--encoders", default=f"{PROBE_MODEL_NAME},{E5}")
    args = parser.parse_args(argv)
    for encoder in [e.strip() for e in args.encoders.split(",") if e.strip()]:
        short = "MiniLM" if "MiniLM" in encoder else encoder.split("/")[-1]
        run_cell(f"{short} x frozen gold", encoder, args.gold_frozen)
        run_cell(f"{short} x gold with bodies", encoder, args.gold_bodies)


if __name__ == "__main__":
    main()
