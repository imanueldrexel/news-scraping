"""QA 2026-10-16 (late): QA's own tests for the SYS-171 rework, SYS-174, SYS-175 and SYS-176 (tracker #336).

Written from each ticket's text and the dev's comment, with inputs the dev's tests do not use:
- SYS-171: every weekday x pekan/minggu x depan/mendatang, the "pekan ini" extension, the Sunday, the dev's key call
  ("Kamis pekan depan" is not "Kamis depan"), the week a stated weekday implies (one way only), SYS-166's scheduled
  step and SYS-163's repeat through the new key, and the past "Kamis pekan lalu" untouched;
- SYS-174: every day a month part runs, each field, today / a past source date / a future source date / a chosen
  item as backing, the last day of each span, "sejak <bulan>", and the replay's true latar shape;
- SYS-175: every change verb adjacent to "mencapai", the words before N, the gap and date exclusions, end to end;
- SYS-176: each weekday, "hari", comma/paren/long date, each period word, a bare weekday, end to end.

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_16_late/test_qa_1016_late.py -q -p no:cacheprovider

A failing test here is a finding, recorded in .10x/reviews/2026-10-16-qa-report-late.md and ticketed:
- TestSys174LastDayOfTheSpan: SYS-174 #373, sent back (the agenda on the day a span ends);
- TestRunningSpanPastSourceDate: SYS-177 (a past date a source states backs a running span outside the agenda);
- TestBareYearAndWeekEnd: SYS-178 (bare "akhir tahun" / "akhir pekan" are read by neither table);
- TestNarrowedFuturePart: SYS-179 ("awal / pertengahan pekan depan" keyed as "pekan depan").
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
from tests.unit.test_story_arc import DAY, FRAME, TEXTS, TIMELINE, _answer  # noqa: E402
from tests.unit.test_source_check import POLRI  # noqa: E402

KAMIS_LINE = "Rapat lanjutan dijadwalkan Kamis (15/10)."
assert KAMIS_LINE in TEXTS[0]
NONE = "Rapat lanjutan belum dijadwalkan."
HARI_INI = "Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara. "
LATAR = FRAME + "Pada 23/9 Seskab melaporkan 209 hektare lahan masih terbakar."
# The second chosen item re-dated to 2/10, so "awal Oktober" in a latar is a true past reading it backs.
EARLY_OCT = [TIMELINE[0], TIMELINE[1]._replace(day=date(2026, 10, 2))]
EARLY_OCT_LATAR = ("Persoalan karhutla sudah di meja Presiden sejak September, dan awal Oktober Presiden menggelar "
                   "rapat terbatas soal karhutla.")


def _texts(sentence=NONE):
    """TEXTS with article [0]'s only next step ("Kamis (15/10)") replaced by `sentence`."""
    return [TEXTS[0].replace(KAMIS_LINE, sentence), *TEXTS[1:]]


def _outcome(answer, texts=None, day=DAY, timeline=TIMELINE):
    """'kept' / 'dropped' (agenda emptied) / the refusal reason."""
    texts = _texts() if texts is None else texts
    try:
        arc = sa.parse(answer, texts, timeline, day)
    except Rejected as e:
        return e.reason
    return "kept" if json.loads(answer).get("agenda", "") == arc.agenda else "dropped"


def _field(field, value, **extra):
    """An answer whose `field` is `value`; the agenda is emptied unless it is the field (its 15/10 is no known day
    once the fixture's next step is replaced)."""
    data = {"agenda": ""}
    data.update(extra)
    if field == "hari_ini":
        value = HARI_INI + value
    elif field == "latar":
        value = LATAR + " " + value
    data[field] = value
    return _answer(**data)


# ── SYS-171 rework: a weekday of a named week ──────────────────────────────────────────────────────

DAYS6 = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]


