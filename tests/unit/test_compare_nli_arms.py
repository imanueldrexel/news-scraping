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
    scores.update({i["id"]: (0.05 if i["seed_id"] == "hedge-0" else 0.99) for i in cmp.identity(pairs)})
    row = cmp.report(pairs, scores)["hedge"]
    assert row["auc"] == 1.0 and row["auc_wrong_premise"] == 0.5
    assert abs(row["ff_identity_05"] - 1 / 6) < 1e-9


def test_identity_is_one_faithful_copy_per_seed():
    pairs = pairs_for("hedge", 3)
    got = cmp.identity(pairs)
    assert [g["id"] for g in got] == ["hedge-0~id", "hedge-1~id", "hedge-2~id"]
    assert all(g["hypothesis"] == g["premise"] and g["label"] == "faithful" for g in got)


def test_near_copy_column_counts_flags_at_the_types_tau():
    pairs = pairs_for("hedge", 6)
    scores = {p["id"]: (0.9 if p["label"] == "faithful" else 0.1) for p in pairs}
    scores.update({w["id"]: 0.5 for w in cmp.wrong_premise(pairs)})
    scores.update({i["id"]: 0.99 for i in cmp.identity(pairs)})
    near = [{"id": f"n{i}", "error_type": "hedge"} for i in range(4)] + [{"id": "x", "error_type": "end"}]
    scores.update({"n0": 0.05, "n1": 0.95, "n2": 0.95, "n3": 0.95, "x": 0.0})
    row = cmp.report(pairs, scores, near)["hedge"]
    assert row["ff_near_copy"] == 0.25
    assert cmp.report(pairs, scores)["hedge"]["ff_near_copy"] is None


def test_a_type_whose_wrong_premise_auc_is_over_the_line_is_marked_fail():
    """ADR-030 decision 3 (#431): the targeted numbers of a type stand only when the model needs the premise."""
    pairs = pairs_for("hedge", 6)
    scores = {p["id"]: (0.9 if p["label"] == "faithful" else 0.1) for p in pairs}
    scores.update({i["id"]: 0.99 for i in cmp.identity(pairs)})
    leaky = {**scores, **{w["id"]: (0.9 if w["label"] == "faithful" else 0.1) for w in cmp.wrong_premise(pairs)}}
    fair = {**scores, **{w["id"]: 0.5 for w in cmp.wrong_premise(pairs)}}
    assert cmp.report(pairs, leaky)["hedge"]["premise_gate"] == "FAIL"
    assert cmp.report(pairs, fair)["hedge"]["premise_gate"] == "ok"
    assert "| hedge | FAIL |" in cmp.table(cmp.report(pairs, leaky))
