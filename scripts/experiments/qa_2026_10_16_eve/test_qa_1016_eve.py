"""QA 2026-10-16 (evening): QA's own tests for SYS-167..170, DBT-79 and DBT-80 (tracker #336).

Written from each ticket's text, with inputs the dev's tests do not use:
- SYS-169: an unstated future time in the latar / judul / sekilas, end to end through `parse`; the dev's
  judgement call that a future phrase inside a relative phrase ("akhir bulan ini") is judged by its span
  only, on a digest date inside that span; the weekday future times ("Kamis depan", "Senin mendatang");
- SYS-168: keys in capitals and with "akhir"; the past narrations ("keesokan harinya", "esoknya");
- SYS-170: the change-claim forms the ticket's evidence table lists beyond the fix ("menjadi total N",
  "<verb>, menjadi N"), "hingga mencapai N" and "<verb> ke N"; the date shapes after "hingga";
- SYS-167: the weekday's exact day from a Sunday digest, "Pada <hari> pekan lalu," openings, and the
  dev's judgement call that "awal / akhir pekan lalu" span the whole week.

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_16_eve/test_qa_1016_eve.py -q -p no:cacheprovider

A failing test here is a finding, recorded in .10x/reviews/2026-10-16-qa-report-evening.md and ticketed:
- TestSys169RelativeFuturePhrase late-in-the-month cases: SYS-169 #366, sent back;
- TestSys169WeekdayFuture: SYS-171 #370;  TestSys170Forms held-out forms: SYS-172 #371;
- TestSys167 part-of-week cases: SYS-173 #372.
"""
import json
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import newscrawler.core.story_arc as sa  # noqa: E402
from newscrawler.core import arc_style  # noqa: E402
from newscrawler.core import source_check as sc  # noqa: E402
from newscrawler.core.llm_json import Rejected  # noqa: E402
from tests.unit.test_story_arc import DAY, TEXTS, TIMELINE, _answer  # noqa: E402

LATAR = ("Persoalan karhutla sudah di meja Presiden sejak September. Pada 23/9 Seskab melaporkan 209 hektare lahan "
         "masih terbakar, dan pada 24 September Prabowo menggelar rapat pertama.")


def _outcome(answer, texts=TEXTS, day=DAY):
    """'kept' / 'dropped' (agenda emptied) / the refusal reason."""
    try:
        arc = sa.parse(answer, texts, TIMELINE, day)
    except Rejected as e:
        return e.reason
    return "kept" if json.loads(answer).get("agenda", "") == arc.agenda else "dropped"


# ── SYS-169: an unstated future time is refused on every prose field ───────────────────────────────

class TestSys169EveryField:
    def test_an_unstated_future_time_in_the_latar_is_refused(self):
        """The dev's comment: "on every prose field, like unbacked_times". The dev's tests cover agenda and hari_ini."""
        assert _outcome(_answer(latar=LATAR + " Rapat lanjutan digelar pekan depan.")) == "date"

    def test_an_unstated_future_time_in_the_sekilas_is_refused(self):
        assert _outcome(_answer(sekilas="Prabowo rapat karhutla lagi besok.")) == "date"

    def test_an_unstated_future_time_in_the_judul_is_refused(self):
        assert _outcome(_answer(judul="Prabowo rapat karhutla lagi, rapat lanjutan bulan depan")) == "date"

    @pytest.mark.parametrize("stated, written", [("Pekan Depan", "minggu mendatang"),
                                                 ("pekan mendatang", "Minggu depan"),
                                                 ("Esok", "besok"),
                                                 ("akhir tahun ini", "Akhir Tahun Ini")])
    def test_a_stated_synonym_backs_it_in_any_case(self, stated, written):
        texts = [TEXTS[0] + f" Rapat lanjutan dijadwalkan {stated}.", *TEXTS[1:]]
        assert _outcome(_answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}."), texts) == "kept"

    def test_a_phrase_stated_only_in_an_unrelated_article_does_not_back_it(self):
        texts = [*TEXTS[:2], TEXTS[2] + " Harga cabai diperkirakan turun pekan depan."]
        assert _outcome(_answer(agenda="Rapat lanjutan karhutla dijadwalkan pekan depan."), texts) == "date"


