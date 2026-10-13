"""DBT-73 (#345): one ask -> check -> retry once -> fall back loop for the
newsletter's JSON answers (summary, editor, story arcs), and one extractor."""
import ast
import os

import pytest

import newscrawler.core.llm_json as lj
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Script:
    """Answers (or raises) in order, recording each prompt."""

    def __init__(self, *items):
        self.items, self.prompts = list(items), []

    def summarize(self, prompt):
        self.prompts.append(prompt)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _check(answer, attempt):
    data = lj.json_object(answer)
    if data.get("ok") is not True:
        raise lj.Rejected("rules", f"ok harus true (percobaan {attempt})")
    return (data, attempt)


class TestAskJson:
    def test_accepted_on_the_first_try(self):
        out = lj.ask_json(_Script('{"ok": true}'), "P", _check)
        assert out == lj.Outcome(({"ok": True}, 0), [], 1, ['{"ok": true}'])

    def test_a_refusal_is_asked_again_with_its_detail(self):
        s = _Script('{"ok": false}', 'teks lalu {"ok": true} lalu teks')
        out = lj.ask_json(s, "P", _check)
        assert out.value == ({"ok": True}, 1)              # the retry is checked as attempt 1
        assert out.reasons == ["rules"] and out.calls == 2
        assert s.prompts[0] == "P"
        assert s.prompts[1] == "P" + lj.RETRY.format(detail="ok harus true (percobaan 0)")
        assert out.answers == ['{"ok": false}', 'teks lalu {"ok": true} lalu teks']

    def test_two_refusals_are_none_with_both_reasons(self):
        out = lj.ask_json(_Script("bukan json", "[1, 2]"), "P", _check)
        assert (out.value, out.reasons, out.calls) == (None, ["json", "json"], 2)

    def test_retries_is_the_number_of_extra_asks(self):
        s = _Script("x", "y", '{"ok": true}')
        assert lj.ask_json(s, "P", _check, retries=2).value == ({"ok": True}, 2)
        assert lj.ask_json(_Script("x"), "P", _check, retries=0).calls == 1

    @pytest.mark.parametrize("error", [QuotaExhausted("429"), SummarizerError("timeout")])
    def test_raise_mode_passes_provider_errors_with_the_refusals_so_far(self, error):
        with pytest.raises(type(error)) as e:
            lj.ask_json(_Script("x", error), "P", _check, on_error="raise")
        assert e.value.refusals == ["json"]

    def test_retry_mode_asks_again_after_a_failed_call_without_a_detail(self):
        s = _Script(SummarizerError("timeout"), '{"ok": true}')
        out = lj.ask_json(s, "P", _check, on_error="retry")
        assert out.value is not None and out.reasons == ["error"] and s.prompts == ["P", "P"]

    def test_retry_mode_stops_at_a_quota_without_another_call(self):
        s = _Script(QuotaExhausted("429"), '{"ok": true}')
        out = lj.ask_json(s, "P", _check, on_error="retry")
        assert (out.value, out.reasons, out.calls, len(s.prompts)) == (None, ["quota"], 1, 1)

    def test_unknown_policy(self):
        with pytest.raises(ValueError):
            lj.ask_json(_Script(), "P", _check, on_error="ignore")


class TestJsonExtraction:
    @pytest.mark.parametrize("answer,detail", [
        (None, "jawaban bukan JSON"), ("tidak ada", "jawaban bukan JSON"), ("{bukan: json}", "JSON tidak valid"),
    ])
    def test_unusable_answers(self, answer, detail):
        with pytest.raises(lj.Rejected) as e:
            lj.json_object(answer)
        assert (e.value.reason, e.value.detail) == ("json", detail)

    def test_an_object_inside_fences_and_text(self):
        assert lj.json_object('```json\n{"a": [1, {"b": 2}]}\n```') == {"a": [1, {"b": 2}]}

    def test_json_value_also_takes_a_bare_list(self):
        assert lj.json_value("[[0, 3], [1]]") == [[0, 3], [1]]

    def test_json_object_refuses_a_bare_list(self):
        with pytest.raises(lj.Rejected):
            lj.json_object("[1, 2]")


# The newsletter's modules that read model JSON: only llm_json parses it (DBT-73). The knowledge
# extractor is out of scope (its provider returns JSON mode output, ADR-003).
_NEWSLETTER = ["newscrawler/core/story_summary.py", "newscrawler/core/newsletter_edition.py",
               "newscrawler/core/story_grouping.py", "newscrawler/core/story_arc.py"]


@pytest.mark.parametrize("path", _NEWSLETTER)
def test_only_llm_json_parses_model_json(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        pytest.skip(f"{path} does not exist yet")
    tree = ast.parse(open(full, encoding="utf-8").read())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("loads", "load") and getattr(n.func.value, "id", None) == "json"]
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "RETRY"]
    assert not calls, f"{path} calls json.loads: use llm_json.json_object / json_value"
    assert not loops, f"{path} builds its own retry prompt: use llm_json.ask_json"
