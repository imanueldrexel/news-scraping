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


# SYS-199 arm B (ADR-028): training pairs come from other articles, with concurrent calls inside the same cap.

class Flaky(Stub):
    """Raises for the seeds whose premise mentions FAIL."""

    def complete(self, prompt):
        self.calls += 1
        if "FAIL" in prompt:
            raise RuntimeError("connection reset")
        return Completion(self.text, self.tin, self.tout)


def test_concurrent_calls_stay_inside_the_cap(tmp_path):
    stub = Stub()
    budget = gen.Budget(0.0065, price)
    stats = gen.generate(seeds(10), stub, budget, str(tmp_path / "p.jsonl"), log=lambda m: None, workers=4)
    assert stub.calls == 3 and stats["stopped_on_budget"] == 1
    assert budget.spent <= budget.max_usd


def test_concurrent_run_writes_every_seed_once(tmp_path):
    out = tmp_path / "p.jsonl"
    stats = gen.generate(seeds(12), Stub(), gen.Budget(3.0, price), str(out), log=lambda m: None, workers=5)
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert stats["seeds"] == 12 and len({r["seed_id"] for r in rows}) == 12 and len(rows) == 48


def test_a_failed_call_leaves_its_seed_for_the_resumed_run(tmp_path):
    out = tmp_path / "p.jsonl"
    group = seeds(3)
    group["cause"][1]["premise"] = "FAIL naik karena pasokan seret."
    stats = gen.generate(group, Flaky(), gen.Budget(3.0, price), str(out), log=lambda m: None, workers=2)
    assert stats["errors"] == 1 and stats["seeds"] == 2 and stats["stopped_on_errors"] == 0
    group["cause"][1]["premise"] = "B naik karena pasokan seret."
    stub = Stub()
    gen.generate(group, stub, gen.Budget(3.0, price), str(out), log=lambda m: None)
    assert stub.calls == 1


def test_failures_in_a_row_stop_the_run(tmp_path):
    group = {"cause": [{"seed_id": f"cause-{i}-x", "premise": "FAIL"} for i in range(30)]}
    stub = Flaky()
    stats = gen.generate(group, stub, gen.Budget(3.0, price), str(tmp_path / "p.jsonl"), log=lambda m: None)
    assert stats["stopped_on_errors"] == 1 and stub.calls == gen.MAX_ERRORS_IN_A_ROW


def test_output_is_lf(tmp_path):
    out = tmp_path / "p.jsonl"
    gen.generate(seeds(1), Stub(), gen.Budget(3.0, price), str(out), log=lambda m: None)
    assert b"\r\n" not in out.read_bytes()


def test_article_ids_are_the_seed_ids_second_field(tmp_path):
    src = tmp_path / "eval.jsonl"
    src.write_text("\n".join(json.dumps({"seed_id": s}) for s in ["cause-101-ab", "hedge-202-cd", "end-101-ef"]) + "\n",
                   encoding="utf-8")
    assert gen.article_ids(str(src)) == {"101", "202"}


def test_a_success_resets_the_failure_count(tmp_path):
    n = gen.MAX_ERRORS_IN_A_ROW - 1
    premises = ["FAIL"] * n + ["A naik karena pasokan seret."] + ["FAIL"] * n
    group = {"cause": [{"seed_id": f"cause-{i}-x", "premise": p} for i, p in enumerate(premises)]}
    stats = gen.generate(group, Flaky(), gen.Budget(3.0, price), str(tmp_path / "p.jsonl"), log=lambda m: None)
    assert stats["stopped_on_errors"] == 0 and stats["errors"] == 2 * n and stats["seeds"] == 1


# ADR-029: faithful near-copies for seeds that already exist.

NEAR = json.dumps({"near_copy": ["A naik sebab pasokan seret.", "A meningkat karena pasokan seret."]})


def test_near_copy_mode_writes_n_faithful_near_copies_per_seed(tmp_path):
    out = tmp_path / "n.jsonl"
    stats = gen.generate(seeds(2), Stub(text=NEAR), gen.Budget(3.0, price), str(out), log=lambda m: None, near=2)
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert stats["pairs"] == 4 and {r["kind"] for r in rows} == {"near_copy"} and {r["label"] for r in rows} == {"faithful"}
    assert sorted(r["id"] for r in rows) == ["cause-0-abc-n0", "cause-0-abc-n1", "cause-1-abc-n0", "cause-1-abc-n1"]


def test_near_copy_prompt_is_used_in_near_mode():
    class Spy(Stub):
        def complete(self, prompt):
            self.prompt = prompt
            return super().complete(prompt)
    spy = Spy(text=NEAR)
    gen.generate(seeds(1), spy, gen.Budget(3.0, price), os.devnull, log=lambda m: None, near=1)
    assert "near copies" in spy.prompt and "corrupted" not in spy.prompt


def test_parse_near_needs_n_distinct_copies():
    assert gen.parse_near(NEAR, 2) == ["A naik sebab pasokan seret.", "A meningkat karena pasokan seret."]
    assert gen.parse_near(NEAR, 1) == ["A naik sebab pasokan seret."]
    assert gen.parse_near(json.dumps({"near_copy": ["x", "x"]}), 2) is None
    assert gen.parse_near("oops", 1) is None and gen.parse_near(json.dumps({"other": []}), 1) is None


def test_a_verbatim_near_copy_is_dropped():
    seed = {"seed_id": "s", "premise": "A naik."}
    assert [p["hypothesis"] for p in gen.near_pairs(seed, "cause", ["a naik.", "A meningkat."])] == ["A meningkat."]


def test_seeds_from_keeps_one_entry_per_seed_by_its_type(tmp_path):
    rows = [{"seed_id": "cause-1-a", "error_type": "cause", "premise": "P1"},
            {"seed_id": "cause-1-a", "error_type": "cause", "premise": "P1"},
            {"seed_id": "denial-2-b", "error_type": "other", "premise": "P2"}]
    src = tmp_path / "p.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert gen.seeds_from(str(src)) == {"cause": [{"seed_id": "cause-1-a", "premise": "P1"}],
                                        "other": [{"seed_id": "denial-2-b", "premise": "P2"}]}
