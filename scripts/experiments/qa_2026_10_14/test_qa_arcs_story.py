"""QA 2026-10-14: QA's own tests for SYS-154..160 (story arcs read as stories, tracker #336).

Written from each ticket's Proposal / Done-when with inputs the dev's tests do not use: held-out
date-opening shapes, year boundaries, phrases that contain a shorter listed phrase, collective
ordinals after verbs, records with a one-word key, recaps in relative time. Run:

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_14/test_qa_arcs_story.py -q -p no:cacheprovider

A failing test here is a finding, recorded in .10x/reviews/2026-10-14-qa-report.md.
"""
import json
import os
import re
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import newscrawler.core.story_arc as sa  # noqa: E402
from newscrawler.core import arc_style  # noqa: E402
from newscrawler.core.llm_json import Rejected  # noqa: E402
from newscrawler.core.source_check import dates_in, ordinal_claims, relative_times  # noqa: E402
from newscrawler.core.thread_finder import TimelineItem  # noqa: E402
from tests.unit.test_story_arc import DAY, N, TEXTS, TIMELINE, _answer, _texts  # noqa: E402

MON = date(2026, 10, 12)        # a Monday (the dev's DAY)
SUN = date(2026, 10, 11)


def _span(phrase, today=MON):
    found = relative_times(phrase, today)
    assert len(found) == 1, found
    return found[0][1], found[0][2]


def _parse(answer, texts=TEXTS, timeline=TIMELINE, lenient=False):
    return sa.parse(answer, texts, timeline, DAY, lenient=lenient)


def _reason(answer, **kw):
    with pytest.raises(Rejected) as e:
        _parse(answer, **kw)
    return e.value.reason, e.value.detail


# ── SYS-154 / SYS-155: the prompt and its example ──────────────────────────────────────────────

class TestSys154Prompt:
    def test_the_chronicle_wording_is_gone(self):
        p = sa.PROMPT.lower()
        assert "setiap fakta bertanggal" not in p and "urut waktu" not in p
        assert "ditulis dengan tanggalnya" not in p
        assert "setiap fakta dari lini masa harus berasal dari cuplikannya" in p

    @pytest.mark.parametrize("rule", ["bingkai", "dua titik balik", "kaitkan", "waktu relatif",
                                      "jangan membuka dua kalimat", "hanya jika artikel menyebutnya"])
    def test_rules_1_to_6_are_there(self, rule):
        assert rule in sa.PROMPT.lower()

    def test_the_prompt_no_longer_shows_a_pada_date_as_a_model(self):
        """The old example taught 'Pada 27/9, ...'. The only 'Pada d/m' left must be in a 'not this' clause."""
        for m in re.finditer(r"Pada \d{1,2}/\d{1,2}", sa.PROMPT):
            assert "bukan" in sa.PROMPT[max(0, m.start() - 60):m.start()]


class TestSys155Example:
    def _example_latar(self):
        start = sa.PROMPT.index("CONTOH JAWABAN")
        block = sa.PROMPT[sa.PROMPT.index("{{", start):sa.PROMPT.index("HARI INI\n", start)]
        data = json.loads(" ".join(block.replace("{{", "{").replace("}}", "}").split()))
        return data

    def test_example_is_a_story(self):
        latar = self._example_latar()["latar"]
        sents = arc_style.sentences(latar)
        assert len(dates_in(latar)) <= 2
        assert not arc_style.opens_on_date(sents[0])
        openings = [arc_style.opening(s) for s in sents]
        assert len(openings) == len(set(openings))
        assert sa.chronicle(latar, self._example_latar()["judul"], self._example_latar()["hari_ini"], True) == []

    def test_example_is_not_from_the_replay_week(self):
        for d in range(8, 13):
            assert f"({d}/10)" not in self._example_latar()["hari_ini"]


# ── SYS-156: the style refusal ─────────────────────────────────────────────────────────────────

class TestSys156OpensOnDate:
    """'more than 1 sentence opening with "Pada <date>" / "<date>,"' -- held-out shapes an Indonesian
    writer uses for the same thing."""

    @pytest.mark.parametrize("sentence", [
        "Pada 3/10, Polri memutasi 88 perwira.",
        "3 Oktober lalu, Polri memutasi 88 perwira.",
        "Sabtu (3/10), Polri memutasi 88 perwira.",
        "Kemudian pada 5/10 peta mutasi dibahas.",
        "Pada tanggal 3 Oktober, Polri memutasi 88 perwira.",
        "Pada hari Sabtu (3/10), Polri memutasi 88 perwira.",
        "Pada Sabtu, 3 Oktober, Polri memutasi 88 perwira.",
        "Tanggal 3/10, Polri memutasi 88 perwira.",
    ])
    def test_held_out_date_openings(self, sentence):
        assert arc_style.opens_on_date(sentence)

    @pytest.mark.parametrize("sentence", [
        "Polri memutasi 88 perwira pada 3/10.",
        "Mutasi ini lanjutan rotasi awal Oktober.",
        "Kapolri yang dilantik 30 September memutasi 88 perwira.",
    ])
    def test_not_a_date_opening(self, sentence):
        assert not arc_style.opens_on_date(sentence)


