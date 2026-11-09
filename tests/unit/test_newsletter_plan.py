"""DBT-75 (#347): the generator's side-effect-free core. `plan()` reads and calls
the LLM but writes nothing; `build_edition()` can run on one plan more than once;
`generate()` alone writes, to the directory it is given; replays read the trace
instead of patching module globals."""
import glob
import os
import re
from datetime import date

import newscrawler.core.newsletter_generator as ng
from tests.unit.newsletter_fakes import FakeNewsroom
from tests.unit.test_newsletter_summaries import _day, _gen

DAY = date(2026, 9, 29)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _planned(monkeypatch, summarizer, arts):
    gen, ds = _gen(monkeypatch, summarizer)
    ds.get_articles_for_date.return_value = arts
    monkeypatch.setattr(gen, "_encode", lambda texts: [[a["_cluster"]] for a in arts])
    return gen, ds


class TestPlan:
    def test_plan_writes_nothing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path))
        gen, ds = _planned(monkeypatch, FakeNewsroom(), _day(3))
        plan = gen.plan(DAY)
        assert len(plan.articles) == 6 and plan.stats.summarized == 3
        ds.save_digest.assert_not_called()
        assert os.listdir(tmp_path) == []

    def test_plan_records_every_summary_call(self, monkeypatch):
        gen, _ = _planned(monkeypatch, FakeNewsroom(story=["bukan json"]), _day(2))
        plan = gen.plan(DAY)
        assert len(plan.calls) == 2
        first = plan.calls[0]
        assert [a["sitemap_id"] for a in first["shown"]] and first["story"] is not None
        assert first["refusals"] == [{"reason": "json", "detail": "jawaban bukan JSON", "answer": "bukan json"}]

    def test_an_empty_day_has_no_plan(self, monkeypatch):
        gen, ds = _planned(monkeypatch, FakeNewsroom(), [])
        assert gen.plan(DAY) is None

    def test_the_edition_can_be_built_twice_on_one_plan(self, monkeypatch):
        gen, _ = _planned(monkeypatch, FakeNewsroom(), _day(8))
        plan = gen.plan(DAY)
        first, second = gen.build_edition(plan), gen.build_edition(plan)
        assert first.markdown == second.markdown and first.stats() == second.stats()
        assert set(first.trace) == {"candidates", "choice", "kept", "echoes"}


class TestGenerate:
    def test_files_go_to_the_directory_given(self, monkeypatch, tmp_path):
        default = tmp_path / "default"
        monkeypatch.setattr(ng, "DIGESTS_DIR", str(default))
        gen, ds = _planned(monkeypatch, FakeNewsroom(), _day(8))
        path = gen.generate(DAY, digests_dir=str(tmp_path / "replay"))
        assert os.path.dirname(path) == str(tmp_path / "replay") and os.path.exists(path.edition)
        assert not default.exists()
        assert path.trace["plan"].date == DAY and path.trace["edition"].markdown == open(
            path.edition, encoding="utf-8").read()
        ds.save_digest.assert_called_once()

    def test_an_empty_day_writes_to_the_directory_given(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path / "default"))
        gen, _ = _planned(monkeypatch, FakeNewsroom(), [])
        path = gen.generate(DAY, digests_dir=str(tmp_path / "x"))
        assert os.path.dirname(path) == str(tmp_path / "x")


_PATCH = re.compile(r"^\s*(?:ng|ne|ss|newsletter_generator|newsletter_edition|story_summary)\.\w+(?:\s*,[^=\n]*)?\s*=[^=]",
                    re.MULTILINE)


def test_no_script_patches_the_newsletter_modules():
    """DBT-75: replays and previews call plan/build/generate(digests_dir=); they assign no module global."""
    offenders = []
    for path in glob.glob(os.path.join(ROOT, "scripts", "**", "*.py"), recursive=True):
        if "qa_" in os.path.basename(os.path.dirname(path)) or os.path.basename(path).startswith("qa_"):
            continue          # QA's own mutant and probe harnesses patch on purpose
        if _PATCH.search(open(path, encoding="utf-8").read()):
            offenders.append(os.path.relpath(path, ROOT))
    assert offenders == [], f"these scripts patch newsletter module globals: {offenders}"


def test_the_replay_reads_the_trace(monkeypatch, tmp_path):
    """replay_newsletter_edition's coverage/stories over a real plan and edition (no LLM: FakeNewsroom)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "replay", os.path.join(ROOT, "scripts", "experiments", "replay_newsletter_edition.py"))
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    gen, _ = _planned(monkeypatch, FakeNewsroom(), _day(8))
    path = gen.generate(DAY, digests_dir=str(tmp_path))
    plan, edition = path.trace["plan"], path.trace["edition"]
    data = replay.stories(plan, edition)
    assert len(data["calls"]) == 8 and data["choice"]["utama"] and "guard_text" in data["calls"][0]["shown"][0]
    assert replay.coverage(plan, edition)["covered"] >= 5
