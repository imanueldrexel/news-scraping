"""SYS-197 (#427, ADR-027 decision 5): move the type misfits of the generated NLI pairs to the `other` bucket.

A misfit keeps its label (it still counts in the overall NLI score) but tests another kind of error than its
declared type, so it must not count in that type's own number. Two rules, from the hand check's type_ok column:
  - denial-no-act: a denial seed with no act of denying (gen_nli_pairs.DENIAL_ACT): "pandangan keliru",
    "secara tidak benar", "penyangkalan perubahan iklim". Every pair of the seed goes, since none tests a denial;
  - cause-effect-side: a cause corruption whose edit sits on the effect side of the nearest causal link in its
    clause ("X sehingga <edit>", "<edit> karena X"). An edit that adds, drops or swaps a causal link, or adds a
    purpose ("agar ...", an invented motive), is a cause edit and stays.
The output has `error_type` "other" for a misfit, with `declared_type` and `misfit` (the rule) kept beside it;
eval_nli.py then reports `other` as its own row. With --check it prints each rule's hits against the hand check.
Usage:
  venv\\Scripts\\python.exe scripts/experiments/filter_nli_pairs.py [--check]
"""
import argparse
import csv
import difflib
import json
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Optional, Set

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from gen_nli_pairs import DENIAL_ACT  # noqa: E402
from newscrawler.core.causal_check import FORWARD, _BOUNDARY, _causal_matches, _kind  # noqa: E402

FIX = os.path.join(REPO, "tests", "fixtures", "nli_eval")
RAW = os.path.join(FIX, "pairs_raw.jsonl")
OUT = os.path.join(FIX, "pairs.jsonl")
FINAL = os.path.join(FIX, "handcheck_final.csv")
OTHER = "other"

_WORD = re.compile(r"\w+(?:[-,.]\w+)*")    # words only: a dropped quote or stray byte is no edit
# "yang timbul dari keputusan tersebut": the object is the cause (ADR-027's disputes counted it as one).
_ORIGIN = re.compile(r"\b(?:timbul|berasal|bersumber)\s+dari\b", re.IGNORECASE)
_PURPOSE = re.compile(r"\b(?:agar|supaya|guna|demi|untuk)\b", re.IGNORECASE)


def edits(premise: str, hypothesis: str) -> List[tuple]:
    """(offset in the premise, premise text, hypothesis text) of each word-level change."""
    tp, th = list(_WORD.finditer(premise)), list(_WORD.finditer(hypothesis))
    a, b = [t.group(0).lower() for t in tp], [t.group(0).lower() for t in th]
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        p_text = premise[tp[i1].start():tp[i2 - 1].end()] if i2 > i1 else ""
        h_text = hypothesis[th[j1].start():th[j2 - 1].end()] if j2 > j1 else ""
        out.append((tp[i1].start() if i1 < len(tp) else len(premise), p_text, h_text))
    return out


def links(text: str) -> List[tuple]:
    """(offset, is_forward) of each causal link: the gate's words, plus "timbul dari" (backward)."""
    return ([(m.start(), _kind(m.group(0)) == FORWARD) for m in _causal_matches(text)]
            + [(m.start(), False) for m in _ORIGIN.finditer(text)])


def denial_misfit(pair: dict) -> bool:
    return pair["error_type"] == "denial" and not DENIAL_ACT.search(pair["premise"])


def cause_misfit(pair: dict) -> bool:
    if pair["error_type"] != "cause" or pair["kind"] != "corrupted":
        return False
    premise = pair["premise"]
    changes = edits(premise, pair["hypothesis"])
    if not changes:
        return False
    for _, p_text, h_text in changes:
        if links(p_text) or links(h_text) or (_PURPOSE.search(h_text) and not _PURPOSE.search(p_text)):
            return False                        # the edit is the link itself, or an invented motive
    at = changes[0][0]
    cuts = [0] + [m.start() for m in _BOUNDARY.finditer(premise)] + [len(premise) + 1]
    lo, hi = max(c for c in cuts if c <= at), min(c for c in cuts if c > at)
    near = [(pos, fwd) for pos, fwd in links(premise) if lo <= pos < hi]
    if not near:
        return False                            # no link in the edit's clause: nothing says which side it is on
    pos, forward = min(near, key=lambda x: abs(x[0] - at))
    return at > pos if forward else at < pos


RULES = {"denial-no-act": denial_misfit, "cause-effect-side": cause_misfit}


def misfit(pair: dict) -> Optional[str]:
    return next((name for name, rule in RULES.items() if rule(pair)), None)


def mislabelled(final: List[dict]) -> Set[str]:
    """The pairs the hand check proved carry the wrong label (label_ok n, owner rulings included)."""
    return {r["id"] for r in final if r["label_ok"] == "n"}


def bucket(pairs: List[dict], wrong_label: Set[str] = frozenset()) -> List[dict]:
    """Every pair, a misfit moved to `other`; a pair in `wrong_label` is dropped (#432): its label is known to be
    wrong, so it would count against the model wherever it scored."""
    out = []
    for p in pairs:
        if p["id"] in wrong_label:
            continue
        reason = misfit(p)
        out.append({**p, "error_type": OTHER, "declared_type": p["error_type"], "misfit": reason} if reason
                   else {**p, "declared_type": p["error_type"], "misfit": None})
    return out


def check(pairs: List[dict], final: List[dict]) -> Dict[str, dict]:
    """Per rule, its hits among the hand-checked pairs whose type was judged (label_ok y): misfit / judged fit; plus
    the judged misfits no rule catches."""
    judged = {r["id"]: r["type_ok"] for r in final if r["type_ok"] in ("y", "n")}
    sample = [p for p in pairs if p["id"] in judged]
    report = {}
    for name, rule in RULES.items():
        hits = [p["id"] for p in sample if rule(p)]
        report[name] = {"misfit": sum(judged[i] == "n" for i in hits), "fit": [i for i in hits if judged[i] == "y"],
                        "full_set": sum(rule(p) for p in pairs)}
    report["missed"] = [p["id"] for p in sample if judged[p["id"]] == "n" and not misfit(p)]
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pairs", default=RAW)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", action="store_true", help="measure the rules against handcheck_final.csv's type_ok")
    args = ap.parse_args(argv)
    with open(args.pairs, encoding="utf-8") as f:
        pairs = [json.loads(line) for line in f if line.strip()]
    with open(FINAL, encoding="utf-8-sig", newline="") as f:
        final = list(csv.DictReader(f))
    if args.check:
        report = check(pairs, final)
        for name in RULES:
            r = report[name]
            print(f"{name}: hand check {r['misfit']} misfit, {len(r['fit'])} judged fit {r['fit']}; "
                  f"full set {r['full_set']} pairs")
        print(f"judged misfits no rule catches: {report['missed']}")
    wrong = mislabelled(final)
    rows = bucket(pairs, wrong)
    dropped = Counter(p["error_type"] for p in pairs if p["id"] in wrong)
    print(f"dropped {sum(dropped.values())} pairs the hand check proved mislabelled: {dict(sorted(dropped.items()))}")
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:     # LF: .gitattributes holds fixtures to it
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    moved = Counter(r["declared_type"] for r in rows if r["misfit"])
    total = Counter(r["declared_type"] for r in rows)
    for t in sorted(total):
        print(f"{t:9s} {total[t]:4d} pairs, {moved[t]:3d} to {OTHER}")
    print(f"wrote {len(rows)} pairs to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