class TestSys169RelativeFuturePhrase:
    """The dev's judgement call: "a future phrase inside a _RELATIVE phrase ("akhir bulan ini") is judged by its
    span only". The span check backs a phrase whose days hold today -- so from the 21st on, an invented "akhir
    bulan ini" is always backed, the "no span backing" rule the dev chose for every other future time."""

    def test_unstated_akhir_bulan_ini_is_refused_early_in_the_month(self):
        assert _outcome(_answer(agenda="Aturan karhutla ditargetkan terbit akhir bulan ini.")) == "date"

    @pytest.mark.parametrize("day", [date(2026, 10, 21), date(2026, 10, 26), date(2026, 10, 31)])
    def test_unstated_akhir_bulan_ini_is_refused_late_in_the_month(self, day):
        assert _outcome(_answer(agenda="Aturan karhutla ditargetkan terbit akhir bulan ini."), day=day) == "date"

    def test_unstated_akhir_bulan_ini_in_the_latar_is_refused_late_in_the_month(self):
        latar = LATAR + " Aturan barunya menyusul akhir bulan ini."
        assert _outcome(_answer(latar=latar), day=date(2026, 10, 26)) == "date"

    @pytest.mark.parametrize("day", [date(2026, 10, 12), date(2026, 10, 26)])
    def test_stated_akhir_bulan_ini_is_kept(self, day):
        texts = [TEXTS[0] + " Aturan turunan ditargetkan terbit akhir bulan ini.", *TEXTS[1:]]
        assert _outcome(_answer(agenda="Aturan karhutla ditargetkan terbit akhir bulan ini."), texts, day) == "kept"


class TestSys169WeekdayFuture:
    """The same false schedule as the ticket's "besok", in the form news writes it for a weekday: "Kamis depan" /
    "Senin mendatang" (~190 articles, half as many as "minggu depan"). The article says "Kamis (15/10)", which is
    this week's Thursday; "Kamis depan" is the 22nd."""

    @pytest.mark.parametrize("agenda", ["Rapat lanjutan karhutla dijadwalkan Kamis depan.",
                                        "Rapat lanjutan karhutla dijadwalkan Senin mendatang.",
                                        "Rapat lanjutan karhutla dijadwalkan pada hari Jumat mendatang."])
    def test_an_unstated_weekday_future_is_refused(self, agenda):
        assert _outcome(_answer(agenda=agenda)) == "date"

    def test_a_stated_weekday_future_is_kept(self):
        texts = [TEXTS[0] + " Rapat lanjutan digelar Kamis mendatang.", *TEXTS[1:]]
        assert _outcome(_answer(agenda="Rapat lanjutan karhutla digelar Kamis depan."), texts) == "kept"


# ── SYS-168: the table ──────────────────────────────────────────────────────────────────────────

