"""SYS-197 (#427, ADR-024): score an NLI eval set and report, per error type, what the checker catches.

Input: a JSONL of pairs
  {"id", "error_type", "premise", "hypothesis", "label": "unfaithful"|"faithful", "kind": "corrupted"|"restatement"|"hard_positive"}
`unfaithful` = the hypothesis states what the premise does not support (a corruption); `faithful` = it does
(a restatement, or a hard positive that keeps the corruption's cue words). A pair is FLAGGED when
p_entail < tau. Per error type this prints:
  - tau: the lowest threshold that flags >= --recall of the unfaithful pairs (None if there are none);
  - recall at tau, and the false-flag rate at tau on the faithful pairs (restatements and hard positives apart);
  - hyp_only: cross-validated accuracy of a classifier that sees the HYPOTHESIS ALONE (> ~0.6 on balanced pairs
    means the edits leak the label and the set measures the edit, not the source).
`--model` scores with the Hugging Face NLI checkpoint; `--scores` reads {id: p_entail} instead (no model).
Usage:
  venv\\Scripts\\python.exe scripts/experiments/eval_nli.py --pairs tests/fixtures/nli_eval/pairs.jsonl --model <name>
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Sequence

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

UNFAITHFUL, FAITHFUL = "unfaithful", "faithful"


def load_pairs(path: str) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        pairs = [json.loads(line) for line in f if line.strip()]
    for p in pairs:
        if p["label"] not in (UNFAITHFUL, FAITHFUL):
            raise ValueError(f"{p['id']}: label must be unfaithful|faithful, got {p['label']!r}")
    return pairs


def choose_tau(unfaithful_scores: Sequence[float], recall: float) -> Optional[float]:
    """The lowest tau with P(p_entail < tau) >= recall over the unfaithful pairs; None without any."""
    if not unfaithful_scores:
        return None
    ordered = sorted(unfaithful_scores)
    k = max(1, math.ceil(recall * len(ordered)))
    return math.nextafter(ordered[k - 1], math.inf)


def rate(scores: Sequence[float], tau: Optional[float]) -> Optional[float]:
    if tau is None or not scores:
        return None
    return sum(s < tau for s in scores) / len(scores)


def hypothesis_only_accuracy(pairs: Sequence[dict], folds: int = 5) -> Optional[float]:
    """Cross-validated accuracy of word/char n-grams of the hypothesis alone; None when a class is too small."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.pipeline import make_pipeline
    y = [p["label"] == UNFAITHFUL for p in pairs]
    smallest = min(sum(y), len(y) - sum(y))
    if smallest < 2:
        return None
    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True), LogisticRegression(max_iter=1000))
    cv = StratifiedKFold(n_splits=min(folds, smallest), shuffle=True, random_state=0)
    return float(cross_val_score(model, [p["hypothesis"] for p in pairs], y, cv=cv).mean())


def evaluate(pairs: Sequence[dict], scores: Dict[str, float], recall: float) -> Dict[str, dict]:
    by_type: Dict[str, List[dict]] = defaultdict(list)
    for p in pairs:
        by_type[p["error_type"]].append(p)
    report = {}
    for error_type, group in sorted(by_type.items()):
        bad = [scores[p["id"]] for p in group if p["label"] == UNFAITHFUL]
        tau = choose_tau(bad, recall)
        kinds = {k: [scores[p["id"]] for p in group if p["label"] == FAITHFUL and p["kind"] == k]
                 for k in ("restatement", "hard_positive")}
        report[error_type] = {
            "n_unfaithful": len(bad), "n_restatement": len(kinds["restatement"]),
            "n_hard_positive": len(kinds["hard_positive"]), "tau": tau, "recall": rate(bad, tau),
            "false_flag_restatement": rate(kinds["restatement"], tau),
            "false_flag_hard_positive": rate(kinds["hard_positive"], tau),
            "hyp_only": hypothesis_only_accuracy(group),
        }
    return report


def table(report: Dict[str, dict]) -> str:
    def f(x):
        return "-" if x is None else f"{x:.2f}"
    head = "| error type | n bad | n ok (restated / hard) | tau | recall | false-flag restated | false-flag hard | hyp-only |"
    rows = [head, "|" + "---|" * 8]
    for t, r in report.items():
        rows.append(f"| {t} | {r['n_unfaithful']} | {r['n_restatement']} / {r['n_hard_positive']} | {f(r['tau'])} | "
                    f"{f(r['recall'])} | {f(r['false_flag_restatement'])} | {f(r['false_flag_hard_positive'])} | "
                    f"{f(r['hyp_only'])} |")
    return "\n".join(rows)


def score_with_model(pairs: Sequence[dict], model_name: str) -> Dict[str, float]:
    from newscrawler.core.nli_check import HfScorer
    scorer = HfScorer(model_name)
    out = scorer.score([(p["premise"], p["hypothesis"]) for p in pairs])
    print(f"model: {scorer.revision}", file=sys.stderr)
    return {p["id"]: e for p, (e, _, _) in zip(pairs, out)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--recall", type=float, default=0.9, help="recall target for tau (default 0.9)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--model")
    src.add_argument("--scores", help="JSON {id: p_entail}")
    ap.add_argument("--json", help="also write the report here")
    args = ap.parse_args(argv)
    pairs = load_pairs(args.pairs)
    if args.scores:
        with open(args.scores, encoding="utf-8") as f:
            scores = json.load(f)
    else:
        scores = score_with_model(pairs, args.model)
    report = evaluate(pairs, scores, args.recall)
    print(table(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
