"""SYS-197 (#427, ADR-025/026/027): the blind sheet hides Claude's labels; validity is label_ok (gated on agreement,
the owner rules on disagreements) and type_ok (Claude's; a misfit is bucketed, not dropped)."""
import csv
import importlib.util
import os

import pytest

_spec = importlib.util.spec_from_file_location(
    "score_nli_handcheck",
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "experiments", "score_nli_handcheck.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

SAMPLE = [{"id": f"{t}-{i}", "error_type": t, "premise": "p", "hypothesis": "h", "intended": "supported"}
          for t in ("cause", "end") for i in range(10)]


def claude(labels):
    """labels: {id: (valid, code)}; every other row y."""
    return [{"id": r["id"], "error_type": r["error_type"], "kind": "corrupted", "intended": r["intended"],
             "valid": labels.get(r["id"], ("y", ""))[0], "code": labels.get(r["id"], ("y", ""))[1]} for r in SAMPLE]


def second(labels):
    return [{"id": i, sc.VALID_COL: v, "code": c} for i, (v, c) in labels.items()]


def rulings(labels):
    return [{"id": i, "label_ok": v} for i, v in labels.items()]


def final_of(res, row_id):
    return next(f for f in res["final"] if f["id"] == row_id)


def test_blind_sheet_takes_n_per_type_and_carries_no_label():
    rows = sc.build_blind(SAMPLE, per_type=3, seed=1)
    assert sorted(r["error_type"] for r in rows) == ["cause"] * 3 + ["end"] * 3
    assert all(r[sc.VALID_COL] == "" and "valid" not in r and "code" not in r for r in rows)
    assert rows == sc.build_blind(SAMPLE, per_type=3, seed=1)          # seeded: the same sheet every time


@pytest.mark.parametrize("valid,code,expected", [
    ("y", "", ("y", "y")), ("n", "cue", ("y", "n")), ("n", "type", ("y", "n")), ("n", "multi", ("y", "n")),
    ("n", "label", ("n", "")), ("n", "garbled", ("n", "")), ("", "", ("", "")),
])
def test_old_codes_map_to_the_two_checks(valid, code, expected):
    assert sc.checks(valid, code) == expected


def test_a_type_dispute_is_no_label_disagreement():
    # Claude: wrong type (label right); Gemini: y. They agree that the label is right.
    res = sc.score(claude({"cause-0": ("n", "cue")}), second({"cause-0": ("y", "")}), [])
    assert (res["agree"], res["compared"], res["disagreements"]) == (1, 1, [])
    assert final_of(res, "cause-0")["type_ok"] == "n"                   # Claude's type judgement stands
    assert final_of(res, "cause-0")["label_ok"] == "y"                  # bucketed, not dropped


def test_the_owner_ruling_decides_a_label_disagreement():
    res = sc.score(claude({"cause-0": ("n", "label"), "cause-1": ("n", "label")}),
                   second({"cause-0": ("y", ""), "cause-1": ("y", "")}), rulings({"cause-0": "y"}))
    assert res["disagreements"] == [("cause-0", "n", "y", "y"), ("cause-1", "n", "y", "")]
    assert (final_of(res, "cause-0")["label_ok"], final_of(res, "cause-0")["decided_by"]) == ("y", "owner")
    assert (final_of(res, "cause-1")["label_ok"], final_of(res, "cause-1")["decided_by"]) == ("", "unresolved")
    assert res["families"]["cause"]["total"] == 9                       # the unresolved row is left out


def test_rows_the_second_labeller_did_not_see_keep_claude():
    res = sc.score(claude({"end-3": ("n", "label")}), second({"cause-0": ("y", "")}), [])
    assert (final_of(res, "end-3")["label_ok"], final_of(res, "end-3")["decided_by"]) == ("n", "claude")
    assert res["families"]["end"]["label_ok"] == 9


def test_unlabelled_second_rows_are_reported_and_not_compared():
    res = sc.score(claude({}), second({"cause-0": ("", ""), "end-0": ("y", "")}), [])
    assert res["unlabelled"] == ["cause-0"]
    assert res["compared"] == 1


def test_family_verdicts_at_the_gates():
    assert sc.verdict(0.80) == "drop"
    assert sc.verdict(0.81) == "borderline"
    assert sc.verdict(0.85) == "borderline"
    assert sc.verdict(0.875) == "keep"


def write(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_score_exit_codes_and_final_file(tmp_path):
    c, s, r, out = (tmp_path / n for n in ("c.csv", "s.csv", "r.csv", "final.csv"))
    write(c, claude({"cause-0": ("n", "label")}))
    write(s, second({f"cause-{i}": ("y", "") for i in range(10)}))                # 9/10 agree
    write(r, rulings({"cause-0": "n"}))
    argv = ["score", "--claude", str(c), "--second", str(s), "--rulings", str(r)]
    assert sc.main(argv + ["--final", str(out)]) == 0
    assert {row["id"]: row["label_ok"] for row in sc.read(str(out))}["cause-0"] == "n"
    write(r, [{"id": "end-0", "label_ok": "y"}])                                 # cause-0 no longer ruled
    assert sc.main(argv) == 3
    write(s, second({f"cause-{i}": ("n", "label") for i in range(10)}))          # 1/10 agree
    assert sc.main(argv) == 1
    write(s, second({"cause-0": ("", "")}))
    assert sc.main(argv) == 2
