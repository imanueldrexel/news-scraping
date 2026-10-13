"""SYS-150 (#340): the A/B replay's own logic -- the hand-check rows, the
repetition share between consecutive days, and the metered summarizer that
keeps the replay's calls out of api_usage_log."""
import importlib.util
import os
from datetime import date
from types import SimpleNamespace

import pytest

from newscrawler.core.story_arc import StoryArc
from newscrawler.core.summarizer import Reply, SummarizerError
from newscrawler.core.thread_finder import TimelineItem

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def replay():
    spec = importlib.util.spec_from_file_location(
        "replay_story_arcs", os.path.join(ROOT, "scripts", "experiments", "replay_story_arcs.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _item(sid, day):
    return TimelineItem(sid, day, "CNBC", f"Judul {sid}", "pembuka", 0.8, 1)


def _arc(judul, latar, items=(), hari_ini="Hari ini.", agenda=""):
    return StoryArc(judul, hari_ini, latar, agenda, "sekilas", [0], [], list(range(len(items))), list(items))


class TestHandcheck:
    def test_one_row_per_timeline_item_and_per_causal_sentence(self, replay):
        arc = _arc("IHSG anjlok", "Pada 24/9 IHSG turun. Penurunan ini dipicu aksi jual asing, kata analis.",
                   [_item(1, date(2026, 9, 24)), _item(2, date(2026, 10, 1))],
                   hari_ini="IHSG jatuh karena rupiah melemah.")
        edition = SimpleNamespace(trace={"arcs": [{"arc": arc}, {"arc": None}]})
        rows = replay.handcheck_rows(date(2026, 10, 12), edition)
        assert [(r["kind"], r["item_date"]) for r in rows if r["kind"] == "alur"] == [
            ("alur", "2026-09-24"), ("alur", "2026-10-01")]
        causal = {r["text"]: r["attributed"] for r in rows if r["kind"] == "causal"}
        assert causal == {"IHSG jatuh karena rupiah melemah.": "no attribution word",
                          "Penurunan ini dipicu aksi jual asing, kata analis.": ""}


class TestRepetition:
    def test_a_continuing_story_that_retells_yesterdays_latar(self, replay):
        yesterday = [(_arc("Karhutla", "Pada 24/9 Prabowo menggelar rapat pertama soal karhutla di Istana."), [501, 502])]
        today = [(_arc("Karhutla lagi", "Pada 24/9 Prabowo menggelar rapat pertama soal karhutla di Istana. "
                                        "Titik panas naik di Kalimantan Tengah pekan ini.",
                       [_item(502, date(2026, 10, 11))]), [601])]
        assert replay.repetition(today, yesterday) == {"sentences": 2, "repeated": 1, "share": 0.5}

    def test_a_story_that_does_not_continue_yesterdays_is_not_counted(self, replay):
        yesterday = [(_arc("Karhutla", "Pada 24/9 Prabowo menggelar rapat pertama soal karhutla."), [501])]
        today = [(_arc("Lain", "Pada 24/9 Prabowo menggelar rapat pertama soal karhutla.",
                       [_item(999, date(2026, 10, 11))]), [601])]
        assert replay.repetition(today, yesterday) == {"sentences": 0, "repeated": 0, "share": None}


class TestMetered:
    def test_counts_calls_and_tokens_and_refuses_an_empty_answer(self, replay):
        inner = SimpleNamespace(name="m", complete=lambda p: Reply("jawaban", 100, 20))
        meter = replay.Metered(inner)
        assert meter.summarize("p") == "jawaban" and meter.snapshot() == (1, 100, 20)
        meter.inner = SimpleNamespace(name="m", complete=lambda p: Reply("  ", 5, 0))
        with pytest.raises(SummarizerError):
            meter.summarize("p")
        assert meter.snapshot() == (2, 105, 20)
