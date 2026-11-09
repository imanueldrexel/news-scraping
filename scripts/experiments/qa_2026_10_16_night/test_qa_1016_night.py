"""QA 2026-10-16 (night): QA's own tests for the SYS-169 rework, SYS-171, SYS-172 and SYS-173 (tracker #336).

Written from each ticket's text, with inputs the dev's tests do not use:
- SYS-169 rework: "akhir bulan ini" / "akhir tahun ini" on every late day of the period, in every prose field; named
  once; the past relative phrases still judged by their span (regression); and the same invented schedule written
  as a month part the future table does not list ("akhir bulan", "akhir Oktober", "pertengahan bulan ini");
- SYS-171: every weekday, both suffixes, "hari" in any case, the Sunday call both ways, a different weekday, the
  windows' counts and units, SYS-166's scheduled step and SYS-163's repeat through the new keys; and the weekday
  written with "pekan depan" ("Kamis pekan depan"), which the fix's own comment says never meets "pekan depan";
- SYS-172: "ke N" after a long gap, after a comma, two words before N; the false readings (a road, an ordinal, a
  date); and "<verb> mencapai N" with no to-word, which the dev noted and left;
- SYS-173: each part's first and last day and the day either side, from a Monday, a Wednesday and a Sunday digest,
  through `relative_times`, `unbacked_times` and `parse`.

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_16_night/test_qa_1016_night.py -q -p no:cacheprovider

A failing test here is a finding, recorded in .10x/reviews/2026-10-16-qa-report-night.md and ticketed:
- TestSys171WeekdayNextWeek: SYS-171 #370, sent back;
- TestMonthPartFuture: SYS-174 #373 (the SYS-169 hole through month parts);
- TestChangeMencapai: SYS-175 #374 ("<verb> mencapai N");
- TestRunningPeriodWithAWeekday: SYS-176 #375 ("hingga Senin (12/10)" is no running period).
"""
import json
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import newscrawler.core.story_arc as sa  # noqa: E402
from newscrawler.core import source_check as sc  # noqa: E402
from newscrawler.core.llm_json import Rejected  # noqa: E402
from newscrawler.core.thread_finder import TimelineItem  # noqa: E402
from tests.unit.test_story_arc import DAY, FRAME, TEXTS, TIMELINE, _answer  # noqa: E402
from tests.unit.test_source_check import POLRI  # noqa: E402

KAMIS_LINE = "Rapat lanjutan dijadwalkan Kamis (15/10)."
assert KAMIS_LINE in TEXTS[0]


def _texts(sentence=""):
    """TEXTS with article [0]'s only next step ("Kamis (15/10)") replaced by `sentence`."""
    return [TEXTS[0].replace(KAMIS_LINE, sentence), *TEXTS[1:]]


def _outcome(answer, texts=TEXTS, day=DAY, timeline=TIMELINE):
    """'kept' / 'dropped' (agenda emptied) / the refusal reason."""
    try:
        arc = sa.parse(answer, texts, timeline, day)
    except Rejected as e:
        return e.reason
    return "kept" if json.loads(answer).get("agenda", "") == arc.agenda else "dropped"


def _detail(answer, texts=TEXTS, day=DAY, timeline=TIMELINE):
    with pytest.raises(Rejected) as e:
        sa.parse(answer, texts, timeline, day)
    return e.value.reason, e.value.detail


LATAR = FRAME + "Pada 23/9 Seskab melaporkan 209 hektare lahan masih terbakar."


# ── SYS-169 rework: a future phrase is judged by key only ──────────────────────────────────────────

