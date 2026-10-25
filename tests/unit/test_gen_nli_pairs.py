"""SYS-197 (#427): the pair generator stops inside its dollar cap, resumes, and keeps only well-formed replies."""
import importlib.util
import json
import os

from newscrawler.core.extraction_provider import Completion

_spec = importlib.util.spec_from_file_location(
    "gen_nli_pairs", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "experiments", "gen_nli_pairs.py"))
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

GOOD = json.dumps({"corrupted": ["A karena X.", "A karena Y."], "restatement": "A sebab pasokan.",
                   "hard_positive": "A karena pasokan."})


class Stub:
    def __init__(self, text=GOOD, tin=1000, tout=500):
        self.calls, self.text, self.tin, self.tout = 0, text, tin, tout

    def complete(self, prompt):
        self.calls += 1
        return Completion(self.text, self.tin, self.tout)


def seeds(n):
    return {"cause": [{"seed_id": f"cause-{i}-abc", "premise": "A naik karena pasokan seret."} for i in range(n)]}


def price(i, o):            # $1 per million tokens either way
    return (i + o) / 1_000_000


def test_parse_reply_needs_two_corrupted_a_restatement_and_a_hard_positive():
    assert gen.parse_reply(GOOD)["restatement"] == "A sebab pasokan."
    assert gen.parse_reply(json.dumps({"corrupted": ["x"], "restatement": "r", "hard_positive": "h"})) is None
    assert gen.parse_reply("not json") is None
    assert gen.parse_reply(None) is None


def test_four_pairs_per_seed_two_unfaithful_two_faithful(tmp_path):
    out = tmp_path / "p.jsonl"
    stats = gen.generate(seeds(1), Stub(), gen.Budget(3.0, price), str(out), log=lambda m: None)
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert stats["pairs"] == 4
    assert sorted(r["kind"] for r in rows) == ["corrupted", "corrupted", "hard_positive", "restatement"]
    assert [r["label"] for r in rows].count("unfaithful") == 2


def test_stops_before_a_call_that_could_pass_the_cap(tmp_path):
    # worst case per call = (1500 + 1500) / 1e6 = $0.003; a $0.0065 cap allows 3 calls at $0.0015 each (the 4th could reach $0.0075)
    out = tmp_path / "p.jsonl"
    stub = Stub()
    budget = gen.Budget(0.0065, price)
    stats = gen.generate(seeds(10), stub, budget, str(out), log=lambda m: None)
    assert stub.calls == 3 and stats["stopped_on_budget"] == 1
    assert budget.spent <= budget.max_usd


def test_resume_skips_seeds_already_written(tmp_path):
    out = tmp_path / "p.jsonl"
    gen.generate(seeds(2), Stub(), gen.Budget(3.0, price), str(out), log=lambda m: None)
    stub = Stub()
    gen.generate(seeds(3), stub, gen.Budget(3.0, price), str(out), log=lambda m: None)
    assert stub.calls == 1


def test_a_bad_reply_is_counted_and_still_charged(tmp_path):
    budget = gen.Budget(3.0, price)
    stats = gen.generate(seeds(1), Stub(text="oops"), budget, str(tmp_path / "p.jsonl"), log=lambda m: None)
    assert stats["bad_reply"] == 1 and stats["pairs"] == 0 and budget.spent > 0


def test_a_verbatim_copy_of_the_premise_is_dropped():
    seed = {"seed_id": "s", "premise": "A naik."}
    pairs = gen.to_pairs(seed, "cause", {"corrupted": ["A naik.", "B naik."], "restatement": "r", "hard_positive": "h"})
    assert len(pairs) == 3