class TestSys156Chronicle:
    J, H = "Polri mutasi 199 perwira, Kakorlantas berganti", "Polri memutasi 199 perwira, Minggu (11/10)."

    def test_three_dates_in_three_forms(self):
        latar = "Mutasi Polri ini lanjutan. Rotasi 24 September, 30/9 dan 2 Okt mengubah peta Polda."
        assert any("3 tanggal" in p for p in sa.chronicle(latar, self.J, self.H, True))

    def test_at_the_limits_passes(self):
        latar = ("Mutasi Polri ini gelombang lanjutan. Pada 3/10, Polri memutasi 88 perwira, "
                 "dan sertijab digelar 9/10.")
        assert sa.chronicle(latar, self.J, self.H, True) == []

    def test_same_opening_word_ignores_case(self):
        latar = "Mutasi Polri ini gelombang lanjutan. MUTASI pertama memindahkan 88 perwira."
        assert any("dibuka dengan kata" in p for p in sa.chronicle(latar, self.J, self.H, True))

    def test_the_reason_is_counted(self):
        assert "style" in sa.REASONS
        from newscrawler.core.newsletter_edition import ARC_REASONS
        assert "style" in ARC_REASONS

    def test_style_survives_the_lenient_retry(self):
        """'On the retry it is still refused' -- lenient only moves strays."""
        latar = "Karhutla sudah lama di meja Presiden. Pada 23/9 Seskab melapor. Pada 24/9 Prabowo rapat."
        assert _reason(_answer(latar=latar), lenient=True)[0] == "style"


# ── SYS-157: relative time ─────────────────────────────────────────────────────────────────────

class TestSys157Ranges:
    """The ranges in the ticket ('awal Oktober' = 1-10 Oct; 'sepekan lalu' = 5-9 days before), from a Monday."""

    @pytest.mark.parametrize("phrase,first,last", [
        ("awal Oktober", date(2026, 10, 1), date(2026, 10, 10)),
        ("pertengahan September", date(2026, 9, 11), date(2026, 9, 20)),
        ("akhir September", date(2026, 9, 21), date(2026, 9, 30)),
        ("akhir bulan lalu", date(2026, 9, 21), date(2026, 9, 30)),
        ("bulan lalu", date(2026, 9, 1), date(2026, 9, 30)),
        ("sejak Agustus", date(2026, 8, 1), date(2026, 8, 31)),
        ("sepekan lalu", date(2026, 10, 3), date(2026, 10, 7)),
        ("dua pekan lalu", date(2026, 9, 25), date(2026, 10, 1)),
        ("dua pekan terakhir", date(2026, 9, 28), date(2026, 10, 11)),
        ("pekan lalu", date(2026, 10, 5), date(2026, 10, 11)),
        ("kemarin", date(2026, 10, 11), date(2026, 10, 11)),
        ("dua hari lalu", date(2026, 10, 9), date(2026, 10, 11)),
        ("Jumat lalu", date(2026, 10, 9), date(2026, 10, 9)),
        ("Senin lalu", date(2026, 10, 5), date(2026, 10, 5)),
    ])
    def test_range(self, phrase, first, last):
        assert _span(phrase) == (first, last)

    def test_year_boundary(self):
        today = date(2027, 1, 5)
        assert _span("akhir Desember", today) == (date(2026, 12, 21), date(2026, 12, 31))
        assert _span("bulan lalu", today) == (date(2026, 12, 1), date(2026, 12, 31))
        assert _span("pekan lalu", today) == (date(2026, 12, 28), date(2027, 1, 3))

    def test_akhir_februari_leap_year(self):
        assert _span("akhir Februari", date(2028, 3, 10)) == (date(2028, 2, 21), date(2028, 2, 29))

    def test_a_calendar_date_is_not_a_relative_phrase(self):
        assert relative_times("Polri memutasi 88 perwira pada 3 Oktober.", MON) == []

    @pytest.mark.parametrize("phrase", ["tiga pekan lalu", "empat pekan lalu", "dua bulan lalu", "tiga bulan lalu"])
    def test_a_longer_phrase_is_not_read_as_the_shorter_one(self, phrase):
        """'tiga pekan lalu' is three weeks back, not 'pekan lalu' (the previous week); 'dua bulan lalu' is
        August, not September. Reading it as the shorter phrase makes the check accept a wrong time and
        refuse a right one."""
        found = relative_times(f"Polri memutasi 88 perwira {phrase}.", MON)
        assert all(p.lower() != phrase.split(" ", 1)[1] for p, _, _ in found), found