class TestSys168Table:
    @pytest.mark.parametrize("phrase, key", [("Esok", "besok"), ("ESOK", "besok"), ("Minggu Mendatang", "pekan depan"),
                                             ("akhir pekan mendatang", "akhir pekan depan"),
                                             ("tahun mendatang", "tahun depan"), ("Akhir  Tahun\nIni", "akhir tahun ini"),
                                             ("bulan mendatang", "bulan depan")])
    def test_keys(self, phrase, key):
        assert sc.future_times(f"Kebijakan itu berlaku {phrase}.") == {key}

    @pytest.mark.parametrize("text", ["Keesokan harinya rapat digelar.", "Esoknya rapat digelar.",
                                      "Besoknya rapat digelar.", "Rapat digelar esok  harinya.",
                                      "Inflasi tahun ini 2,5 persen.", "Penjualan bulan ini turun.",
                                      "Rapat digelar awal bulan ini."])
    def test_not_future_times(self, text):
        assert sc.future_phrases(text) == []

    @pytest.mark.parametrize("text", ["Aturan berlaku akhir bulan depan.", "Aturan berlaku akhir bulan mendatang."])
    def test_akhir_bulan_depan_is_not_this_months_end(self, text):
        assert sc.relative_times(text, DAY) == []
        assert sc.future_phrases(text)

    def test_akhir_pekan_depan_is_not_backed_by_pekan_depan(self):
        """A narrower time than the article states is the model's own."""
        texts = [TEXTS[0] + " Rapat lanjutan digelar pekan depan.", *TEXTS[1:]]
        assert _outcome(_answer(agenda="Rapat lanjutan karhutla digelar akhir pekan depan."), texts) == "date"


# ── SYS-170: the change claim's forms ────────────────────────────────────────────────────────────

POLRI_SRC = ("Kapolri memutasi 199 perwira melalui Surat Telegram Nomor ST/2251/X/KEP/2026. "
             "Total ada 199 pejabat Polri yang dirotasi.")


class TestSys170Forms:
    @pytest.mark.parametrize("claim", ["Kini jumlahnya bertambah sampai 199 orang.",
                                       "Kini jumlahnya Bertambah Hingga 199 orang.",
                                       "Kini jumlahnya bertambah lagi hingga sebanyak 199 orang.",
                                       "Kini jumlahnya bertambah ke posisi 199.",
                                       "Kini jumlahnya bertambah hingga  199 orang."])
    def test_the_fixed_forms_in_other_spellings_are_refused(self, claim):
        assert sc.unbacked_changes(claim, POLRI_SRC)

    @pytest.mark.parametrize("claim", ["Kini jumlahnya bertambah menjadi total 199 orang.",
                                       "Kini jumlahnya bertambah, menjadi 199 orang.",
                                       "Kini jumlahnya bertambah hingga mencapai 199 orang.",
                                       "Kini jumlahnya bertambah ke 199 orang."])
    def test_the_held_out_forms_are_refused(self, claim):
        """The ticket's own evidence table lists "menjadi total N" and "<verb>, menjadi N"; the corpus writes
        "<verb> hingga mencapai N" in 145 articles and "<verb> ke N" in 425 ("melemah ke 17.930")."""
        assert sc.unbacked_changes(claim, POLRI_SRC)

    @pytest.mark.parametrize("text", ["Harga naik sejak 1 Oktober hingga 12 Okt.",
                                      "Harga naik hingga 12/10/2026.", "Harga naik hingga 12 Oktober 2026.",
                                      "Harga naik sampai 12 Oktober."])
    def test_a_date_after_hingga_claims_no_figure(self, text):
        assert sc.unbacked_changes(text, "Harga beras di pasar induk.") == []

    def test_a_range_backed_by_a_source_change_passes(self):
        assert sc.unbacked_changes("Harga cabai naik hingga 37 persen.", "Harga cabai rawit naik 37 persen.") == []

    def test_a_year_the_source_states_with_the_change_passes(self):
        src = "Kapasitas pusat data diperkirakan tumbuh 16,8 persen per tahun hingga 2029."
        assert sc.unbacked_changes("Kapasitas pusat data terus tumbuh hingga 2029.", src) == []

    def test_end_to_end_the_hingga_claim_is_refused_as_a_number(self):
        texts = [TEXTS[0] + " Total ada 1.673 penerbangan terganggu.", *TEXTS[1:]]
        latar = LATAR + " Kini gangguan penerbangan bertambah hingga 1.673."
        assert _outcome(_answer(latar=latar), texts) == "number"


# ── SYS-167: a modifier is part of "pekan lalu" ──────────────────────────────────────────────────