class TestSys169KeyOnly:
    @pytest.mark.parametrize("day", [date(2026, 10, d) for d in (21, 25, 30, 31)])
    @pytest.mark.parametrize("field", ["agenda", "hari_ini", "latar", "sekilas"])
    def test_an_invented_akhir_bulan_ini_is_refused_every_late_day(self, day, field):
        value = {"agenda": "Rapat lanjutan karhutla dijadwalkan akhir bulan ini.",
                 "hari_ini": "Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara. "
                             "Aturan barunya terbit akhir bulan ini.",
                 "latar": LATAR + " Aturan barunya menyusul akhir bulan ini.",
                 "sekilas": "Aturan karhutla terbit akhir bulan ini."}[field]
        reason, detail = _detail(_answer(**{field: value}), _texts(), day)
        assert reason == "date" and detail.count('"akhir bulan ini"') == 1

    @pytest.mark.parametrize("day", [date(2026, 12, 21), date(2026, 12, 31), date(2026, 10, 12)])
    def test_an_invented_akhir_tahun_ini_is_refused_even_in_late_december(self, day):
        assert _outcome(_answer(agenda="Rapat lanjutan karhutla dijadwalkan akhir tahun ini."), _texts(), day) == "date"

    @pytest.mark.parametrize("stated", ["Aturan terbit akhir bulan ini.", "Aturan Terbit Akhir Bulan Ini",
                                        "Aturan terbit akhir  bulan  ini."])
    def test_a_stated_one_backs_it_in_any_case_and_spacing(self, stated):
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan akhir bulan ini.")
        assert _outcome(answer, _texts(stated), date(2026, 10, 26)) == "kept"

    def test_the_span_check_no_longer_reads_a_future_phrase(self):
        assert sa.unbacked_times("Evaluasi akhir bulan ini.", date(2026, 10, 12), {date(2026, 10, 12)}, "") == []

    @pytest.mark.parametrize("text", ["Rapat pertama digelar pekan lalu.", "Rapat pertama digelar awal Oktober.",
                                      "Rapat pertama digelar kemarin.", "Rapat pertama digelar akhir bulan lalu."])
    def test_a_past_phrase_is_still_judged_by_its_span(self, text):
        """Regression: the skip is for future phrases only. Known = today (12/10) only, nothing stated."""
        assert sa.unbacked_times(text, DAY, {DAY}, "") != []

    def test_a_past_phrase_a_chosen_item_backs_still_passes(self):
        assert sa.unbacked_times("Rapat pertama digelar akhir September.", DAY, {DAY, date(2026, 9, 24)}, "") == []


class TestMonthPartFuture:
    """The SYS-169 hole, written as a month part `_FUTURE` does not list. `_RELATIVE` reads "akhir bulan",
    "akhir Oktober" and "pertengahan bulan ini" as spans of this month; today is a known day, so from the day the
    span opens an invented schedule in it is backed by today and printed. "akhir bulan ini" is refused on the same
    days; the reader cannot tell the two apart. A source date inside the span still backs it (last test)."""

    @pytest.mark.parametrize("phrase,day", [("akhir bulan", date(2026, 10, 21)), ("akhir bulan", date(2026, 10, 26)),
                                            ("akhir Oktober", date(2026, 10, 26)),
                                            ("pertengahan bulan ini", date(2026, 10, 12)),
                                            ("pertengahan Oktober", date(2026, 10, 15)),
                                            ("awal bulan depan", date(2026, 10, 12))])
    def test_an_invented_month_part_schedule_is_refused(self, phrase, day):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {phrase}.")
        assert _outcome(answer, _texts("Rapat lanjutan belum dijadwalkan."), day) == "date"

    def test_in_the_latar_too(self):
        answer = _answer(latar=LATAR + " Aturan barunya menyusul akhir bulan.")
        assert _outcome(answer, _texts(), date(2026, 10, 26)) == "date"

    def test_before_the_span_opens_it_is_already_refused(self):
        """Holds on HEAD: the phrase is refused on the 12th, so only today's place in the month changes it."""
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan akhir bulan.")
        assert _outcome(answer, _texts("Rapat lanjutan belum dijadwalkan."), date(2026, 10, 12)) == "date"

    def test_a_source_date_inside_the_span_backs_it(self):
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan akhir bulan.")
        assert _outcome(answer, _texts("Rapat lanjutan digelar Rabu (28/10)."), date(2026, 10, 12)) == "kept"


# ── SYS-171: a weekday or a window ahead ───────────────────────────────────────────────────────────

WEEKDAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]


