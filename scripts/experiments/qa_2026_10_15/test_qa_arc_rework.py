"""QA 2026-10-15: QA's own tests for the rework of the arc guards (SYS-157/158 sent back, SYS-162/163/164,
DBT-77; tracker #336).

Written from each ticket's text with inputs the dev's tests do not use: counts the dev did not list,
a phrase stated in an article that is *not* terkait (or is moved out on the retry), records whose
times differ in one part only, an agenda that repeats hari_ini rather than the latar, a "sejak"
frame followed by real anchors, and the replay metrics on hand-counted records. Run:

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_15/test_qa_arc_rework.py -q -p no:cacheprovider

A failing test here is a finding, recorded in .10x/reviews/2026-10-15-qa-report.md.
"""
import json
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments"))

import newscrawler.core.story_arc as sa  # noqa: E402
from newscrawler.core import arc_style  # noqa: E402
from newscrawler.core.llm_json import Rejected  # noqa: E402
from newscrawler.core.source_check import ordinal_claims, relative_phrases, relative_times, stated_claims  # noqa: E402
from newscrawler.core.thread_finder import TimelineItem  # noqa: E402
from tests.unit.test_story_arc import DAY, N, TEXTS, TIMELINE, _answer  # noqa: E402

MON = date(2026, 10, 12)        # the dev's DAY, a Monday
FRAME = "Karhutla sudah lama di meja Presiden. "


def _parse(answer, texts=TEXTS, timeline=TIMELINE, lenient=False):
    return sa.parse(answer, texts, timeline, DAY, lenient=lenient)


def _reason(answer, **kw):
    with pytest.raises(Rejected) as e:
        _parse(answer, **kw)
    return e.value.reason, e.value.detail


def _with(i, extra):
    return [t + (" " + extra if k == i else "") for k, t in enumerate(TEXTS)]


def _span(phrase, today=MON):
    found = relative_times(phrase, today)
    assert len(found) == 1, found
    return found[0][1], found[0][2]


# ── SYS-157 rework: a count before a listed phrase ─────────────────────────────────────────────

class TestSys157CountAgo:
    @pytest.mark.parametrize("phrase,first,last", [
        ("lima pekan lalu", date(2026, 9, 4), date(2026, 9, 10)),          # 35 days back, +-3
        ("satu pekan lalu", date(2026, 10, 3), date(2026, 10, 7)),         # = sepekan lalu (5-9)
        ("sebelas hari lalu", date(2026, 9, 30), date(2026, 10, 2)),       # 11 +-1
        ("12 hari lalu", date(2026, 9, 29), date(2026, 10, 1)),
        ("satu bulan lalu", date(2026, 9, 1), date(2026, 9, 30)),
        ("Tiga Minggu lalu", date(2026, 9, 18), date(2026, 9, 24)),        # a count makes "Minggu" a week
        ("dua hari lalu", date(2026, 10, 9), date(2026, 10, 11)),
    ])
    def test_spans_the_dev_did_not_list(self, phrase, first, last):
        assert _span(phrase) == (first, last)

    def test_months_back_across_two_years(self):
        assert _span("tiga bulan lalu", date(2027, 2, 15)) == (date(2026, 11, 1), date(2026, 11, 30))
        assert _span("14 bulan lalu", date(2027, 2, 15)) == (date(2025, 12, 1), date(2025, 12, 31))

    @pytest.mark.parametrize("phrase", ["belasan hari lalu", "sekian bulan lalu", "puluhan hari lalu",
                                        "tiga belas hari lalu", "beberapa minggu lalu"])
    def test_a_vague_count_is_neither_read_nor_shortened(self, phrase):
        assert relative_times(phrase, MON) == []
        assert [p for _, p in relative_phrases(phrase)] == [phrase]

    def test_three_weeks_over_an_item_ten_days_back_is_refused(self):
        """The false-pass half of the send-back: 'tiga pekan lalu' must not be backed by last week's item."""
        assert sa.unbacked_times("Tiga pekan lalu Presiden melantik Wantimpres.", MON,
                                 {MON, date(2026, 10, 2)}, "") == ["Tiga pekan lalu"]
        assert sa.unbacked_times("Tiga pekan lalu Seskab melapor.", MON, {MON, date(2026, 9, 23)}, "") == []

    def test_two_phrases_in_one_sentence_are_both_read(self):
        found = relative_times("Dua pekan lalu banjir, kemarin surut.", MON)
        assert [p for p, *_ in found] == ["Dua pekan lalu", "kemarin"]


# ── SYS-162: only today's terkait articles state a relative phrase ─────────────────────────────