class TestSys171WeekdayOfAWeek:
    @pytest.mark.parametrize("day", DAYS6 + ["Minggu"])
    @pytest.mark.parametrize("week", ["pekan depan", "minggu depan", "pekan mendatang", "Minggu Mendatang"])
    def test_every_weekday_of_next_week_is_refused_on_the_week_alone(self, day, week):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {day} {week}.")
        assert _outcome(answer, _texts("Rapat lanjutan digelar pekan depan.")) == "date"

    @pytest.mark.parametrize("written,stated", [("Kamis pekan depan", "KAMIS MINGGU MENDATANG"),
                                                ("hari Jumat minggu depan", "Jumat pekan depan"),
                                                ("Minggu pekan depan", "hari Minggu minggu depan"),
                                                ("Sabtu pekan mendatang", "sabtu pekan depan")])
    def test_the_same_weekday_backs_it_through_synonyms_and_case(self, written, stated):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "kept"

    @pytest.mark.parametrize("written,stated", [("Kamis pekan depan", "Jumat pekan depan"),
                                                ("Kamis pekan depan", "Kamis pekan ini"),
                                                ("Kamis pekan ini", "Kamis pekan depan"),
                                                ("Minggu pekan depan", "Senin pekan depan")])
    def test_another_weekday_or_week_does_not_back_it(self, written, stated):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "date"

    @pytest.mark.parametrize("written,stated", [("Kamis pekan depan", "Kamis depan"), ("Kamis depan", "Kamis pekan depan"),
                                                ("Minggu pekan depan", "hari Minggu depan")])
    def test_the_dev_call_a_weekday_of_next_week_is_not_a_weekday_ahead(self, written, stated):
        """Recorded on #370: from a Monday "Kamis depan" may be this week's Thursday. Both ways a retry."""
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "date"

    @pytest.mark.parametrize("written,stated", [("pekan depan", "Rabu pekan depan"), ("minggu mendatang", "Rabu minggu depan"),
                                                ("pekan ini", "Rabu pekan ini")])
    def test_a_stated_weekday_of_a_week_states_the_week(self, written, stated):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "kept"

    @pytest.mark.parametrize("written,stated", [("pekan depan", "Rabu pekan ini"), ("pekan ini", "Rabu pekan depan"),
                                                ("Rabu depan", "Rabu pekan depan")])
    def test_the_implied_week_is_that_week_only(self, written, stated):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "date"

    @pytest.mark.parametrize("field", ["hari_ini", "latar", "sekilas"])
    def test_every_prose_field(self, field):
        answer = _field(field, "Rapat lanjutan karhutla digelar Kamis pekan depan.")
        assert _outcome(answer, _texts("Rapat lanjutan digelar pekan depan.")) == "date"

    def test_a_weekday_of_a_week_makes_a_scheduled_step(self):
        agenda = "Para ahli dipanggil Jumat pekan depan."
        assert not sa._SCHEDULED.search(agenda)
        assert _outcome(_answer(agenda=agenda), _texts("Para ahli dipanggil Jumat minggu depan.")) == "kept"

    def test_the_hari_ini_already_told_it_so_the_agenda_is_dropped(self):
        hari_ini = HARI_INI + "Rapat lanjutan karhutla digelar Kamis pekan depan."
        answer = _answer(hari_ini=hari_ini, agenda="Rapat lanjutan karhutla digelar Kamis minggu mendatang.")
        assert _outcome(answer, _texts("Rapat lanjutan digelar Kamis pekan depan.")) == "dropped"

    @pytest.mark.parametrize("text", ["Rapat digelar Kamis pekan lalu.", "Rapat digelar Kamis (22/10) pekan depan.",
                                      "Senin-Jumat pekan lalu ramai."])
    def test_not_a_weekday_of_a_week_ahead(self, text):
        assert not any(k.startswith("hari ") for k in sc.future_times(text))

    def test_the_past_weekday_of_last_week_is_still_a_relative_span(self):
        assert sc.relative_times("Rapat digelar Kamis pekan lalu.", DAY) == [("Kamis pekan lalu", date(2026, 10, 8),
                                                                              date(2026, 10, 8))]


# ── SYS-174: today does not back a running span ───────────────────────────────────────────────────

