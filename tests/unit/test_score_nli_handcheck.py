"""SYS-197 (#427, ADR-025): the blind sheet hides Claude's labels, the owner's label wins, and the gates are applied."""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "score_nli_handcheck",
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "experiments", "score_nli_handcheck.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

SAMPLE = [{"id": f"{t}-{i}", "error_type": t, "premise": "p", "hypothesis": "h", "intended": "supported"}
          for t in ("cause", "end") for i in range(10)]


def claude(valid_by_id):
    return [{"id": r["id"], "error_type": r["error_type"], "valid": valid_by_id.get(r["id"], "y"),
             "code": "label" if valid_by_id.get(r["id"]) == "n" else ""} for r in SAMPLE]


def owner(labels):
    return [{"id": i, sc.VALID_COL: v} for i, v in labels.items()]


def test_blind_sheet_takes_n_per_type_and_carries_no_label():
    rows = sc.build_blind(SAMPLE, per_type=3, seed=1)
    assert sorted(r["error_type"] for r in rows) == ["cause"] * 3 + ["end"] * 3
    assert all(r[sc.VALID_COL] == "" and "valid" not in r and "code" not in r for r in rows)
    assert rows == sc.build_blind(SAMPLE, per_type=3, seed=1)          # seeded: the same sheet every time


def test_agreement_counts_only_rows_both_labelled():
    res = sc.score(claude({"cause-0": "n"}), owner({"cause-0": "n", "cause-1": "n", "end-0": "y"}))
    assert (res["agree"], res["compared"]) == (2, 3)
    assert res["disagreements"] == [("cause-1", "y", "n")]


def test_owner_label_wins_in_the_family_share():
    res = sc.score(claude({"cause-0": "n"}), owner({"cause-0": "y", "cause-1": "n"}))
    assert res["families"]["cause"]["valid"] == 9                          # cause-0 back to y, cause-1 now n
    assert res["families"]["cause"]["codes"] == {"owner": 1}


def test_unlabelled_owner_rows_are_reported():
    res = sc.score(claude({}), owner({"cause-0": "", "end-0": "y"}))
    assert res["unlabelled"] == ["cause-0"]
    assert res["compared"] == 1                                            # a blank row is not a disagreement


def test_family_verdicts_at_the_gates():
    assert sc.verdict(0.80) == "drop"
    assert sc.verdict(0.81) == "borderline"
    assert sc.verdict(0.85) == "borderline"
    assert sc.verdict(0.875) == "keep"


def test_score_exit_codes(tmp_path):
    def write(path, rows):
        import csv
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    c, o = tmp_path / "c.csv", tmp_path / "o.csv"
    write(c, claude({"cause-0": "n"}))
    write(o, owner({f"cause-{i}": "y" for i in range(1, 10)} | {"cause-0": "n"}))
    assert sc.main(["score", "--claude", str(c), "--owner", str(o)]) == 0      # 10/10 agree
    write(o, owner({f"cause-{i}": "n" for i in range(10)}))
    assert sc.main(["score", "--claude", str(c), "--owner", str(o)]) == 1      # 1/10 agree: the owner labels the rest
    write(o, owner({"cause-0": ""}))
    assert sc.main(["score", "--claude", str(c), "--owner", str(o)]) == 2