class TestSys162StatedToday:
    LATAR = FRAME + "Kemarin Seskab melaporkan 209 hektare lahan masih terbakar."

    def test_stated_in_a_tidak_terkait_article_does_not_license(self):
        """Article [2] (cabai) is tidak_terkait: its 'kemarin' was not chosen as today's story."""
        reason, detail = _reason(_answer(latar=self.LATAR), texts=_with(2, "Kemarin harga cabai naik."))
        assert reason == "date" and '"Kemarin"' in detail

    def test_stated_in_an_article_moved_out_on_the_retry_does_not_license(self):
        """On the retry the off-subject article [2] is moved out; its text must stop licensing too."""
        answer = _answer(latar=self.LATAR, terkait=[0, 1, 2], tidak_terkait=[])
        reason, detail = _reason(answer, texts=_with(2, "Kemarin harga cabai naik."), lenient=True)
        assert reason == "date" and '"Kemarin"' in detail

    def test_stated_in_a_terkait_article_licenses(self):
        assert _parse(_answer(latar=self.LATAR), texts=_with(1, "Kemarin asap makin tebal."))

    def test_a_date_stated_by_an_old_item_still_backs_the_phrase(self):
        """An item's own date is absolute, so 'akhir September' over the 23/9 item passes (unchanged)."""
        assert _parse(_answer(latar=FRAME + "Akhir September Seskab melaporkan 209 hektare lahan masih terbakar."))


# ── SYS-158 rework: whole-time records, series with "kali", collectives ────────────────────────

class TestSys158Records:
    @pytest.mark.parametrize("arc,source", [
        ("IHSG tertinggi sejak 2019.", "IHSG tertinggi sejak 2020."),
        ("IHSG terendah sejak akhir Agustus.", "IHSG terendah sejak awal Agustus."),
        ("IHSG terendah sejak 9/2.", "IHSG terendah sejak 9/1."),
        ("Rupiah terendah sejak Maret 2024.", "Rupiah terendah sejak Maret 2025."),
        ("Rupiah terendah sejak 10 Januari.", "Rupiah terendah sejak 9 Januari."),
        ("IHSG terendah sejak 9/1/2025.", "IHSG terendah sejak 9/1/2026."),
        ("Inflasi pertama kalinya sejak tahun lalu.", "Inflasi pertama kali sejak awal tahun."),
    ])
    def test_a_different_time_is_not_stated(self, arc, source):
        arc_keys = {k for _, _, k in ordinal_claims(arc)}
        assert arc_keys and not arc_keys & stated_claims(source)

    @pytest.mark.parametrize("arc,source", [
        ("IHSG terendah sejak awal tahun ini.", "IHSG terendah sejak awal tahun."),
        ("Rupiah terendah sejak Maret.", "Rupiah terendah sejak Maret 2026."),
        ("Inflasi pertama kalinya sejak 2019.", "Inflasi pertama kali sejak 2019."),
        ("Rupiah terendah sejak 9 Januari.", "Rupiah terendah sejak 9 Januari 2026."),
    ])
    def test_the_same_time_is_stated(self, arc, source):
        arc_keys = {k for _, _, k in ordinal_claims(arc)}
        assert arc_keys and arc_keys <= stated_claims(source)

    def test_in_parse_a_record_with_another_year_is_refused(self):
        latar = FRAME + "Luas lahan terbakar kali ini tertinggi sejak 2015."
        reason, detail = _reason(_answer(latar=latar), texts=_with(0, "Luas karhutla tertinggi sejak 2019."))
        assert reason == "number" and "tertinggi sejak 2015" in detail


