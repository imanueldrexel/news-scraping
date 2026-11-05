"""SYS-199 (#429): one NLI arm on the eval set -- held-out per-type table plus a wrong-premise control.

Held-out (arm A's protocol): per type, 20 random halves by seed; tau is chosen on one half for recall 0.9 and the
recall / false-flag rates are measured on the other; both directions, averaged.

Wrong-premise control: every hypothesis is scored against the premise of another seed of the same type. A model that
reads the premise cannot tell faithful from unfaithful then, so the AUC of p_entail (faithful vs unfaithful) should
fall to about 0.5; an AUC that stays high means the model is judging the hypothesis alone (generator style), and its
eval-set numbers overstate it. The arm B training pairs let a hypothesis-only classifier reach 0.74-0.82 on the eval
set, so this is the check that separates learning the task from learning the generator.

  venv\\Scripts\\python.exe scripts/experiments/compare_nli_arms.py --model <name or dir> --cache <scores.json>
"""
import argparse
import json
import os
import random
import sys
from collections import defaultdict
from typing import Dict, List, Sequence

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import eval_nli  # noqa: E402

PAIRS = os.path.join(REPO, "tests", "fixtures", "nli_eval", "pairs.jsonl")
NEAR = os.path.join(REPO, "tests", "fixtures", "nli_eval", "near_copies.jsonl")      # ADR-029
SPLITS = 20
# ADR-030 decision 3: a type's targeted-set numbers stand only when the model needs the premise to get them.
MAX_AUC_WRONG_PREMISE = 0.65


def wrong_premise(pairs: Sequence[dict]) -> List[dict]:
    """Each pair with the premise of another seed of its type (a seeded rotation of the type's seeds, so no seed
    keeps its own premise)."""
    by_type: Dict[str, List[str]] = defaultdict(list)
    premise = {}
    for p in pairs:
        if p["seed_id"] not in premise:
            premise[p["seed_id"]] = p["premise"]
            by_type[p["error_type"]].append(p["seed_id"])
    other = {}
    for t, seeds in by_type.items():
        order = sorted(seeds)
        random.Random(t).shuffle(order)
        for i, s in enumerate(order):
            other[s] = order[(i + 1) % len(order)]
    return [{**p, "id": p["id"] + "~wrong", "premise": premise[other[p["seed_id"]]]} for p in pairs]


def identity(pairs: Sequence[dict]) -> List[dict]:
    """One faithful pair per seed whose hypothesis IS the premise. The generator drops verbatim copies, so every
    near-copy in the targeted pairs is a one-edit corruption; a model can learn "near-identical = unfaithful" and the
    held-out table cannot see it (arm B 2026-11-04 flagged 98% of these)."""
    seen = {}
    for p in pairs:
        seen.setdefault(p["seed_id"], p)
    return [{**p, "id": s + "~id", "hypothesis": p["premise"], "label": eval_nli.FAITHFUL, "kind": "identity"}
            for s, p in seen.items()]


