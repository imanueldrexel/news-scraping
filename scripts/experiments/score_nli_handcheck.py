"""SYS-197 (#427, ADR-025/026/027): validity of the LLM-written NLI pairs.

Each pair gets two checks (ADR-027):
  - label_ok: the intended label is right. It is gated on Claude vs the blind second labeller (Gemini, ADR-026),
    >= 90% on the rows both labelled, and the owner rules on the disagreements;
  - type_ok: the pair tests its declared type. This is Claude's judgement; a misfit goes to the `other` bucket and is not dropped.
Old one-letter labels map by code: label/garbled/copy -> label_ok n; type/cue/multi -> label_ok y, type_ok n.

`build-blind` writes the blind sheet (a seeded N rows per type, no labels). `score` prints the label_ok agreement,
the disagreements (with the owner's ruling, if any), and per declared type the label_ok share against the 81% family
gate (`drop` below, `borderline` to 87%, `keep` above) next to the type_ok share. With --final it writes the per-row
result SYS-199 reads.
Exit 0 when the gate holds and every disagreement has a ruling; 1 when the gate fails; 3 when rulings are missing.
Usage:
  venv\\Scripts\\python.exe scripts/experiments/score_nli_handcheck.py build-blind
  venv\\Scripts\\python.exe scripts/experiments/score_nli_handcheck.py score --final
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
OWNER = os.path.join(FIX, "handcheck_owner_blind.csv")       # the blind sheet (ADR-025 meant the owner to fill it)
SECOND = os.path.join(FIX, "handcheck_gemini_blind.csv")
RULINGS = os.path.join(FIX, "handcheck_owner_rulings.csv")
FINAL = os.path.join(FIX, "handcheck_final.csv")
LABEL_CODES = ("label", "garbled", "copy")           # the intended label is wrong / undefined
TYPE_CODES = ("type", "cue", "multi")                # the label is right, the pair tests another kind

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


def checks(valid: str, code: str):
    """(label_ok, type_ok) of one labeller's row; type_ok is "" when label_ok is not y."""
    v, c = yn(valid), (code or "").strip().lower()
    if v == "y":
        return "y", "y"
    if v == "n" and c in TYPE_CODES:
        return "y", "n"
    if v == "n":
        return "n", ""
    return "", ""


def score(claude: List[dict], second: List[dict], rulings: List[dict]) -> dict:
    second_by_id = {r["id"]: checks(r[VALID_COL], r.get("code", "")) for r in second}
    ruled = {r["id"]: yn(r["label_ok"]) for r in rulings if yn(r["label_ok"])}
    unlabelled = [i for i, (lab, _) in second_by_id.items() if not lab]
    compared = agree = 0
    disagreements, final = [], []
    for row in claude:
        c_label, c_type = checks(row["valid"], row.get("code", ""))
        s_label = second_by_id.get(row["id"], ("", ""))[0]
        label, by = c_label, "claude"
        if s_label:
            compared += 1
            if s_label == c_label:
                agree += 1
                by = "agree"
            else:
                disagreements.append((row["id"], c_label, s_label, ruled.get(row["id"], "")))
                label, by = (ruled[row["id"]], "owner") if row["id"] in ruled else ("", "unresolved")
        elif row["id"] in ruled:
            label, by = ruled[row["id"]], "owner"
        type_ok = (c_type or "y") if label == "y" else ""
        final.append({"id": row["id"], "error_type": row["error_type"], "kind": row.get("kind", ""),
                      "intended": row["intended"], "label_ok": label, "type_ok": type_ok, "decided_by": by})
    families: Dict[str, Counter] = defaultdict(Counter)
    for f in final:
        if f["label_ok"]:
            families[f["error_type"]]["total"] += 1
            families[f["error_type"]]["label_ok"] += f["label_ok"] == "y"
            families[f["error_type"]]["type_ok"] += f["type_ok"] == "y"
    per_family = {}
    for t, c in sorted(families.items()):
        share = c["label_ok"] / c["total"] if c["total"] else 0.0
        per_family[t] = {"label_ok": c["label_ok"], "type_ok": c["type_ok"], "total": c["total"], "share": share,
                         "verdict": verdict(share)}
    return {"agreement": agree / compared if compared else None, "compared": compared, "agree": agree,
            "disagreements": disagreements, "unlabelled": unlabelled, "families": per_family, "final": final}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-blind")
    b.add_argument("--per-type", type=int, default=8)
    b.add_argument("--seed", type=int, default=20261103)
    b.add_argument("--out", default=OWNER)
    s = sub.add_parser("score")
    s.add_argument("--claude", default=CLAUDE)
    s.add_argument("--second", default=SECOND, help="the blind second labeller's sheet (ADR-026: Gemini's)")
    s.add_argument("--rulings", default=RULINGS, help="the owner's label_ok rulings on disagreements (ADR-027)")
    s.add_argument("--final", nargs="?", const=FINAL, default=None, help="write the per-row result (default path)")
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

    rulings = read(args.rulings) if os.path.exists(args.rulings) else []
    result = score(read(args.claude), read(args.second), rulings)
    if result["unlabelled"]:
        print(f"second sheet: {len(result['unlabelled'])} row(s) without y/n -- label them first")
        return 2
    gate_ok = result["agreement"] is not None and result["agreement"] >= AGREEMENT_GATE
    print(f"label_ok agreement, second labeller vs Claude: {result['agree']}/{result['compared']} "
          f"({result['agreement']:.1%}) -> {'HOLDS' if gate_ok else 'FAILS'}")
    for i, c, o, r in result["disagreements"]:
        print(f"  {i}: Claude {c}, second {o}, owner {r or 'NOT RULED'}")
    for t, f in result["families"].items():
        print(f"{t:9s} label_ok {f['label_ok']}/{f['total']} ({f['share']:.1%}) {f['verdict']:10s} "
              f"type_ok {f['type_ok']}/{f['label_ok']}")
    if args.final:
        with open(args.final, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(result["final"][0]))
            w.writeheader()
            w.writerows(result["final"])
        print(f"wrote {args.final}")
    if not gate_ok:
        return 1
    return 3 if any(not r for *_, r in result["disagreements"]) else 0


if __name__ == "__main__":
    sys.exit(main())