class TestSys157InParse:
    def test_backed_passes_unbacked_is_refused(self):
        assert _parse(_answer(latar="Karhutla sudah lama di meja Presiden, setidaknya sejak akhir September. "
                                    "Seskab melaporkan 209 hektare lahan masih terbakar."))
        reason, detail = _reason(_answer(latar="Karhutla sudah lama di meja Presiden. Kemarin Seskab melaporkan "
                                               "209 hektare lahan masih terbakar."))
        assert reason == "date" and '"Kemarin"' in detail

    def test_a_phrase_in_an_old_timeline_item_does_not_license_it_today(self):
        """A relative phrase is relative to the day it was written. A 23/9 snippet that says 'kemarin'
        means 22/9; it cannot back today's 'kemarin' (11/10) -- the model copying a snippet's wording
        is exactly the slip SYS-157 is for. ('stated verbatim in an article' = today's articles.)"""
        timeline = [TIMELINE[0]._replace(opening="Kemarin Seskab melaporkan 209 hektare lahan masih terbakar.")] \
            + TIMELINE[1:]
        latar = "Karhutla sudah lama di meja Presiden. Kemarin Seskab melaporkan 209 hektare lahan masih terbakar."
        reason, _ = _reason(_answer(latar=latar), timeline=timeline)
        assert reason == "date"


# ── SYS-158: ordinal and series claims ─────────────────────────────────────────────────────────

def _keys(text):
    return [k for _, _, k in ordinal_claims(text)]


class TestSys158Claims:
    @pytest.mark.parametrize("text,n", [
        ("Ini gelombang ketiga mutasi.", 3), ("Polri merombak untuk keempat kalinya.", 4),
        ("Ini mutasi ke-5 tahun ini.", 5), ("Polri merombak untuk kesekian kalinya.", 3),
        ("IHSG turun lima hari beruntun.", 5), ("Rupiah melemah 3 sesi berturut-turut.", 3),
    ])
    def test_found(self, text, n):
        assert [c[1] for c in ordinal_claims(text)] == [n]

    @pytest.mark.parametrize("text", [
        "Kedua negara meneken EPA.", "Pertemuan kedua belah pihak berlangsung tertutup.",
        "EPA disepakati antara kedua negara.", "Keduanya bertemu di Istana.",
        "Polisi menahan kedua tersangka.", "Jaksa memeriksa ketiga saksi kemarin.",
        "KPK menetapkan kelima tersangka itu.", "Hakim memvonis keempat terdakwa.",
    ])
    def test_collective_is_not_a_claim(self, text):
        """'kedua negara' = both countries; after a verb ('menahan kedua tersangka' = held both suspects)
        a word ordinal is collective too. The ticket: 'a claim only after a noun'."""
        assert ordinal_claims(text) == []

    def test_n_times_in_a_row_is_a_series_claim(self):
        """'BI menaikkan suku bunga tiga kali berturut-turut' is a series count no digit check sees."""
        assert [c[1] for c in ordinal_claims("BI menaikkan suku bunga tiga kali berturut-turut.")] == [3]

    def test_a_record_key_holds_its_whole_time(self):
        """'terendah sejak awal Maret' in a source must not license 'terendah sejak awal tahun'."""
        assert _keys("IHSG terendah sejak awal tahun.") != _keys("IHSG terendah sejak awal Maret.")


class TestSys158InParse:
    def test_excess_refused_backed_passes(self):
        assert _parse(_answer(latar="Ini rapat karhutla ketiga Prabowo. Seskab melaporkan 209 hektare."))
        assert _reason(_answer(alur=[N], latar="Ini rapat karhutla ketiga Prabowo. Seskab melaporkan 209 hektare."))[0] \
            == "number"

    def test_kesekian_needs_two_items(self):
        assert _reason(_answer(alur=[N], latar="Ini rapat karhutla untuk kesekian kalinya. Seskab melapor."))[0] \
            == "number"

    def test_record_only_when_stated(self):
        latar = "Karhutla kali ini terluas, tertinggi sejak 2019. Seskab melaporkan 209 hektare."
        assert _reason(_answer(latar=latar))[0] == "number"
        assert _parse(_answer(latar=latar), texts=_texts("Luas karhutla tertinggi sejak 2019."))

    def test_a_collective_after_a_verb_does_not_cost_a_retry(self):
        """No alur, a hari_ini naming 'kedua tersangka' -- a common crime-desk phrase -- must pass."""
        hari_ini = "Polisi menahan kedua tersangka karhutla di Istana Negara, Senin (12/10)."
        assert _parse(_answer(alur=[], latar="", hari_ini=hari_ini, judul="Polisi tahan dua tersangka karhutla"))