class TestSys171Weekday:
    @pytest.mark.parametrize("day", WEEKDAYS)
    @pytest.mark.parametrize("suffix", ["depan", "mendatang", "Mendatang"])
    def test_every_weekday_ahead_is_refused_unless_stated(self, day, suffix):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {day} {suffix}.")
        assert _outcome(answer, _texts()) == "date"
        other = "mendatang" if suffix == "depan" else "depan"
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {day.upper()} {other}.")) == "kept"

    @pytest.mark.parametrize("written,stated", [("Kamis depan", "Selasa depan"), ("Senin mendatang", "Sabtu mendatang"),
                                                ("Kamis depan", "pekan depan"), ("Kamis depan", "minggu mendatang"),
                                                ("hari Minggu depan", "pekan depan"), ("Jumat depan", "besok")])
    def test_another_time_ahead_does_not_back_it(self, written, stated):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "date"

    @pytest.mark.parametrize("written,stated", [("hari Minggu depan", "HARI MINGGU mendatang"),
                                                ("pada hari Kamis depan", "Kamis depan"),
                                                ("Kamis depan", "hari Kamis mendatang")])
    def test_hari_is_optional_and_case_free(self, written, stated):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "kept"

    @pytest.mark.parametrize("written,stated", [("Minggu depan", "Dilantik Pekan Depan"),
                                                ("pekan depan", "Pelantikan Digelar Minggu Depan"),
                                                ("Minggu Mendatang", "pekan depan")])
    def test_the_sunday_call_a_bare_minggu_depan_is_next_week_both_ways(self, written, stated):
        """The dev's call: a bare "Minggu depan" is next week, whatever its case (title-case headlines)."""
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(stated + ".")) == "kept"

    def test_the_sunday_call_a_hari_minggu_depan_needs_the_sunday(self):
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan Minggu depan.")
        assert _outcome(answer, _texts("Rapat lanjutan digelar hari Minggu depan.")) == "date"

    @pytest.mark.parametrize("text", ["Rapat digelar Kamis (22/10) mendatang.", "Pada hari Kamis, rapat digelar.",
                                      "Hari-hari ke depan berat.", "Ke depan, pemerintah menambah anggaran.",
                                      "Sabtu-Minggu lalu ramai."])
    def test_not_a_weekday_ahead(self, text):
        assert not any(k.startswith("hari ") for k in sc.future_times(text))

    def test_a_weekday_ahead_makes_a_scheduled_step(self):
        """SYS-166: the agenda has no date, digit or schedule word but the weekday ahead."""
        agenda = "Para ahli dipanggil Jumat mendatang."
        assert not sa._SCHEDULED.search(agenda)
        assert _outcome(_answer(agenda=agenda), _texts("Para ahli dipanggil Jumat depan.")) == "kept"

    def test_a_weekday_ahead_the_hari_ini_already_told_is_dropped_as_a_repeat(self):
        """SYS-163/165 read the same keys: "Kamis mendatang" in the agenda repeats "Kamis depan" in hari_ini."""
        hari_ini = ("Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara, Senin (12/10). "
                    "Rapat lanjutan karhutla digelar Kamis depan.")
        answer = _answer(hari_ini=hari_ini, agenda="Rapat lanjutan karhutla digelar Kamis mendatang.")
        assert _outcome(answer, _texts("Rapat lanjutan digelar Kamis depan.")) == "dropped"


class TestSys171WeekdayNextWeek:
    """The weekday written with "pekan/minggu depan": `_DAY_AHEAD` needs "depan" right after the weekday, so
    "Kamis pekan depan" reads as "pekan depan" alone and the weekday goes unchecked. The dev's comment: "a weekday
    never meets 'pekan depan' in either direction". 51 articles write "<hari> pekan/minggu depan"."""

    @pytest.mark.parametrize("written,stated", [("Kamis pekan depan", "pekan depan"),
                                                ("Senin minggu depan", "minggu depan"),
                                                ("hari Kamis pekan depan", "pekan depan"),
                                                ("Kamis pekan depan", "Selasa pekan depan"),
                                                ("Rabu pekan mendatang", "Senin depan")])
    def test_an_unstated_weekday_next_week_is_refused(self, written, stated):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "date"

    def test_a_stated_weekday_next_week_is_kept(self):
        """Holds on HEAD, and must keep holding."""
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan Kamis pekan depan.")
        assert _outcome(answer, _texts("Rapat lanjutan digelar Kamis pekan depan.")) == "kept"


