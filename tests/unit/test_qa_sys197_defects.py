"""QA's failing tests for SYS-197 (#427): qa-defects #431-#434, copied from the issues.

Only the paths are made absolute (the issues ran them from the repo root). #431's second test (family leak <= 0.60)
is not here: the owner dropped it (ADR-030 decision 3, comment on #431); its first test still applies.
"""
import csv
import importlib.util
import json
import os
import re

import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, cross_val_score
from sklearn.pipeline import make_pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIX = os.path.join(ROOT, "tests", "fixtures", "nli_eval")
PAIRS = os.path.join(FIX, "pairs.jsonl")
spec = importlib.util.spec_from_file_location("eval_nli", os.path.join(ROOT, "scripts", "experiments", "eval_nli.py"))
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


# ---- #431: the hypothesis-only check keeps a seed's pairs in one fold ----
def _group(t):
    pairs = [json.loads(line) for line in open(PAIRS, encoding="utf-8") if line.strip()]
    return [p for p in pairs if p["error_type"] == t]


def _grouped(g):
    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True), LogisticRegression(max_iter=1000))
    return cross_val_score(model, [p["hypothesis"] for p in g], [p["label"] == "unfaithful" for p in g],
                           groups=[p["seed_id"] for p in g], cv=GroupKFold(5)).mean()


@pytest.mark.parametrize("t", ["cause", "denial", "end", "hedge", "schedule"])
def test_harness_hypothesis_only_keeps_seed_mates_in_one_fold(t):
    g = _group(t)
    assert abs(ev.hypothesis_only_accuracy(g) - _grouped(g)) <= 0.03


# ---- #432: pairs the hand check proved mislabelled are not scored under that label ----
def _jsonl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def test_pairs_proved_mislabelled_are_not_scored_under_that_label():
    with open(os.path.join(FIX, "handcheck_final.csv"), encoding="utf-8-sig", newline="") as f:
        wrong = {r["id"] for r in csv.DictReader(f) if r["label_ok"] == "n"}
    assert wrong
    raw = {p["id"]: p["label"] for p in _jsonl(os.path.join(FIX, "pairs_raw.jsonl"))}
    still = [p["id"] for p in _jsonl(PAIRS)
             if p["id"] in wrong and p["label"] == raw[p["id"]]]
    assert not still, f"{len(still)} known-mislabelled pairs still scored as labelled: {still}"


# ---- #433: each type is compared with the lexicon gate alone ----
def test_report_compares_each_type_with_the_lexicon_gate_alone():
    pairs = ev.load_pairs(os.path.join(FIX, "golden.jsonl"))
    report = ev.evaluate(pairs, {p["id"]: 0.5 for p in pairs}, 0.9)
    for error_type, row in report.items():
        assert any("gate" in k or "lexicon" in k for k in row), (error_type, sorted(row))


# ---- #434: a golden faithful row adds nothing its premise lacks ----
STOP = {"di", "yang", "dan", "sebab", "karena", "membuat", "akibat"}


def test_golden_faithful_rows_add_nothing_the_premise_lacks():
    bad = []
    for line in open(os.path.join(FIX, "golden.jsonl"), encoding="utf-8"):
        p = json.loads(line)
        if p["label"] != "faithful":
            continue
        premise = set(re.findall(r"\w+", p["premise"].lower()))
        extra = [w for w in re.findall(r"\w+", p["hypothesis"].lower()) if w not in premise and w not in STOP]
        if extra:
            bad.append((p["id"], extra))
    assert not bad, bad