def auc(pos: Sequence[float], neg: Sequence[float]) -> float:
    """P(a faithful pair scores above an unfaithful one), ties half."""
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def held_out(group: Sequence[dict], scores: Dict[str, float], recall: float = 0.9, splits: int = SPLITS) -> dict:
    seeds = sorted({p["seed_id"] for p in group})
    rows, taus = [], []
    for rep in range(splits):
        order = list(seeds)
        random.Random(rep).shuffle(order)
        half = set(order[:len(order) // 2])
        for fit_in_half in (True, False):
            fit = [p for p in group if (p["seed_id"] in half) == fit_in_half]
            test = [p for p in group if (p["seed_id"] in half) != fit_in_half]
            tau = eval_nli.choose_tau([scores[p["id"]] for p in fit if p["label"] == eval_nli.UNFAITHFUL], recall)
            taus.append(tau)
            rows.append([eval_nli.rate([scores[p["id"]] for p in test if p["label"] == eval_nli.UNFAITHFUL], tau),
                         eval_nli.rate([scores[p["id"]] for p in test if p["kind"] == "restatement"], tau),
                         eval_nli.rate([scores[p["id"]] for p in test if p["kind"] == "hard_positive"], tau)])
    mean = [sum(r[i] for r in rows if r[i] is not None) / max(sum(r[i] is not None for r in rows), 1) for i in range(3)]
    return {"recall": mean[0], "ff_restated": mean[1], "ff_hard": mean[2], "tau_min": min(taus), "tau_max": max(taus),
            "tau_median": sorted(taus)[len(taus) // 2]}


def report(pairs: Sequence[dict], scores: Dict[str, float], near: Sequence[dict] = ()) -> Dict[str, dict]:
    out = {}
    for t in sorted({p["error_type"] for p in pairs}):
        g = [p for p in pairs if p["error_type"] == t]
        faithful = lambda ids: [scores[i] for i in ids]  # noqa: E731
        row = held_out(g, scores)
        row["auc"] = auc(faithful(p["id"] for p in g if p["label"] == eval_nli.FAITHFUL),
                         faithful(p["id"] for p in g if p["label"] == eval_nli.UNFAITHFUL))
        row["auc_wrong_premise"] = auc(faithful(p["id"] + "~wrong" for p in g if p["label"] == eval_nli.FAITHFUL),
                                       faithful(p["id"] + "~wrong" for p in g if p["label"] == eval_nli.UNFAITHFUL))
        ident = [scores[s + "~id"] for s in sorted({p["seed_id"] for p in g})]
        row["ff_identity"] = eval_nli.rate(ident, row["tau_median"])
        row["ff_identity_05"] = eval_nli.rate(ident, 0.5)
        row["ff_near_copy"] = eval_nli.rate([scores[n["id"]] for n in near if n["error_type"] == t], row["tau_median"])
        # nan (a label missing) is no pass either: nothing shows the model reads the premise
        row["premise_gate"] = "ok" if row["auc_wrong_premise"] <= MAX_AUC_WRONG_PREMISE else "FAIL"
        out[t] = row
    return out


def table(rep: Dict[str, dict]) -> str:
    f = lambda x: "-" if x is None else f"{x:.2f}"  # noqa: E731
    lines = [f"| type | ADR-030 (AUC wrong premise <= {MAX_AUC_WRONG_PREMISE}) | held-out recall | ff restated | ff hard "
             "| tau range | AUC | AUC wrong premise | ff identity @median tau | ff identity @0.5 "
             "| ff near-copy @median tau |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for t, r in rep.items():
        lines.append(f"| {t} | {r['premise_gate']} | {f(r['recall'])} | {f(r['ff_restated'])} | {f(r['ff_hard'])} | "
                     f"{f(r['tau_min'])}-{f(r['tau_max'])} | {f(r['auc'])} | {f(r['auc_wrong_premise'])} | "
                     f"{f(r['ff_identity'])} | {f(r['ff_identity_05'])} | {f(r.get('ff_near_copy'))} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--cache", required=True, help="JSON {id: p_entail}; pairs missing from it are scored")
    ap.add_argument("--pairs", default=PAIRS)
    ap.add_argument("--near-copies", default=NEAR, help="ADR-029 faithful near-copies; skipped when the file is absent")
    args = ap.parse_args(argv)
    pairs = eval_nli.load_pairs(args.pairs)
    near = eval_nli.load_pairs(args.near_copies) if os.path.exists(args.near_copies) else []
    every = pairs + wrong_premise(pairs) + identity(pairs) + near
    scores = {}
    if os.path.exists(args.cache):
        with open(args.cache, encoding="utf-8") as f:
            scores = json.load(f)
    todo = [p for p in every if p["id"] not in scores]
    if todo:
        scores.update(eval_nli.score_with_model(todo, args.model))
        with open(args.cache, "w", encoding="utf-8") as f:
            json.dump(scores, f)
    print(f"model: {args.model}")
    print(table(report(pairs, scores, near)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