class TestSys171Window:
    @pytest.mark.parametrize("written,stated", [("sepekan ke depan", "seminggu ke depan"),
                                                ("Seminggu Ke Depan", "sepekan ke depan"),
                                                ("dua minggu ke depan", "dua pekan ke depan"),
                                                ("sebulan ke depan", "sebulan ke depan"),
                                                ("3 hari ke depan", "3 hari ke depan"),
                                                ("beberapa bulan ke depan", "beberapa bulan ke depan")])
    def test_a_stated_window_backs_it(self, written, stated):
        answer = _answer(agenda=f"Keputusan karhutla akan diumumkan {written}.")
        assert _outcome(answer, _texts(f"Keputusan diumumkan {stated}.")) == "kept"

    @pytest.mark.parametrize("written,stated", [("dua pekan ke depan", "sepekan ke depan"),
                                                ("sebulan ke depan", "sepekan ke depan"),
                                                ("sepekan ke depan", "pekan depan"),
                                                ("setahun ke depan", "tahun depan")])
    def test_another_window_does_not_back_it(self, written, stated):
        answer = _answer(agenda=f"Keputusan karhutla akan diumumkan {written}.")
        assert _outcome(answer, _texts(f"Keputusan diumumkan {stated}.")) == "date"

    def test_a_window_in_the_latar_is_refused_unless_stated(self):
        answer = _answer(latar=LATAR + " Kabut asap diperkirakan bertahan dua minggu ke depan.")
        assert _outcome(answer, _texts()) == "date"


# ── SYS-172: change claims ─────────────────────────────────────────────────────────────────────────

class TestSys172:
    @pytest.mark.parametrize("claim", [
        "Kini jumlah personel yang dimutasi bertambah dari 88 orang pada telegram pertama ke 199 orang.",
        "Kini jumlahnya bertambah lagi, ke 199 orang.",
        "Kini jumlahnya naik, hingga mencapai 199 orang.",
        "Kini jumlahnya meningkat ke angka 199 orang.",
        "Kini jumlahnya membengkak sampai total 199 orang.",
        "KINI JUMLAHNYA BERTAMBAH KE 199 ORANG.",
    ])
    def test_more_ke_and_two_word_forms_are_claims_on_the_one_event_source(self, claim):
        assert sc.unbacked_changes(claim, POLRI) != []

    @pytest.mark.parametrize("text", [
        "Ribuan buruh turun ke jalan, 199 orang ditahan.",
        "Harga naik ke-199 kalinya.",
        "Harga naik sejak 1 Oktober ke 12 Oktober.",
        "Harga naik ke 12/10 lalu.",
        "Polisi menurunkan 199 personel ke lokasi.",
    ])
    def test_no_false_claim(self, text):
        assert sc.unbacked_changes(text, POLRI) == []

    @pytest.mark.parametrize("claim,source", [
        ("Rupiah melemah ke Rp17.930 per dolar AS.", "Rupiah ditutup melemah 0,2% ke level Rp17.930 per dolar AS."),
        ("Korban bertambah ke 199 orang.", "Hingga 12/10, korban tercatat 199 orang."),
        ("Pasien naik hingga mencapai 199 orang.", "Jumlah pasien sepanjang Oktober 199 orang."),
    ])
    def test_a_source_that_tells_the_change_or_a_running_total_backs_it(self, claim, source):
        assert sc.unbacked_changes(claim, source) == []

    def test_end_to_end_a_ke_claim_is_refused_as_number(self):
        texts = [TEXTS[0] + " Total ada 199 pejabat Polri yang dirotasi.", *TEXTS[1:]]
        answer = _answer(hari_ini="Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara, "
                                  "Senin (12/10). Pejabat yang dirotasi kini bertambah ke 199 orang.")
        assert _outcome(answer, texts) == "number"


