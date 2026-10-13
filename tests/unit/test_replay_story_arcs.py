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


    def test_one_reads_as_story_row_per_arc(self, replay):
        arc = _arc("IHSG anjlok", "Ini pekan kedua IHSG melemah.", agenda="BI rapat Rabu (14/10).")
        rows = replay.handcheck_rows(date(2026, 10, 12), SimpleNamespace(trace={"arcs": [{"arc": arc}]}))
        assert [(r["kind"], r["text"], r["reads_as_story"]) for r in rows if r["kind"] == "arc"] == [
            ("arc", "Ini pekan kedua IHSG melemah. BI rapat Rabu (14/10).", "")]
        assert set(rows[0]) == set(replay.HANDCHECK_FIELDS)


CHRONICLE = "Pelemahan ini berlanjut. Pada 24/9 IHSG turun. Pada 25/9 IHSG dibahas, dan pada 1/10 disebut anjlok."
STORY = "Ini pekan kedua IHSG melemah. Akhir September indeks sudah turun 3,09%."


def _record(back, alur=True, judul="IHSG anjlok", hari_ini="IHSG ditutup anjlok 2,59%."):
    return {"judul": judul, "hari_ini": hari_ini, "back": back, "alur": alur}


class TestStyleMetrics:
    """SYS-160 (#355): the numbers the arcs' writing is judged by."""

    def test_on_fixed_back_stories(self, replay):
        m = replay.style_metrics([_record(CHRONICLE), _record(STORY), _record("", alur=False),
                                  _record("Gempa ini terjadi tanpa korban.", alur=False)])
        assert m == {"back_stories": 3, "sentences": 6, "date_led": 2, "date_led_share": 0.333,
                     "dates_mean": 1.0, "dates_max": 3, "with_3_dates_or_more": 1, "non_events": 2,
                     "tied_to_today": 1, "tied_checked": 2, "tied_share": 0.5}

    def test_nothing_to_measure(self, replay):
        m = replay.style_metrics([])
        assert m["back_stories"] == 0 and m["date_led_share"] is None and m["tied_share"] is None

    def test_back_stories_of_an_edition_are_the_built_arcs(self, replay):
        arc = _arc("IHSG anjlok", STORY, [_item(1, date(2026, 9, 25))], hari_ini="IHSG anjlok.", agenda="Rapat Rabu.")
        edition = SimpleNamespace(trace={"arcs": [{"arc": arc}, {"arc": None}]})
        assert replay.back_stories(edition) == [{"judul": "IHSG anjlok", "hari_ini": "IHSG anjlok.",
                                                 "back": STORY + " Rapat Rabu.", "alur": True}]


ARCS_MD = """# Rangkuman Berita

## Berita Utama

### [IHSG anjlok 2,59%](https://a/1)

IHSG ditutup anjlok 2,59%.

{back}

**Diberitakan 9 portal** · [Baca di Kontan →](https://a/1)

### [Emas naik](https://a/2)

Harga emas naik Rp20.000 per gram. Harga 0,5 gram Rp1.346.000.

**Diberitakan 7 portal** · [Baca di Kontan →](https://a/2)

## Sekilas

- **Pasar ·** satu baris.
"""
TODAY_MD = """# Rangkuman Berita

## Berita Utama

### [IHSG turun](https://a/1)

IHSG turun hari ini.

- poin

### [Emas naik](https://a/2)

Harga emas naik Rp20.000 per gram.

- Harga 0,5 gram Rp1.346.000.

**Mengapa penting:** emas jadi pelarian.
**Diberitakan 7 portal** · [Baca di Kontan →](https://a/2)

### [Lain](https://a/3)

Berita lain.
"""


class TestFromMarkdown:
    def test_stories_in_the_top_stories_section(self, replay):
        stories = replay.stories_in(ARCS_MD.format(back=STORY))
        assert [(s["judul"], s["link"]) for s in stories] == [("IHSG anjlok 2,59%", "https://a/1"),
                                                              ("Emas naik", "https://a/2")]
        assert stories[0]["paragraphs"] == ["IHSG ditutup anjlok 2,59%.", STORY]
        assert replay.stories_in(TODAY_MD)[1]["paragraphs"][-1] == "**Mengapa penting:** emas jadi pelarian."

    def test_a_fallback_story_is_not_an_arc(self, replay):
        """The emas story's prose starts with today's summary of it: the arc failed, it is the summary."""
        records = replay.back_stories_from_markdown(ARCS_MD.format(back=CHRONICLE), TODAY_MD, {"IHSG anjlok 2,59%"})
        assert records == [{"judul": "IHSG anjlok 2,59%", "hari_ini": "IHSG ditutup anjlok 2,59%.", "back": CHRONICLE,
                            "alur": True}]

    def test_metrics_from_an_earlier_run(self, replay, tmp_path):
        (tmp_path / "key.json").write_text('{"2026-10-12": {"X": "arcs", "Y": "today"}}', encoding="utf-8")
        (tmp_path / "2026-10-12-X.md").write_text(ARCS_MD.format(back=CHRONICLE), encoding="utf-8")
        (tmp_path / "2026-10-12-Y.md").write_text(TODAY_MD, encoding="utf-8")
        (tmp_path / "handcheck.csv").write_text('date,kind,story\n2026-10-12,alur,"IHSG anjlok 2,59%"\n',
                                                encoding="utf-8")
        m = replay.metrics_from(str(tmp_path))
        assert m["total"]["back_stories"] == 1 and m["total"]["date_led"] == 2 and m["total"]["tied_checked"] == 1
        assert m["dates"]["2026-10-12"] == m["total"]


class TestCompare:
    def test_three_versions_per_story_blind(self, replay):
        import random

        new_md, old_md = ARCS_MD.format(back=STORY), ARCS_MD.format(back=CHRONICLE)
        markdown, key = replay.compare_markdown(date(2026, 10, 12), new_md, old_md, TODAY_MD, random.Random(1))
        assert sorted(key["IHSG anjlok 2,59%"].values()) == ["baru", "hari_ini", "lama"]
        ihsg = markdown.split("## IHSG anjlok 2,59%")[1].split("\n## ")[0]
        assert ihsg.count("### Versi ") == 3 and STORY in ihsg and CHRONICLE in ihsg and "IHSG turun hari ini." in ihsg
        label_of_new = next(label for label, kind in key["IHSG anjlok 2,59%"].items() if kind == "baru")
        assert STORY in ihsg.split(f"### Versi {label_of_new}")[1].split("### Versi")[0]

    def test_the_order_is_random(self, replay):
        import random

        new_md, old_md = ARCS_MD.format(back=STORY), ARCS_MD.format(back=CHRONICLE)
        first = {replay.compare_markdown(date(2026, 10, 12), new_md, old_md, TODAY_MD, random.Random(seed))[1][
            "IHSG anjlok 2,59%"]["A"] for seed in range(12)}
        assert first == {"baru", "lama", "hari_ini"}

    def test_a_story_the_old_run_did_not_have(self, replay):
        import random

        old_md = ARCS_MD.format(back=CHRONICLE).replace("https://a/1", "https://a/9")
        _, key = replay.compare_markdown(date(2026, 10, 12), ARCS_MD.format(back=STORY), old_md, TODAY_MD,
                                         random.Random(1))
        assert sorted(key["IHSG anjlok 2,59%"].values()) == ["baru", "hari_ini"]


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
