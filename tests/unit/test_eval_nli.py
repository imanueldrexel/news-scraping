"""SYS-197 (#427): the NLI eval harness on a 10-pair golden fixture with fixed scores (no model)."""
import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("eval_nli", os.path.join(ROOT, "scripts", "experiments", "eval_nli.py"))
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

GOLDEN = os.path.join(ROOT, "tests", "fixtures", "nli_eval", "golden.jsonl")
# p_entail per pair: the corrupted cause pairs score .1 .2 .3 .6; restatements .9 .8; hard positives .7 .95
SCORES = {"c0": .1, "c1": .2, "c2": .3, "c3": .6, "c4": .9, "c5": .8, "c6": .7, "c7": .95,
          "h0": .05, "h1": .1, "h2": .9, "h3": .85}


def test_the_fixture_loads_and_labels_are_checked(tmp_path):
    assert len(ev.load_pairs(GOLDEN)) == 12
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"id": "x", "label": "maybe"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ev.load_pairs(str(bad))


def test_tau_is_the_lowest_threshold_that_reaches_the_recall():
    assert ev.choose_tau([.1, .2, .3, .6], 0.75) == pytest.approx(.3, abs=1e-9)
    assert ev.choose_tau([.1, .2, .3, .6], 0.9) == pytest.approx(.6, abs=1e-9)
    assert ev.choose_tau([], 0.9) is None


def test_tau_flags_strictly_below_it():
    tau = ev.choose_tau([.1, .2, .3, .6], 0.75)
    assert ev.rate([.1, .2, .3, .6], tau) == 0.75 and ev.rate([.3], tau) == 0.0 + 1.0 * (.3 < tau)


def test_report_numbers():
    report = ev.evaluate(ev.load_pairs(GOLDEN), SCORES, recall=0.75)
    cause, hedge = report["cause"], report["hedge"]
    assert cause["n_unfaithful"] == 4 and (cause["n_restatement"], cause["n_hard_positive"]) == (2, 2)
    assert cause["recall"] == 0.75
    assert cause["false_flag_restatement"] == 0.0 and cause["false_flag_hard_positive"] == 0.0
    assert hedge["recall"] == 1.0 and hedge["tau"] > .1


def test_a_threshold_that_flags_faithful_pairs_shows_in_the_false_flag_rate():
    scores = {**SCORES, "c6": .25}              # a hard positive scored below tau(.3)
    cause = ev.evaluate(ev.load_pairs(GOLDEN), scores, recall=0.75)["cause"]
    assert cause["false_flag_hard_positive"] == 0.5


def test_hypothesis_only_catches_a_leaky_edit():
    leaky = [{"id": str(i), "error_type": "t", "premise": "p", "label": "unfaithful" if i % 2 else "faithful",
              "kind": "corrupted" if i % 2 else "restatement",
              "hypothesis": f"{'akibat' if i % 2 else 'sebab'} peristiwa nomor {i}"} for i in range(40)]
    assert ev.hypothesis_only_accuracy(leaky) > 0.9


def test_hypothesis_only_is_none_when_a_class_is_too_small():
    one = [{"id": "a", "label": "unfaithful", "hypothesis": "x"}, {"id": "b", "label": "faithful", "hypothesis": "y"}]
    assert ev.hypothesis_only_accuracy(one) is None


def test_main_prints_a_table_from_scores(tmp_path, capsys):
    scores = tmp_path / "s.json"
    scores.write_text(json.dumps(SCORES), encoding="utf-8")
    assert ev.main(["--pairs", GOLDEN, "--scores", str(scores), "--recall", "0.75"]) == 0
    out = capsys.readouterr().out
    assert "| cause | 4 | 2 / 2 |" in out and "| hedge | 2 | 1 / 1 |" in out
