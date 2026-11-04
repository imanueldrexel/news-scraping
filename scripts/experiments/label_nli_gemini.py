"""SYS-197 (#427, ADR-026): Gemini labels the seeded blind 40 of the NLI pair sample with ADR-025's rubric.

Gemini gets what Claude had: premise, hypothesis, error type and intended label. It never sees Claude's labels.
10 rows per call (4 calls for 40, inside the free tier's 20/day). Rows already in --out are skipped, so a run stopped by
a 429 resumes where it stopped. Score afterwards:
  venv\\Scripts\\python.exe scripts/experiments/score_nli_handcheck.py score --second tests/fixtures/nli_eval/handcheck_gemini_blind.csv
Usage:
  venv\\Scripts\\python.exe scripts/experiments/label_nli_gemini.py
"""
import argparse
import csv
import json
import os
import sys
from typing import Dict, List

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
FIX = os.path.join(REPO, "tests", "fixtures", "nli_eval")
BLIND = os.path.join(FIX, "handcheck_owner_blind.csv")
OUT = os.path.join(FIX, "handcheck_gemini_blind.csv")
VALID_COL = "valid (y/n)"
CODES = ("label", "type", "multi", "cue", "copy", "garbled")
FIELDS = ["id", "error_type", "premise", "hypothesis", "intended", VALID_COL, "code", "reason"]

TYPES = {
    "cause": "the stated cause (karena, akibat, sehingga..., dipicu, didorong) is replaced by another, or a cause is "
             "added where the premise gives none",
    "hedge": "a hedge (diduga, dugaan, kemungkinan, diperkirakan, mungkin, apakah...) is removed so the claim reads "
             "as established fact",
    "denial": "a denial (membantah, menepis, menampik, menyangkal, tidak benar...) is flipped into an affirmation, or "
              "the reverse",
    "end": "an end date or deadline (hingga, sampai, paling lambat...) is changed",
    "schedule": "a planned future event or its time is added or changed",
}

PROMPT = """You check test pairs for a faithfulness checker of Indonesian news. Each row has a PREMISE (a real
sentence), a HYPOTHESIS, an error type and an INTENDED label:
- intended "unsupported": the hypothesis was meant to be a corruption of the premise of this error type;
- intended "supported": the hypothesis was meant to be fully supported by the premise (a restatement, or a shortened
  or reordered sentence keeping the error type's cue words).

Error types:
{types}

Label each row valid "y" only when BOTH hold:
1. the intended label is right: "supported" means the premise ALONE entails the hypothesis, and "unsupported" means it
   does not;
2. the pair tests its type: an unsupported row changes one thing, and that thing is of the stated error type; a
   supported row only needs entailment.
Otherwise "n", with one code:
- label: the intended label is wrong;
- type: the change is of another kind, or of a word that is not the type's cue;
- multi: a second change of another kind;
- cue: the premise has no instance of the type, so the test is empty;
- copy: verbatim or trivial;
- garbled: the hypothesis has no clear meaning.
Two changes of the same type (two hedges dropped) are still "y".

Rows (JSON):
{rows}

Reply as JSON only: {{"labels": [{{"id": "...", "valid": "y"|"n", "code": "" or one code, "reason": "one short sentence"}}]}}
with exactly one entry per row id."""


def read(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_prompt(batch: List[dict]) -> str:
    rows = [{k: r[k] for k in ("id", "error_type", "premise", "hypothesis", "intended")} for r in batch]
    types = "\n".join(f"- {t}: {d}" for t, d in TYPES.items())
    return PROMPT.format(types=types, rows=json.dumps(rows, ensure_ascii=False, indent=1))


def parse(text: str, batch: List[dict]) -> Dict[str, dict]:
    """{id: {valid, code, reason}} for exactly the batch's ids; ValueError on anything else."""
    labels = json.loads(text)["labels"]
    got = {}
    for lab in labels:
        valid = str(lab.get("valid", "")).strip().lower()
        code = str(lab.get("code") or "").strip().lower()
        if valid not in ("y", "n") or (valid == "n" and code not in CODES):
            raise ValueError(f"bad label {lab!r}")
        got[lab["id"]] = {"valid": valid, "code": code if valid == "n" else "", "reason": str(lab.get("reason", ""))}
    want = {r["id"] for r in batch}
    if set(got) != want:
        raise ValueError(f"ids differ: missing {sorted(want - set(got))}, extra {sorted(set(got) - want)}")
    return got


def label(rows: List[dict], done: List[dict], provider, batch_size: int, out_path: str) -> dict:
    """Label the rows not in `done`, writing `out_path` after every call. Stops at a provider transient error."""
    from newscrawler.core.extraction_provider import ProviderTransientError
    have = {r["id"]: r for r in done}
    todo = [r for r in rows if r["id"] not in have]
    stats = {"calls": 0, "labelled": 0, "stopped": None}
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        try:
            completion = provider.complete(build_prompt(batch))
        except ProviderTransientError as e:
            stats["stopped"] = f"{type(e).__name__}: {e}"[:200]
            break
        stats["calls"] += 1
        got = parse(completion.text, batch)
        for r in batch:
            g = got[r["id"]]
            have[r["id"]] = {**{k: r[k] for k in FIELDS[:5]}, VALID_COL: g["valid"], "code": g["code"],
                             "reason": g["reason"]}
            stats["labelled"] += 1
        write(out_path, [have[r["id"]] for r in rows if r["id"] in have])
    return stats


def write(path: str, rows: List[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--blind", default=BLIND)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--batch", type=int, default=10)
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO, ".env"))
    from newscrawler.core.extraction_provider import build_provider
    provider = build_provider("gemini")
    if provider is None:
        print("GEMINI_API_KEY is not set")
        return 1
    stats = label(read(args.blind), read(args.out), provider, args.batch, args.out)
    print(f"{provider.name}: {stats}")
    return 0 if stats["stopped"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