# ── SYS-159: the tie to today ──────────────────────────────────────────────────────────────────

class TestSys159Tie:
    J, H = "Polri mutasi Kakorlantas", "Polri memutasi 199 perwira, termasuk Kakorlantas, Minggu (11/10)."

    def test_ticket_example_recap_is_refused(self):
        assert not arc_style.tied_to_today("Pada 3/10, Polri memutasi 88 perwira.", self.J, self.H)

    def test_research_rewrite_is_tied(self):
        assert arc_style.tied_to_today("Ini gelombang kedua perombakan Polri bulan ini.", self.J, self.H)

    def test_a_vague_first_sentence_is_refused(self):
        assert not arc_style.tied_to_today("Persoalan ini sudah lama berjalan.", self.J, self.H)

    @pytest.mark.parametrize("recap", [
        "Awal Oktober, Polri memutasi 88 perwira.",
        "Pekan lalu, Polri memutasi 88 perwira.",
        "Sabtu lalu Polri memutasi 88 perwira tinggi.",
    ])
    def test_the_same_recap_in_relative_time_is_refused(self, recap):
        """The ticket's recap with its date written the way SYS-154 now asks: still a free-standing recap
        of a past item, not a frame of today's news."""
        assert not arc_style.tied_to_today(recap, self.J, self.H)

    def test_a_since_frame_passes(self):
        assert arc_style.tied_to_today("Sejak awal Oktober, Polri sudah dua kali merombak jabatan Kapolda.",
                                       self.J, self.H)

    def test_no_alur_is_exempt_in_parse(self):
        assert _parse(_answer(alur=[], latar="Dampaknya dirasakan warga Sumatera, menurut Menko Polkam."))


# ── SYS-160: the metrics ───────────────────────────────────────────────────────────────────────

class TestSys160Metrics:
    @pytest.mark.parametrize("sentence,led", [
        ("Pada 3/10, Polri memutasi 88 perwira.", True),
        ("Polri memutasi 88 perwira pada 3/10.", True),
        ("Polri memutasi 88 perwira pada Sabtu (3/10).", True),
        ("Sebelumnya, pada 19/9, Polri merotasi Kapolda.", True),
        ("Polri memutasi 88 perwira awal Oktober.", False),
        ("Kapolri yang dilantik 30 September memutasi 88 perwira.", False),
    ])
    def test_date_led(self, sentence, led):
        assert arc_style.date_led(sentence) is led

    def test_style_metrics_on_fixed_records(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments"))
        from replay_story_arcs import style_metrics
        records = [
            {"back": "Pada 3/10, Polri memutasi 88 perwira. Pada 5/10 dan 7/10 peta dibahas. Mutasi berlanjut.",
             "judul": "Polri mutasi Kakorlantas", "hari_ini": "Polri memutasi 199 perwira.", "alur": [1, 2]},
            {"back": "Mutasi ini gelombang lanjutan Polri.", "judul": "Polri mutasi Kakorlantas",
             "hari_ini": "Polri memutasi 199 perwira.", "alur": [1]},
            {"back": "Dampaknya dirasakan warga.", "judul": "Gempa Panama", "hari_ini": "Gempa M 7,7.", "alur": []},
            {"back": "", "judul": "x", "hari_ini": "y", "alur": []},
            {"back": "Mutasi Polri berlanjut sejak 3/10 dan 5/10.", "judul": "Polri mutasi Kakorlantas",
             "hari_ini": "Polri memutasi 199 perwira.", "alur": [1]},       # 2 dates: not ">= 3"
        ]
        m = style_metrics(records)
        assert m["back_stories"] == 4 and m["sentences"] == 6
        assert m["date_led"] == 2 and m["date_led_share"] == 0.333
        assert m["dates_max"] == 3 and m["with_3_dates_or_more"] == 1 and m["dates_mean"] == 1.25
        assert m["non_events"] == 1
        assert m["tied_checked"] == 3 and m["tied_to_today"] == 2 and m["tied_share"] == 0.667