class TestRunningPeriodWithAWeekday:
    """SYS-161's `_TOTAL_OR_CHANGE` reads a running period as "hingga / sampai / per" + a time word, a d/m date or a
    month; news writes it with the weekday first, "Hingga Senin (12/10)" (2,096 articles). Such a source does not
    back a true running-total claim, so the arc is refused and retried. SYS-172 widens the claims that reach it."""

    @pytest.mark.parametrize("claim", ["Korban bertambah menjadi 199 orang.", "Korban bertambah ke 199 orang."])
    @pytest.mark.parametrize("source", ["Hingga Senin (12/10), korban tercatat 199 orang.",
                                        "Korban tercatat 199 orang per Senin, 12/10.",
                                        "Sampai hari Senin (12/10/2026) korban tercatat 199 orang."])
    def test_a_weekday_dated_running_period_backs_the_claim(self, claim, source):
        assert sc.unbacked_changes(claim, source) == []


class TestChangeMencapai:
    """"<verb> mencapai N" with no to-word (43 articles: "naik mencapai 65,70 persen") is the same running-total
    claim as "naik hingga mencapai N". The dev noted it on #371 and left it."""

    @pytest.mark.parametrize("claim,written", [("Kini jumlahnya bertambah mencapai 199 orang.", "bertambah mencapai 199"),
                                               ("Kini jumlahnya naik mencapai total 199 orang.",
                                                "naik mencapai total 199")])
    def test_verb_mencapai_n_is_a_claim(self, claim, written):
        assert sc.unbacked_changes(claim, POLRI) == [written]


# ── SYS-173: parts of last week ────────────────────────────────────────────────────────────────────

# Last week seen from Mon 12/10, Wed 14/10 and Sun 18/10 is Mon 5/10 .. Sun 11/10 for all three.
DIGESTS = [date(2026, 10, 12), date(2026, 10, 14), date(2026, 10, 18)]
PARTS = {"awal": (5, 7), "pertengahan": (6, 8), "akhir": (8, 11)}


class TestSys173:
    @pytest.mark.parametrize("today", DIGESTS)
    @pytest.mark.parametrize("part", PARTS)
    @pytest.mark.parametrize("week", ["pekan", "minggu"])
    def test_each_part_spans_its_days_from_any_digest_day(self, today, part, week):
        first, last = PARTS[part]
        text = f"Rapat itu digelar {part} {week} lalu."
        assert sc.relative_times(text, today) == [(f"{part} {week} lalu", date(2026, 10, first), date(2026, 10, last))]

    @pytest.mark.parametrize("part", PARTS)
    def test_the_first_and_last_day_back_it_and_the_day_either_side_does_not(self, part):
        first, last = PARTS[part]
        text = f"Polri memutasi perwira {part} pekan lalu."
        for d in (first, last):
            assert sa.unbacked_times(text, DAY, {DAY, date(2026, 10, d)}, "") == [], d
        for d in (first - 1, last + 1):
            if 5 <= d <= 11:
                assert sa.unbacked_times(text, DAY, {DAY, date(2026, 10, d)}, "") != [], d

    def test_capitalised_at_a_sentence_start(self):
        assert sc.relative_times("Akhir pekan lalu, Polri memutasi perwira.", DAY) == [
            ("Akhir pekan lalu", date(2026, 10, 8), date(2026, 10, 11))]

    def test_this_weeks_items_never_back_last_weeks_part(self):
        """A Wednesday digest: Mon 12/10 is this week, not "awal pekan lalu"."""
        assert sa.unbacked_times("Polri memutasi perwira awal pekan lalu.", date(2026, 10, 14),
                                 {date(2026, 10, 14), date(2026, 10, 12)}, "") != []

    @pytest.mark.parametrize("item_day,expected", [(date(2026, 10, 11), "date"), (date(2026, 10, 6), "kept")])
    def test_end_to_end_a_sunday_item_does_not_back_awal_pekan_lalu(self, item_day, expected):
        item = TimelineItem(104, item_day, "CNBC", "Prabowo Rapat Karhutla Lagi", "Presiden rapat karhutla lagi.", 0.85, 12)
        timeline = [TIMELINE[0], TIMELINE[1], item]
        latar = ("Persoalan karhutla sudah di meja Presiden sejak September. Pada 23/9 Seskab melaporkan 209 hektare "
                 "lahan masih terbakar, dan awal pekan lalu Prabowo menggelar rapat lagi.")
        answer = _answer(latar=latar, alur=[3, 5])
        assert _outcome(answer, TEXTS, DAY, timeline) == expected