JUDUL, HARI_INI = "Polri mutasi Kakorlantas", "Polri memutasi 199 perwira, Minggu (11/10)."


class TestSys167:
    @pytest.mark.parametrize("today, phrase, day", [
        (date(2026, 10, 12), "Kamis pekan lalu", date(2026, 10, 8)),
        (date(2026, 10, 12), "Minggu pekan lalu", date(2026, 10, 11)),
        (date(2026, 10, 18), "Senin pekan lalu", date(2026, 10, 5)),     # a Sunday digest: the week before this one
        (date(2026, 10, 18), "Sabtu minggu lalu", date(2026, 10, 10)),
        (date(2026, 10, 14), "Jumat pekan lalu", date(2026, 10, 9)),
    ])
    def test_the_weekday_is_that_day_of_the_previous_week(self, today, phrase, day):
        assert sc.relative_times(f"{phrase}, Polri memutasi 88 perwira.", today) == [(phrase, day, day)]

    @pytest.mark.parametrize("opening", ["Pada Senin pekan lalu, Polri memutasi 88 perwira.",
                                         "Pada akhir pekan lalu, Polri memutasi 88 perwira.",
                                         "Pertengahan pekan lalu, Polri memutasi 88 perwira."])
    def test_a_pada_or_pertengahan_opening_is_time_led_like_pekan_lalu(self, opening):
        assert arc_style.opens_on_time(opening) == arc_style.opens_on_time("Pada pekan lalu, Polri memutasi 88 perwira.")
        assert arc_style.opens_on_time(opening)
        assert not arc_style.tied_to_today(opening, JUDUL, HARI_INI)

    @pytest.mark.parametrize("frame", ["Sejak Jumat pekan lalu, Polri merombak jabatan Kapolda.",
                                       "Sejak pertengahan minggu lalu, Polri merombak jabatan Kapolda."])
    def test_held_out_modified_frames_are_not_anchors(self, frame):
        assert arc_style.time_anchors(frame) == []

    def test_an_unbacked_weekday_is_refused_and_a_backed_one_passes(self):
        """"Senin pekan lalu" is 5/10 from 12/10: no chosen item or source date is that day."""
        assert sa.unbacked_times("Senin pekan lalu Polri memutasi perwira.", DAY, {date(2026, 10, 8)}, "") \
            == ["Senin pekan lalu"]
        assert sa.unbacked_times("Kamis pekan lalu Polri memutasi perwira.", DAY, {date(2026, 10, 8)}, "") == []

    @pytest.mark.parametrize("phrase, outside", [("Awal pekan lalu", date(2026, 10, 10)),
                                                  ("Awal pekan lalu", date(2026, 10, 11)),
                                                  ("Akhir pekan lalu", date(2026, 10, 5))])
    def test_a_part_of_last_week_is_not_the_whole_week(self, phrase, outside):
        """The dev's judgement call: awal/pertengahan/akhir keep the whole week. "Awal pekan lalu" for a Sunday item
        is false whichever way "akhir pekan" is read; a month's parts are narrowed (`_month_part`), a week's are not."""
        assert sa.unbacked_times(f"{phrase} Polri memutasi perwira.", DAY, {outside}, "") == [phrase]


# ── DBT-80: the registry check ──────────────────────────────────────────────────────────────────

class TestDbt80Hygiene:
    def test_an_entry_on_a_missing_file_is_red(self):
        from tests.unit import test_repo_hygiene as h
        with pytest.raises(Exception):
            h._orphaned([("gone", "newscrawler/core/no_such_module.py", "x", "y")], h._read)

    def test_an_entry_doubled_only_in_crlf_form_is_red(self):
        from tests.unit import test_repo_hygiene as h
        files = {"d.py": "a\r\nb\r\na\r\nb\r\n"}
        assert h._orphaned([("dbl", "d.py", "a\nb", "a\nc")], files.__getitem__) == ["dbl (d.py): 2 matches"]
