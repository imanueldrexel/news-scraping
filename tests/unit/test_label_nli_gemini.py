"""SYS-197 (#427, ADR-026): Gemini's blind labels: the prompt hides Claude's labels, a 429 stops and resumes,
and a reply that misses or invents a row id is refused."""
import importlib.util
import json
import os

import pytest

from newscrawler.core.extraction_provider import Completion, ProviderQuotaExhausted

_spec = importlib.util.spec_from_file_location(
    "label_nli_gemini",
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "experiments", "label_nli_gemini.py"))
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

ROWS = [{"id": f"r{i}", "error_type": "hedge", "premise": "Ia diduga mencuri.", "hypothesis": "Ia mencuri.",
         "intended": "unsupported", lg.VALID_COL: "", "note": ""} for i in range(5)]


class Stub:
    name = "gemini-test"

    def __init__(self, fail_on_call=None):
        self.calls, self.prompts, self.fail_on_call = 0, [], fail_on_call

    def complete(self, prompt):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise ProviderQuotaExhausted("429", quota="per-day")
        self.prompts.append(prompt)
        ids = [r["id"] for r in json.loads(prompt.split("Rows (JSON):\n", 1)[1].split("\n\nReply as", 1)[0])]
        return Completion(json.dumps({"labels": [{"id": i, "valid": "n" if i == "r0" else "y",
                                                  "code": "label" if i == "r0" else "", "reason": "x"}
                                                 for i in ids]}), 100, 50)


def test_labels_every_row_in_batches_and_writes_them(tmp_path):
    out = tmp_path / "g.csv"
    stats = lg.label(ROWS, [], Stub(), batch_size=2, out_path=str(out))
    assert (stats["calls"], stats["labelled"], stats["stopped"]) == (3, 5, None)
    rows = lg.read(str(out))
    assert [r["id"] for r in rows] == [r["id"] for r in ROWS]
    assert (rows[0][lg.VALID_COL], rows[0]["code"]) == ("n", "label")
    assert rows[1][lg.VALID_COL] == "y" and rows[1]["code"] == ""


def test_prompt_carries_no_label_of_claude():
    prompt = lg.build_prompt([{**ROWS[0], "valid": "n", "code": "cue", "note": "Claude's reason"}])
    assert "Claude's reason" not in prompt and '"code": "cue"' not in prompt


def test_a_quota_error_stops_and_a_rerun_resumes(tmp_path):
    out = tmp_path / "g.csv"
    stats = lg.label(ROWS, [], Stub(fail_on_call=2), batch_size=2, out_path=str(out))
    assert (stats["labelled"], stats["stopped"] is not None) == (2, True)
    stub = Stub()
    stats = lg.label(ROWS, lg.read(str(out)), stub, batch_size=2, out_path=str(out))
    assert (stub.calls, stats["labelled"]) == (2, 3)                       # only the 3 missing rows
    assert len(lg.read(str(out))) == 5


@pytest.mark.parametrize("labels", [
    [{"id": "r0", "valid": "y"}],                                          # r1 missing
    [{"id": "r0", "valid": "y"}, {"id": "r1", "valid": "y"}, {"id": "zz", "valid": "y"}],
    [{"id": "r0", "valid": "maybe"}, {"id": "r1", "valid": "y"}],
    [{"id": "r0", "valid": "n", "code": "vibes"}, {"id": "r1", "valid": "y"}],
])
def test_a_reply_that_does_not_match_the_batch_is_refused(labels):
    with pytest.raises(ValueError):
        lg.parse(json.dumps({"labels": labels}), ROWS[:2])