class TestSys174Today:
    @pytest.mark.parametrize("d", range(21, 31))
    @pytest.mark.parametrize("field", ["agenda", "hari_ini", "latar", "sekilas"])
    def test_today_alone_never_backs_akhir_bulan_while_it_runs(self, d, field):
        answer = _field(field, "Aturan karhutla dijadwalkan terbit akhir bulan.")
        assert _outcome(answer, _texts(), date(2026, 10, d)) == "date"

    @pytest.mark.parametrize("phrase,d", [("pertengahan bulan", 11), ("pertengahan bulan ini", 19),
                                          ("awal bulan", 1), ("awal November", 5), ("akhir Desember", 21)])
    def test_every_part_while_it_runs(self, phrase, d):
        month = 11 if "November" in phrase else 12 if "Desember" in phrase else 10
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {phrase}.")
        assert _outcome(answer, _texts(), date(2026, month, d)) == "date"

    @pytest.mark.parametrize("src", ["Rapat lanjutan digelar Kamis (29/10).", "Rapat lanjutan digelar 29 Oktober."])
    def test_in_the_agenda_a_day_ahead_a_source_states_backs_it(self, src):
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan akhir bulan.")
        assert _outcome(answer, _texts(src), date(2026, 10, 26)) == "kept"

    @pytest.mark.parametrize("src", ["Asap meluas sejak Kamis (22/10).", "Asap meluas sejak Minggu (25/10)."])
    def test_in_the_agenda_a_past_day_a_source_states_does_not(self, src):
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan akhir bulan.")
        assert _outcome(answer, _texts(NONE + " " + src), date(2026, 10, 26)) == "date"

    def test_in_the_agenda_a_chosen_item_inside_the_span_does_not(self):
        timeline = [*TIMELINE[:1], TIMELINE[1]._replace(day=date(2026, 10, 22))]
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan akhir bulan.",
                         latar=FRAME + "Pada 23/9 Seskab melaporkan 209 hektare lahan masih terbakar.")
        assert _outcome(answer, _texts(), date(2026, 10, 26), timeline) == "date"

    def test_the_replay_shape_a_chosen_item_backs_a_past_running_part_in_the_latar(self):
        """arcs-v4 8/10: "Sebelumnya, pada awal Oktober, Polri memutasi 88 perwira" backed by a 2/10 item."""
        answer = _answer(latar=EARLY_OCT_LATAR, agenda="")
        assert _outcome(answer, _texts(), date(2026, 10, 8), EARLY_OCT) == "kept"

    @pytest.mark.parametrize("d", [12, 25])
    def test_an_ended_span_is_judged_as_before(self, d):
        """"awal Oktober" on 12/10 or 25/10: ended, so the chosen 2/10 item backs it and nothing else needs to."""
        answer = _answer(latar=EARLY_OCT_LATAR, agenda="")
        assert _outcome(answer, _texts(), date(2026, 10, d), EARLY_OCT) == "kept"

    @pytest.mark.parametrize("d", [1, 12, 31])
    def test_sejak_this_month_is_backed_by_today_and_never_a_schedule(self, d):
        assert sc.relative_times("sejak Oktober", date(2026, 10, d)) == [("sejak Oktober", date(2026, 10, 1),
                                                                          date(2026, 10, d))]
        assert sa.unbacked_times("Asap bertahan sejak Oktober.", date(2026, 10, d), {date(2026, 10, d)}, "", True) == []

    def test_sejak_a_past_month_is_still_that_whole_month(self):
        assert sc.relative_times("sejak September", DAY) == [("sejak September", date(2026, 9, 1), date(2026, 9, 30))]


class TestSys174LastDayOfTheSpan:
    """The dev's rule reads a span that ends today as ended, so today backs it. In the agenda an invented
    "dijadwalkan akhir bulan" is then printed on the 30th/31st, "pertengahan bulan ini" on the 20th, "awal bulan" on
    the 10th: the SYS-174 symptom on the last day of each span, 3 days a month. The dev's comment: "The agenda is
    closed". Outside the agenda a span ending today stays backed by today (the past reading)."""

    @pytest.mark.parametrize("phrase,day", [("akhir bulan", date(2026, 10, 31)), ("akhir Oktober", date(2026, 10, 31)),
                                            ("akhir bulan", date(2026, 11, 30)),
                                            ("pertengahan bulan ini", date(2026, 10, 20)),
                                            ("pertengahan Oktober", date(2026, 10, 20)),
                                            ("awal bulan", date(2026, 10, 10))])
    def test_an_invented_agenda_schedule_on_the_spans_last_day_is_refused(self, phrase, day):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {phrase}.")
        assert _outcome(answer, _texts(), day) == "date"

    def test_the_day_before_is_already_refused(self):
        """Holds on HEAD."""
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan akhir bulan.")
        assert _outcome(answer, _texts(), date(2026, 10, 30)) == "date"

    def test_outside_the_agenda_today_still_backs_a_span_ending_today(self):
        """Holds on HEAD, and must keep holding: on 20/10 "pertengahan Oktober" in the hari_ini is today."""
        answer = _field("hari_ini", "Rapat digelar pertengahan Oktober.")
        assert _outcome(answer, _texts(), date(2026, 10, 20)) == "kept"