class TestSys158SeriesAndCollectives:
    def test_two_times_in_a_row_needs_one_item(self):
        latar = FRAME + "Prabowo dua kali berturut-turut memimpin rapat karhutla."
        assert _reason(_answer(alur=[], latar=latar.replace(FRAME, "")))[0] in ("number", "date")
        assert _parse(_answer(alur=[N + 1], latar=latar))

    @pytest.mark.parametrize("text", ["Menko mengumpulkan kedua belah pihak.", "Presiden dikunjungi ketiga menteri.",
                                      "Polda bersama kelima tersangka ke lokasi.", "Jaksa memanggil keempat saksi."])
    def test_collective(self, text):
        assert ordinal_claims(text) == []

    @pytest.mark.parametrize("text,key", [("Pencairan termin kedua tertunda.", "termin 2"),
                                          ("Menteri kedua yang diperiksa.", "menteri 2"),
                                          ("Debat kedua capres digelar.", "debat 2"),
                                          ("BI menahan bunga lima kali beruntun.", "beruntun kali 5")])
    def test_still_a_claim(self, text, key):
        assert key in {k for _, _, k in ordinal_claims(text)}

    def test_the_fixed_fixture_of_qa_1014(self):
        """QA 10-14's test put 'Istana Negara' in hari_ini, which article [1] does not name (the dev was
        right on #353). The same case, on its own texts, where both articles name the story."""
        texts = [sa.guard_text({"source": "DETIK", "headline": "Polisi Tahan Dua Tersangka Karhutla Ogan Ilir",
                                "l1_text": "Polisi menahan dua tersangka karhutla di Ogan Ilir, Senin (12/10/2026)."}),
                 sa.guard_text({"source": "KOMPAS", "headline": "Dua Tersangka Karhutla Ogan Ilir Ditahan",
                                "l1_text": "Dua tersangka karhutla di Ogan Ilir ditahan polisi."})]
        answer = json.dumps({"judul": "Polisi tahan dua tersangka karhutla Ogan Ilir",
                             "hari_ini": "Polisi menahan kedua tersangka karhutla di Ogan Ilir, Senin (12/10).",
                             "latar": "", "agenda": "", "sekilas": "Polisi menahan dua tersangka karhutla Ogan Ilir.",
                             "terkait": [0, 1], "tidak_terkait": [], "alur": []})
        assert sa.parse(answer, texts, TIMELINE, DAY)


# ── SYS-163: an agenda that repeats ─────────────────────────────────────────────────────────────

class TestSys163AgendaRepeats:
    def test_repeating_hari_ini_not_the_latar_is_dropped(self):
        hari_ini = "Prabowo memimpin rapat karhutla, Senin (12/10). Rapat lanjutan dijadwalkan Kamis (15/10) di Istana."
        assert sa.agenda_repeats("Rapat lanjutan dijadwalkan Kamis (15/10) di Istana.", "Karhutla meluas.", hari_ini)

    def test_the_same_date_written_another_way_is_still_a_repeat(self):
        latar = "Prabowo dijadwalkan menerima El-Sisi di Istana Kepresidenan, Minggu (11/10) pukul 10.30 WIB."
        assert sa.agenda_repeats("Prabowo menerima El-Sisi di Istana Kepresidenan pada 11 Oktober pukul 10.30 WIB.",
                                 latar, "")

    def test_exactly_half_the_words_is_a_repeat(self):
        """AGENDA_REPEAT_SHARE is 'at least': 2 of 4 content words (rapat, karhutla) + the shared date."""
        assert sa.agenda_repeats("Kapolri memanggil rapat karhutla, Kamis (15/10).",
                                 "Prabowo menggelar rapat karhutla lanjutan Kamis (15/10).", "")

    def test_a_new_step_on_a_date_already_told_is_kept(self):
        assert not sa.agenda_repeats("DPR memanggil Kapolri dan Kepala BNPB soal anggaran pemadaman, Kamis (15/10).",
                                     "Prabowo menggelar rapat lanjutan Kamis (15/10).", "")

    def test_bpgmn_repeat_in_relative_time_is_dropped(self):
        """New ticket (SYS-165), not a SYS-163 send-back: v5 10-12's agenda repeats hari_ini's last sentence
        (6 of 7 content words) with "minggu depan" instead of a date, so SYS-163's shared-date gate keeps it."""
        hari_ini = ("Presiden Prabowo Subianto memimpin rapat terbatas soal kebakaran hutan dan lahan di Istana "
                    "Kepresidenan Jakarta, Senin (12/10). Menko Polkam Dudung Abdurachman menyebut pelantikan pimpinan "
                    "Badan Pengelola Gambut dan Mangrove Nasional diharapkan minggu depan.")
        latar = "Kini Dudung menyebut Satyawan Puryatmoko, Dirjen KSDAE Kementerian Kehutanan, sebagai calon Ketua BPGMN."
        assert sa.agenda_repeats("Pelantikan pimpinan BPGMN diharapkan dilakukan minggu depan menurut Dudung.",
                                 latar, hari_ini)

    def test_a_dropped_agenda_is_not_checked(self):
        """A dropped agenda's unsupported number must not refuse the arc: it is no longer printed."""
        hari_ini = ("Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara, Senin (12/10). "
                    "Kebakaran mengganggu 1.673 penerbangan domestik. Rapat lanjutan dijadwalkan Kamis (15/10).")
        arc = _parse(_answer(hari_ini=hari_ini, agenda="Rapat lanjutan karhutla dijadwalkan Kamis (15/10) pukul 99.99."))
        assert arc.agenda == "" and arc.agenda_dropped


