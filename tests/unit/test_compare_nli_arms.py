"""SYS-199 (#429): the arm comparison's wrong-premise control and held-out protocol (no model)."""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "compare_nli_arms", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "experiments", "compare_nli_arms.py"))
cmp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmp)


def pairs_for(error_type, n_seeds):
    out = []
    for s in range(n_seeds):
        for i, (label, kind) in enumerate([("unfaithful", "corrupted"), ("unfaithful", "corrupted"),
                                           ("faithful", "restatement"), ("faithful", "hard_positive")]):
            out.append({"id": f"{error_type}-{s}-{i}", "seed_id": f"{error_type}-{s}", "error_type": error_type,
                        "premise": f"premise {error_type} {s}", "hypothesis": f"h {s} {i}", "label": label,
                        "kind": kind})
    return out


def test_wrong_premise_never_keeps_its_own_and_stays_in_type():
    pairs = pairs_for("hedge", 5) + pairs_for("end", 3)
    wrong = cmp.wrong_premise(pairs)
    assert len(wrong) == len(pairs) and all(w["id"].endswith("~wrong") for w in wrong)
    for p, w in zip(pairs, wrong):
        assert w["premise"] != p["premise"] and w["premise"].startswith(f"premise {p['error_type']} ")
        assert w["hypothesis"] == p["hypothesis"] and w["label"] == p["label"]
    # every pair of a seed gets the same other premise
    by_seed = {}
    for p, w in zip(pairs, wrong):
        by_seed.setdefault(p["seed_id"], set()).add(w["premise"])
    assert all(len(v) == 1 for v in by_seed.values())


def test_auc():
    assert cmp.auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert cmp.auc([0.1], [0.9]) == 0.0
    assert cmp.auc([0.5, 0.5], [0.5]) == 0.5


def test_held_out_measures_on_the_half_tau_was_not_chosen_on():
    pairs = pairs_for("cause", 20)
    # unfaithful pairs score 0.1 on even seeds and 0.6 on odd ones; faithful pairs score 0.95
    scores = {p["id"]: (0.95 if p["label"] == "faithful" else (0.1 if int(p["seed_id"].split("-")[1]) % 2 == 0 else 0.6))
              for p in pairs}
    row = cmp.held_out(pairs, scores, recall=0.9, splits=5)
    assert row["ff_restated"] == 0.0 and row["ff_hard"] == 0.0
    assert row["recall"] == 1.0 and 0.6 < row["tau_min"] <= row["tau_max"] < 0.95


def test_report_separates_true_and_wrong_premise_auc():
    pairs = pairs_for("hedge", 6)
    scores = {p["id"]: (0.9 if p["label"] == "faithful" else 0.1) for p in pairs}
    scores.update({w["id"]: 0.5 for w in cmp.wrong_premise(pairs)})
    row = cmp.report(pairs, scores)["hedge"]
    assert row["auc"] == 1.0 and row["auc_wrong_premise"] == 0.5
