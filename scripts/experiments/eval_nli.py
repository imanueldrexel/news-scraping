"""SYS-197 (#427, ADR-024): score an NLI eval set and report, per error type, what the checker catches.

Input: a JSONL of pairs
  {"id", "error_type", "premise", "hypothesis", "label": "unfaithful"|"faithful", "kind": "corrupted"|"restatement"|"hard_positive"}
`unfaithful` = the hypothesis states what the premise does not support (a corruption); `faithful` = it does
(a restatement, or a hard positive that keeps the corruption's cue words). A pair is FLAGGED when
p_entail < tau. Per error type this prints:
  - tau: the lowest threshold that flags >= --recall of the unfaithful pairs (None if there are none);
  - recall at tau, and the false-flag rate at tau on the faithful pairs (restatements and hard positives apart);
  - hyp_only: cross-validated accuracy of a classifier that sees the HYPOTHESIS ALONE, folds grouped by seed
    (> ~0.6 on balanced pairs means the edits leak the label; ADR-030 keeps the families and gates a model's
    numbers on its wrong-premise AUC in compare_nli_arms.py instead);
  - gate_*: the same pairs through the lexicon gate the type maps to (`GATES`), with no NLI: its recall, its false
    flags, and the unfaithful pairs only NLI (at tau) or only the gate catches (#433).
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
from datetime import date
from typing import Dict, List, Optional, Sequence

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from newscrawler.core import causal_check, source_check, story_arc  # noqa: E402

UNFAITHFUL, FAITHFUL = "unfaithful", "faithful"
# What the period gate resolves a month without a year against; the pairs carry no date (any fixed day gives the same
# key on both sides, since premise and hypothesis are resolved alike).
GATE_TODAY = date(2026, 11, 5)


def _causal_gate(premise: str, hypothesis: str) -> bool:
    """The causal gate (SYS-152, ADR-019/020) with the whole premise as the one `sebab` quote -- the most it can be
    given: cause, hedge and denial are all judged on a causal link (a hedged or denied link backs no flat claim)."""
    return bool(causal_check.unbacked_causes([("hari_ini", hypothesis)], [(0, premise)], {0: premise}))


def _end_gate(premise: str, hypothesis: str) -> bool:
    return bool(source_check.unbacked_end_times(hypothesis, premise))


def _schedule_gate(premise: str, hypothesis: str) -> bool:
    """A future time or period the premise does not give, judged as in the agenda (every one is read)."""
    return bool(source_check.unstated_future_times(hypothesis, premise)
                or story_arc.unstated_periods(hypothesis, GATE_TODAY, premise, "agenda"))


# The lexicon gate each error type maps to (#433); a type not listed (`other`) has none.
GATES = {"cause": _causal_gate, "hedge": _causal_gate, "denial": _causal_gate, "end": _end_gate,
         "schedule": _schedule_gate}


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
    """Cross-validated accuracy of word/char n-grams of the hypothesis alone; None when a class is too small.
    A seed's pairs stay in one fold (#431, ADR-030): its corruptions, restatement and hard positive are near-copies
    with opposite labels, and a shuffled split puts them on both sides, which pushes the score to chance. A pair
    without a `seed_id` is its own group."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold, cross_val_score
    from sklearn.pipeline import make_pipeline
    y = [p["label"] == UNFAITHFUL for p in pairs]
    groups = [p.get("seed_id") or p["id"] for p in pairs]
    smallest = min(sum(y), len(y) - sum(y))
    if smallest < 2 or len(set(groups)) < 2:
        return None
    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True), LogisticRegression(max_iter=1000))
    cv = GroupKFold(n_splits=min(folds, smallest, len(set(groups))))
    return float(cross_val_score(model, [p["hypothesis"] for p in pairs], y, groups=groups, cv=cv).mean())


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
            **gate_comparison(group, scores, tau, GATES.get(error_type)),
        }
    return report


def gate_comparison(group: Sequence[dict], scores: Dict[str, float], tau: Optional[float], gate) -> dict:
    """The lexicon gate alone on `group` (#433): its recall and false-flag rates, and per unfaithful pair which of NLI
    (p_entail < tau) and the gate catches it. All None when the type has no gate."""
    keys = ("gate_recall", "gate_false_flag_restatement", "gate_false_flag_hard_positive", "nli_only", "gate_only",
            "both")
    if gate is None:
        return dict.fromkeys(keys)
    flagged = {p["id"]: gate(p["premise"], p["hypothesis"]) for p in group}

    def share(kind_or_label):
        rows = [flagged[p["id"]] for p in group
                if (p["label"] == UNFAITHFUL if kind_or_label == UNFAITHFUL
                    else p["label"] == FAITHFUL and p["kind"] == kind_or_label)]
        return sum(rows) / len(rows) if rows else None
    bad = [p["id"] for p in group if p["label"] == UNFAITHFUL]
    nli = {i: tau is not None and scores[i] < tau for i in bad}
    return {"gate_recall": share(UNFAITHFUL), "gate_false_flag_restatement": share("restatement"),
            "gate_false_flag_hard_positive": share("hard_positive"),
            "nli_only": sum(nli[i] and not flagged[i] for i in bad),
            "gate_only": sum(flagged[i] and not nli[i] for i in bad), "both": sum(nli[i] and flagged[i] for i in bad)}


def table(report: Dict[str, dict]) -> str:
    def f(x):
        return "-" if x is None else f"{x:.2f}"

    def n(x):
        return "-" if x is None else str(x)
    head = ("| error type | n bad | n ok (restated / hard) | tau | recall | false-flag restated | false-flag hard | "
            "hyp-only | gate recall | gate ff restated | gate ff hard | caught by NLI only / gate only / both |")
    rows = [head, "|" + "---|" * 12]
    for t, r in report.items():
        rows.append(f"| {t} | {r['n_unfaithful']} | {r['n_restatement']} / {r['n_hard_positive']} | {f(r['tau'])} | "
                    f"{f(r['recall'])} | {f(r['false_flag_restatement'])} | {f(r['false_flag_hard_positive'])} | "
                    f"{f(r['hyp_only'])} | {f(r['gate_recall'])} | {f(r['gate_false_flag_restatement'])} | "
                    f"{f(r['gate_false_flag_hard_positive'])} | {n(r['nli_only'])} / {n(r['gate_only'])} / "
                    f"{n(r['both'])} |")
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
