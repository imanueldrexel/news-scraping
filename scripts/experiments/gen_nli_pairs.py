"""SYS-197 (#427, ADR-024 E4): LLM-written contrastive pairs for the NLI eval set, with a hard dollar cap.

Seeds are real sentences of stored articles that hold one error type's cue (the lexicon gates' own regexes):
cause, hedge, denial, end (an end date), schedule (a planned future event). For each seed the model writes
  - 2 `corrupted`: one atomic edit that makes the claim unsupported (invented cause, dropped hedge, flipped denial,
    changed end date, invented schedule),
  - 1 `restatement`: the same meaning in other words,
  - 1 `hard_positive`: a supported sentence that KEEPS the cue words.
Output is a JSONL in eval_nli.py's format (id, error_type, premise, hypothesis, label, kind) plus `seed_id` and
`verified: null` for the hand check (E5). Resumable: seeds already in the output are skipped.

Spend: tokens come from the provider's own usage, priced by peak_hours.cost_usd. The run stops BEFORE a call that
could pass --max-usd (default 3.00, owner 2026-10-25), and the running total is printed. These calls are not in
api_usage_log (replays never are); the total goes in the EXPERIMENTS.md entry.

  venv\\Scripts\\python.exe scripts/experiments/gen_nli_pairs.py --per-type 90 --out <path> [--max-usd 3] [--dry-run]

SYS-199 arm B (ADR-028) training pairs: `--exclude-pairs tests/fixtures/nli_eval/pairs.jsonl` keeps every article of the
eval set out, and `--workers N` runs N calls at once (the cap reserves worst case for each call in flight).
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

ERROR_TYPES = ("cause", "hedge", "denial", "end", "schedule")
MIN_WORDS, MAX_WORDS = 8, 45
# A call is assumed to cost at most this many tokens when deciding whether it can start inside the cap.
WORST_CALL_INPUT, WORST_CALL_OUTPUT = 1500, 1500

# ADR-027: the gate's denial regex also matches judgements ("pandangan keliru", "secara tidak benar") and the noun
# "penyangkalan"; a denial seed must hold an act of denying, or none of its pairs tests a flipped denial (5 of 5
# denial type misfits of the hand check). "tidak benar" counts unless it is an adverb ("secara tidak benar").
DENIAL_ACT = re.compile(r"\b(?:(?:mem|di)bantah|bantahan|menepis|ditepis|menampik|ditampik|menyangkal|disangkal|"
                        r"hoa(?:ks|x))\b|(?<!secara\s)\btidak\s+benar\b", re.IGNORECASE)

EDITS = {
    "cause": "replace the stated cause (the part that says why, not the result) with a different, plausible cause the "
             "sentence does not give (or state a cause where the sentence gives none)",
    "hedge": "remove the hedge (diduga, kemungkinan, dugaan, diperkirakan ...) so the claim reads as established fact",
    "denial": "flip the denial: turn what the source denies into something it affirms, or the reverse",
    "end": "change the end date, or the deadline, to a different date the sentence does not give",
    "schedule": "add or change a planned future event or its date so the sentence announces a schedule it does not have",
}

PROMPT = """You write test pairs for a faithfulness checker of Indonesian news. Premise (a sentence from a real article):

{premise}

Error type: {error_type}. Write Indonesian hypotheses, each ONE sentence of similar length to the premise:
- "corrupted" (exactly 2, different from each other): change ONE thing only: {edit}. Keep every other word.
- "restatement" (exactly 1): the same meaning in other words; do not add or drop any fact, hedge or denial.
- "hard_positive" (exactly 1): a sentence the premise fully supports that KEEPS the cue words of the {error_type} type
  (e.g. the same cause word, hedge, denial, date or plan wording), shortened or reordered, adding nothing new.