class TestRunningSpanPastSourceDate:
    """Outside the agenda a past day inside a running span still backs it, and `parse` counts every date today's
    `terkait` articles state. On 26/10 a source's "Minggu (25/10)" backs an invented "Aturan barunya terbit akhir
    bulan." in the hari_ini, the sekilas or the latar, while "akhir bulan ini" in the same sentence is refused.
    Corpus (probe_running_span_backing.py): 13.4% of articles posted 22-30/9 state a past date inside "akhir
    September" in their opening, so ~25% of 2-article and ~35% of 3-article arcs; 10-14% inside "pertengahan"."""

    @pytest.mark.parametrize("field", ["hari_ini", "sekilas"])
    @pytest.mark.parametrize("src", ["Asap meluas sejak Minggu (25/10).", "Asap meluas sejak Kamis (22/10)."])
    def test_a_past_source_date_does_not_back_a_running_schedule_outside_the_latar(self, field, src):
        value = "Aturan karhutla terbit akhir bulan." if field == "sekilas" else "Aturan barunya terbit akhir bulan."
        answer = _field(field, value)
        assert _outcome(answer, _texts(NONE + " " + src), date(2026, 10, 26)) == "date"

    @pytest.mark.parametrize("cue", ["akan terbit", "dijadwalkan terbit", "ditargetkan rampung", "menyusul"])
    def test_in_the_latar_a_future_verb_before_a_running_part_makes_it_a_schedule(self, cue):
        answer = _field("latar", f"Aturan barunya {cue} akhir Oktober.")
        assert _outcome(answer, _texts(NONE + " Asap meluas sejak Kamis (22/10)."), date(2026, 10, 26)) == "date"

    def test_the_replay_latar_shapes_stay_backed(self):
        """All 6 replay running spans (arcs-v4/v5, 8-9/10) are latar past narration; one has an 'akan' after the
        phrase about something else. A rule must keep them."""
        latar = ("Persoalan karhutla sudah di meja Presiden sejak September. Sebelumnya, pada awal Oktober, Presiden "
                 "menggelar rapat terbatas soal karhutla yang akan memanggil para ahli.")
        assert _outcome(_answer(latar=latar, agenda=""), _texts(), date(2026, 10, 8), EARLY_OCT) == "kept"


# ── Neither table: bare "akhir tahun" / "akhir pekan" ──────────────────────────────────────────────

class TestBareYearAndWeekEnd:
    """`_FUTURE` reads "akhir tahun" / "akhir pekan" only with ini/depan/mendatang, `_RELATIVE` only "akhir pekan
    lalu"; the bare forms are read by neither, so an invented one is printed in any field. Corpus: 141 articles
    write a future verb + bare "akhir tahun" ("ditargetkan rampung akhir tahun"), 21 bare "akhir pekan"."""

    @pytest.mark.parametrize("phrase", ["akhir tahun", "akhir pekan", "Akhir Tahun"])
    @pytest.mark.parametrize("field", ["agenda", "hari_ini", "sekilas"])
    def test_an_invented_bare_one_is_refused(self, phrase, field):
        answer = _field(field, f"Aturan karhutla akan rampung {phrase}.")
        assert _outcome(answer) == "date"

    @pytest.mark.parametrize("phrase", ["akhir tahun", "akhir pekan"])
    def test_a_stated_one_backs_it(self, phrase):
        """Holds on HEAD (nothing is checked), and must keep holding."""
        answer = _answer(agenda=f"Aturan karhutla akan rampung {phrase}.")
        assert _outcome(answer, _texts(f"Aturan akan rampung {phrase}.")) == "kept"

    def test_akhir_pekan_lalu_stays_the_past_span(self):
        """Holds on HEAD: SYS-173's span, never a future time."""
        assert not sc.future_phrases("Rupiah melemah akhir pekan lalu.")
        assert sc.relative_times("Rupiah melemah akhir pekan lalu.", DAY)[0][0] == "akhir pekan lalu"


# ── The parts of a future period ───────────────────────────────────────────────────────────────────

class TestNarrowedFuturePart:
    """`_FUTURE` reads only "akhir" as a part: "awal / pertengahan pekan depan" keys as "pekan depan", so an article's
    "pekan depan" backs a model's invented "awal pekan depan" (55 articles write the form). "akhir pekan depan" is
    keyed apart and refused (last test, holds on HEAD)."""

    @pytest.mark.parametrize("written,stated", [("awal pekan depan", "pekan depan"),
                                                ("pertengahan pekan depan", "minggu depan"),
                                                ("awal bulan depan", "bulan depan"),
                                                ("awal tahun depan", "tahun depan")])
    def test_a_narrowed_part_is_not_backed_by_the_whole_period(self, written, stated):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "date"

    @pytest.mark.parametrize("written,stated", [("awal pekan depan", "awal minggu depan"), ("pekan depan", "awal pekan depan")])
    def test_the_same_part_or_the_whole_backed_by_its_part(self, written, stated):
        answer = _answer(agenda=f"Rapat lanjutan karhutla dijadwalkan {written}.")
        assert _outcome(answer, _texts(f"Rapat lanjutan digelar {stated}.")) == "kept"

    def test_akhir_is_already_keyed_apart(self):
        answer = _answer(agenda="Rapat lanjutan karhutla dijadwalkan akhir pekan depan.")
        assert _outcome(answer, _texts("Rapat lanjutan digelar pekan depan.")) == "date"