# ── SYS-164: time anchors ───────────────────────────────────────────────────────────────────────

class TestSys164Anchors:
    def test_a_sejak_frame_does_not_hide_the_anchors_after_it(self):
        latar = ("Sejak September karhutla meluas. Pekan lalu Seskab melapor, 5/10 rapat digelar, "
                 "dan kemarin asap sampai Malaysia.")
        assert arc_style.time_anchors(latar) == ["Pekan lalu", "5/10", "kemarin"]

    @pytest.mark.parametrize("frame", ["Sejak September, Polri sudah dua kali merombak jabatan Kapolda.",
                                       "Sejak Agustus 2026, Polri sudah dua kali merombak jabatan Kapolda."])
    def test_a_sejak_month_frame_is_not_an_anchor_and_still_ties(self, frame):
        """"sejak <bulan>" is itself a table phrase that *starts* with sejak: the ticket and prompt rule 4 say it
        is not counted. Before SYS-164 this frame was tied (no calendar date); now the tie refuses it."""
        assert arc_style.time_anchors(frame) == []
        assert not arc_style.opens_on_time(frame)
        assert arc_style.tied_to_today(frame, "Polri mutasi Kakorlantas", "Polri memutasi 199 perwira, Minggu (11/10).")

    def test_four_anchors_are_refused_three_pass(self):
        four = (FRAME + "Seskab melapor pekan lalu, rapat digelar 5/10, asap meluas 8/10, dan kemarin sampai Malaysia.")
        three = FRAME + "Seskab melapor pekan lalu, rapat digelar 5/10, dan kemarin asap sampai Malaysia."
        assert any("penanda waktu" in p for p in sa.chronicle(four, "Karhutla", "Karhutla meluas.", True))
        assert not any("penanda waktu" in p for p in sa.chronicle(three, "Karhutla", "Karhutla meluas.", True))

    @pytest.mark.parametrize("opening", ["Kemarin, Polri memutasi 88 perwira.", "Dua pekan lalu, Polri memutasi 88 perwira.",
                                         "Pada awal Oktober, Polri memutasi 88 perwira.",
                                         "Sebelumnya, pekan lalu Polri memutasi 88 perwira."])
    def test_held_out_relative_openings(self, opening):
        assert arc_style.opens_on_time(opening)
        assert not arc_style.tied_to_today(opening, "Polri mutasi Kakorlantas", "Polri memutasi 199 perwira.")

    def test_a_relative_opening_and_a_date_opening_are_two(self):
        latar = "Karhutla meluas sejak September. Pekan lalu, Seskab melapor 209 hektare. Pada 8/10, asap ke Malaysia."
        assert any("dibuka dengan tanggal atau waktu" in p for p in sa.chronicle(latar, "Karhutla", "Karhutla.", True))

    @pytest.mark.parametrize("sentence,led", [("Polri memutasi 88 perwira pada 3/10.", True),
                                              ("Polri memutasi 88 perwira pekan lalu.", False),
                                              ("Pekan lalu, Polri memutasi 88 perwira.", True)])
    def test_time_led_keeps_date_leds_mid_sentence_pada(self, sentence, led):
        """time_led = date_led (incl. "pada <date>" anywhere) or a time opening (dev comment on #359, Bulog)."""
        assert arc_style.time_led(sentence) is led

    def test_metrics_on_hand_counted_records(self):
        from replay_story_arcs import style_metrics
        records = [
            {"back": "Karhutla meluas sejak awal Oktober. Pekan lalu, Seskab melapor. Kemarin asap ke Malaysia.",
             "judul": "Karhutla", "hari_ini": "Karhutla meluas.", "alur": [1]},
            {"back": "Rupiah melemah. Pada 3/10, BI intervensi. Akhir September, cadangan turun. Kemarin, BI rapat.",
             "judul": "Rupiah", "hari_ini": "Rupiah melemah.", "alur": [1]},
        ]
        m = style_metrics(records)
        # rec 1: 3 sentences, time-led: "Pekan lalu," only (Kemarin is mid? no: opens) -> "Pekan lalu," + "Kemarin" = 2
        # rec 2: 4 sentences, time-led: "Pada 3/10", "Akhir September", "Kemarin" = 3; date-led: "Pada 3/10" = 1
        assert (m["sentences"], m["time_led"], m["date_led"]) == (7, 5, 1)
        # anchors: rec 1 = Pekan lalu, Kemarin (sejak frame not counted) = 2; rec 2 = 3/10, Akhir September, Kemarin = 3
        assert (m["anchors_max"], m["with_3_anchors_or_more"]) == (3, 1)