Never copy the premise verbatim. Reply as JSON only:
{{"corrupted": ["...", "..."], "restatement": "...", "hard_positive": "..."}}"""


def cue_check(error_type: str) -> Callable[[str], bool]:
    """The gate regex of `error_type`; imported lazily so --help and tests need no pipeline import."""
    from newscrawler.core import causal_check, source_check
    return {
        "cause": lambda s: bool(causal_check._causal_matches(s)),
        "hedge": lambda s: bool(causal_check._HEDGE.search(s)),
        "denial": lambda s: bool(causal_check._DENIAL.search(s)) and bool(DENIAL_ACT.search(s)),
        "end": lambda s: bool(source_check.end_points(s)),
        "schedule": lambda s: bool(source_check.future_phrases(s)),
    }[error_type]


def usable(sentence: str) -> bool:
    n = len(sentence.split())
    return MIN_WORDS <= n <= MAX_WORDS and not re.search(r"https?://|\n", sentence)


def pick_seeds(texts: Iterable[tuple], per_type: int, rng: random.Random) -> Dict[str, List[dict]]:
    """(article_id, text) -> up to `per_type` distinct seed sentences per error type, at most one per article."""
    from newscrawler.core.causal_check import sentences
    checks = {t: cue_check(t) for t in ERROR_TYPES}
    pools: Dict[str, List[dict]] = {t: [] for t in ERROR_TYPES}
    for art_id, text in texts:
        for s in (x.strip() for x in sentences(text)):
            if not usable(s):
                continue
            for t in ERROR_TYPES:
                if checks[t](s):
                    pools[t].append({"seed_id": f"{t}-{art_id}-{hashlib.md5(s.encode('utf-8')).hexdigest()[:6]}", "premise": s})
    out = {}
    for t, pool in pools.items():
        rng.shuffle(pool)
        seen, chosen = set(), []
        for seed in pool:
            art = seed["seed_id"].split("-")[1]
            if art not in seen:
                seen.add(art)
                chosen.append(seed)
            if len(chosen) >= per_type:
                break
        out[t] = chosen
    return out


def parse_reply(text: Optional[str]) -> Optional[dict]:
    """The JSON object with 2 corrupted, a restatement and a hard_positive, or None."""
    try:
        data = json.loads(text or "")
        corrupted = [c.strip() for c in data["corrupted"] if isinstance(c, str) and c.strip()]
        rest, hard = data["restatement"].strip(), data["hard_positive"].strip()
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if len(corrupted) != 2 or not rest or not hard:
        return None
    return {"corrupted": corrupted, "restatement": rest, "hard_positive": hard}


def to_pairs(seed: dict, error_type: str, reply: dict) -> List[dict]:
    premise = seed["premise"]
    items = ([(c, "unfaithful", "corrupted") for c in reply["corrupted"]]
             + [(reply["restatement"], "faithful", "restatement"), (reply["hard_positive"], "faithful", "hard_positive")])
    pairs = []
    for i, (hyp, label, kind) in enumerate(items):
        if hyp.strip().lower() == premise.strip().lower():
            continue                     # a verbatim copy tests nothing
        pairs.append({"id": f"{seed['seed_id']}-{i}", "seed_id": seed["seed_id"], "error_type": error_type,
                      "premise": premise, "hypothesis": hyp, "label": label, "kind": kind, "verified": None})
    return pairs


class Budget:
    """Dollars spent against a hard cap; `can_start` is False when one more worst-case call could pass it."""

    def __init__(self, max_usd: float, price: Callable[[int, int], float]):
        self.max_usd, self.spent, self.price = max_usd, 0.0, price

    def can_start(self, in_flight: int = 0) -> bool:
        """`in_flight` calls already started are charged at worst case too, so concurrent calls stay inside the cap."""
        return self.spent + (in_flight + 1) * self.price(WORST_CALL_INPUT, WORST_CALL_OUTPUT) <= self.max_usd

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.spent += self.price(input_tokens, output_tokens)


def article_ids(pairs_path: str) -> set:
    """Article ids (seed_id's second field) of every pair in a JSONL: the articles a new run must not seed from."""
    with open(pairs_path, encoding="utf-8") as f:
        return {json.loads(l)["seed_id"].split("-")[1] for l in f if l.strip()}


MAX_ERRORS_IN_A_ROW = 10


def generate(seeds: Dict[str, List[dict]], provider, budget: Budget, out_path: str,
             log: Callable[[str], None] = print, workers: int = 1) -> Dict[str, int]:
    """Calls run on `workers` threads; budget checks, counting and writing stay on this thread. A failed call is
    counted and its seed left for a resumed run; MAX_ERRORS_IN_A_ROW failures in a row stop the run."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    done = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            done = {json.loads(l)["seed_id"] for l in f if l.strip()}
    todo = iter([(t, s) for t, group in seeds.items() for s in group if s["seed_id"] not in done])
    stats = {"seeds": 0, "pairs": 0, "bad_reply": 0, "errors": 0, "stopped_on_budget": 0, "stopped_on_errors": 0}
    errors_in_a_row, stopping = 0, False
    with open(out_path, "a", encoding="utf-8", newline="\n") as f, ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}
        while True:
            while not stopping and len(pending) < workers:
                if not budget.can_start(len(pending)):
                    if pending:
                        break                   # wait: finished calls may cost less than their reservation
                    stats["stopped_on_budget"] = 1
                    log(f"budget: ${budget.spent:.4f} spent of ${budget.max_usd:.2f}; stopping before the next call")
                    stopping = True
                    break
                item = next(todo, None)
                if item is None:
                    stopping = True
                    break
                error_type, seed = item
                prompt = PROMPT.format(premise=seed["premise"], error_type=error_type, edit=EDITS[error_type])
                pending[pool.submit(provider.complete, prompt)] = item
            if not pending:
                return stats
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                error_type, seed = pending.pop(fut)
                try:
                    completion = fut.result()
                except Exception as e:  # noqa: BLE001 -- the seed stays unwritten; a resumed run retries it
                    stats["errors"] += 1
                    errors_in_a_row += 1
                    log(f"call failed for {seed['seed_id']}: {e!r}")
                    if errors_in_a_row >= MAX_ERRORS_IN_A_ROW and not stopping:
                        stats["stopped_on_errors"] = 1
                        log(f"{errors_in_a_row} failed calls in a row; stopping")
                        stopping = True
                    continue
                errors_in_a_row = 0
                budget.add(completion.input_tokens, completion.output_tokens)
                reply = parse_reply(completion.text)
                stats["seeds"] += 1
                if reply is None:
                    stats["bad_reply"] += 1
                    continue
                for pair in to_pairs(seed, error_type, reply):
                    f.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    stats["pairs"] += 1
                f.flush()
                if stats["seeds"] % 100 == 0:
                    log(f"{stats['seeds']} seeds, {stats['pairs']} pairs, ${budget.spent:.4f}")


def load_article_texts(days: int, limit: int) -> List[tuple]:
    from sqlalchemy import text
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    with SQLAlchemyClient().get_session() as session:
        rows = session.execute(text(
            "SELECT a.sitemap_id, a.extracted_text FROM articles a JOIN sitemaps s ON s.sitemap_id = a.sitemap_id "
            "WHERE s.posted_at >= :since AND a.extracted_text IS NOT NULL ORDER BY random() LIMIT :n"),
            {"since": int((datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%d")), "n": limit}).fetchall()
    return [(r[0], r[1]) for r in rows]


def main(argv=None) -> int:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO, ".env"))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-type", type=int, default=90, help="seeds per error type (4 pairs each)")
    ap.add_argument("--max-usd", type=float, default=3.0)
    ap.add_argument("--days", type=int, default=100, help="articles posted within this many days")
    ap.add_argument("--articles", type=int, default=6000, help="articles sampled for seeds")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="pick seeds, print counts and the cost ceiling, no calls")
    ap.add_argument("--exclude-pairs", action="append", default=[],
                    help="JSONL of pairs whose articles must not be seeded from (e.g. the eval set); repeatable")
    ap.add_argument("--workers", type=int, default=1, help="concurrent model calls")
    args = ap.parse_args(argv)

    from newscrawler.core.extraction_provider import build_provider
    from newscrawler.core.peak_hours import cost_usd, is_peak
    rng = random.Random(args.seed)
    texts = load_article_texts(args.days, args.articles)
    excluded = set().union(*(article_ids(p) for p in args.exclude_pairs)) if args.exclude_pairs else set()
    texts = [(a, t) for a, t in texts if str(a) not in excluded]
    print(f"{len(texts)} articles after excluding {len(excluded)} already seeded")
    seeds = pick_seeds(texts, args.per_type, rng)
    print({t: len(v) for t, v in seeds.items()})
    peak = is_peak()
    price = lambda i, o: cost_usd(i, o, peak)  # noqa: E731
    print(f"{'peak' if peak else 'off-peak'} prices; worst case per call ${price(WORST_CALL_INPUT, WORST_CALL_OUTPUT):.5f}; "
          f"cap ${args.max_usd:.2f}")
    if args.dry_run:
        return 0
    provider = build_provider("openai")
    if provider is None:
        print("no OPENAI_API_KEY", file=sys.stderr)
        return 2
    budget = Budget(args.max_usd, price)
    stats = generate(seeds, provider, budget, args.out, workers=args.workers)
    print(stats, f"spent ${budget.spent:.4f} of ${args.max_usd:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
