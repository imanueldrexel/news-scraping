"""SYS-197 (#427, ADR-025): validity of the LLM-written NLI pairs from Claude's pre-label and the owner's blind rows.

`build-blind` writes the owner's sheet: a seeded random N rows per error type from the hand-check sample, without
Claude's labels. `score` reads both label files and prints:
  - agreement: owner vs Claude on the rows the owner labelled (gate: >= 90%, ADR-025);
  - per error type: valid / total, with the owner's label winning where both exist, and the verdict against the
    81% family gate (`drop` below it, `borderline` from 81% to 87%, otherwise `keep`);
  - the reason codes of the invalid rows.
Exit 0 when the gate holds, 1 when it does not (then the owner labels the rest, per ADR-025), 2 when the owner's
sheet has unlabelled rows.
Usage:
  venv\\Scripts\\python.exe scripts/experiments/score_nli_handcheck.py build-blind
  venv\\Scripts\\python.exe scripts/experiments/score_nli_handcheck.py score
"""
import argparse
import csv
import os
import random
import sys
from collections import Counter, defaultdict
from typing import Dict, List

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIX = os.path.join(REPO, "tests", "fixtures", "nli_eval")
SAMPLE = os.path.join(FIX, "handcheck_sheet.csv")
CLAUDE = os.path.join(FIX, "handcheck_claude.csv")
OWNER = os.path.join(FIX, "handcheck_owner_blind.csv")

AGREEMENT_GATE = 0.90
FAMILY_GATE = 0.81
BORDERLINE_TOP = 0.87
VALID_COL = "valid (y/n)"


def read(path: str) -> List[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def yn(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in ("y", "n") else ""


def build_blind(sample: List[dict], per_type: int, seed: int) -> List[dict]:
    """`per_type` rows of each error type, in a shuffled order, with the label columns empty."""
    by_type: Dict[str, List[dict]] = defaultdict(list)
    for row in sample:
        by_type[row["error_type"]].append(row)
    rng = random.Random(seed)
    picked = [r for t in sorted(by_type) for r in rng.sample(by_type[t], min(per_type, len(by_type[t])))]
    rng.shuffle(picked)
    return [{**{k: r[k] for k in ("id", "error_type", "premise", "hypothesis", "intended")}, VALID_COL: "", "note": ""}
            for r in picked]


def verdict(share: float) -> str:
    """Below the spec's 81% gate: drop. From the gate to 87% (where n=40's interval still reaches below 81%): kept,
    flagged. Above: keep."""
    if share < FAMILY_GATE:
        return "drop"
    if share <= BORDERLINE_TOP:
        return "borderline"
    return "keep"


def score(claude: List[dict], owner: List[dict]) -> dict:
    claude_by_id = {r["id"]: r for r in claude}
    owner_labels = {r["id"]: yn(r[VALID_COL]) for r in owner}
    unlabelled = [i for i, v in owner_labels.items() if not v]
    both = [i for i, v in owner_labels.items() if v and i in claude_by_id]
    agree = sum(owner_labels[i] == yn(claude_by_id[i]["valid"]) for i in both)
    disagreements = [(i, claude_by_id[i]["valid"], owner_labels[i]) for i in both
                     if owner_labels[i] != yn(claude_by_id[i]["valid"])]
    families: Dict[str, Counter] = defaultdict(Counter)
    codes: Dict[str, Counter] = defaultdict(Counter)
    for row in claude:
        label = owner_labels.get(row["id"]) or yn(row["valid"])
        families[row["error_type"]][label] += 1
        if label == "n":
            codes[row["error_type"]][row.get("code") or "owner"] += 1
    per_family = {}
    for t, c in sorted(families.items()):
        total = c["y"] + c["n"]
        share = c["y"] / total if total else 0.0
        per_family[t] = {"valid": c["y"], "total": total, "share": share, "verdict": verdict(share),
                         "codes": dict(codes[t])}
    return {"agreement": agree / len(both) if both else None, "compared": len(both), "agree": agree,
            "disagreements": disagreements, "unlabelled": unlabelled, "families": per_family}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-blind")
    b.add_argument("--per-type", type=int, default=8)
    b.add_argument("--seed", type=int, default=20261103)
    b.add_argument("--out", default=OWNER)
    s = sub.add_parser("score")
    s.add_argument("--claude", default=CLAUDE)
    s.add_argument("--owner", default=OWNER)
    args = ap.parse_args(argv)

    if args.cmd == "build-blind":
        if os.path.exists(args.out):
            print(f"{args.out} exists; not overwriting the owner's labels")
            return 1
        rows = build_blind(read(SAMPLE), args.per_type, args.seed)
        with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} rows to {args.out}")
        return 0

    result = score(read(args.claude), read(args.owner))
    if result["unlabelled"]:
        print(f"owner sheet: {len(result['unlabelled'])} row(s) without y/n -- label them first")
        return 2
    gate_ok = result["agreement"] is not None and result["agreement"] >= AGREEMENT_GATE
    print(f"agreement owner vs Claude: {result['agree']}/{result['compared']} "
          f"({result['agreement']:.0%}) -> {'HOLDS' if gate_ok else 'FAILS: owner labels the other rows'}")
    for i, c, o in result["disagreements"]:
        print(f"  {i}: Claude {c}, owner {o}")
    for t, f in result["families"].items():
        print(f"{t:9s} {f['valid']}/{f['total']} ({f['share']:.0%}) {f['verdict']:10s} {f['codes'] or ''}")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