# ── SYS-175: "<verb> mencapai N" ───────────────────────────────────────────────────────────────────

VERBS = ["bertambah", "naik", "meningkat", "turun", "berkurang", "menurun", "melonjak", "anjlok"]


class TestSys175:
    @pytest.mark.parametrize("verb", VERBS)
    def test_every_change_verb_adjacent_to_mencapai_is_a_claim(self, verb):
        assert sc.unbacked_changes(f"Kini jumlahnya {verb} mencapai 199 orang.", POLRI) == [f"{verb} mencapai 199"]

    @pytest.mark.parametrize("claim", ["Kini jumlahnya naik, mencapai 199 orang.", "KINI JUMLAHNYA NAIK MENCAPAI 199 ORANG.",
                                       "Kini jumlahnya naik mencapai sekitar 199 orang.",
                                       "Kini jumlahnya naik mencapai lebih dari 199 orang.",
                                       "Kini jumlahnya bertambah   mencapai 199 orang."])
    def test_comma_case_spacing_and_the_words_before_n(self, claim):
        assert sc.unbacked_changes(claim, POLRI) != []

    @pytest.mark.parametrize("text", ["Jumlahnya mencapai 199 orang.", "Kenaikan mencapai 199 orang.",
                                      "Harga turun 5 persen dari bulan lalu yang mencapai 199 ribu.",
                                      "Harga naik mencapai 12/10 lalu.", "Harga naik mencapai 12 Oktober."])
    def test_no_false_claim(self, text):
        assert sc.unbacked_changes(text, POLRI) == []

    @pytest.mark.parametrize("source", ["Korban bertambah mencapai 199 orang.", "Hingga 12/10 korban mencapai 199 orang.",
                                        "Korban bertambah dari 88 menjadi 199 orang."])
    def test_a_source_that_tells_the_change_backs_it(self, source):
        assert sc.unbacked_changes("Kini korban bertambah mencapai 199 orang.", source) == []

    def test_end_to_end_refused_as_number(self):
        texts = [TEXTS[0] + " Total ada 199 pejabat Polri yang dirotasi.", *TEXTS[1:]]
        answer = _answer(hari_ini=HARI_INI.rstrip(". ") + ", Senin (12/10). Pejabat yang dirotasi kini bertambah "
                                                          "mencapai 199 orang.")
        assert _outcome(answer, texts) == "number"


# ── SYS-176: a running period dated by weekday ─────────────────────────────────────────────────────

class TestSys176:
    @pytest.mark.parametrize("source", [
        "Hingga Minggu (11/10), korban tercatat 199 orang.",
        "hingga hari Selasa (13/10) korban tercatat 199 orang.",
        "Per Jumat, 9/10, korban tercatat 199 orang.",
        "Sampai Rabu 14 Oktober 2026, korban tercatat 199 orang.",
        "Sejak Senin (12/10), korban tercatat 199 orang.",
        "HINGGA SENIN (12/10) KORBAN TERCATAT 199 ORANG.",
    ])
    def test_a_weekday_before_the_date_is_a_running_period(self, source):
        assert sc.unbacked_changes("Korban bertambah menjadi 199 orang.", source) == []

    @pytest.mark.parametrize("source", ["Kegiatan berlangsung Jumat hingga Senin, 199 orang hadir.",
                                        "Hingga Senin, 199 orang hadir.", "Pada Senin (12/10), 199 orang hadir."])
    def test_a_weekday_without_a_date_or_without_a_period_word_is_not(self, source):
        assert sc.unbacked_changes("Korban bertambah menjadi 199 orang.", source) != []

    def test_end_to_end_the_true_claim_is_kept(self):
        texts = [TEXTS[0] + " Hingga Senin (12/10), korban asap tercatat 199 orang.", *TEXTS[1:]]
        answer = _answer(hari_ini=HARI_INI.rstrip(". ") + ", Senin (12/10). Korban asap bertambah menjadi 199 orang.")
        assert _outcome(answer, texts) == "kept"
