"""QA 2026-10-16: QA's own tests for SYS-164 (rework), SYS-165, SYS-166 and DBT-78 (tracker #336).

Written from each ticket's text with inputs the dev's tests do not use: frames the rework's two
regexes do not name ("Sejak Sabtu lalu", "Sejak dua pekan lalu", a modifier between "sejak" and
the phrase), openings with a modifier before the table phrase ("Senin pekan lalu, ..."), the
synonyms of the future times Indonesian news writes most ("pekan mendatang", "esok", "akhir tahun
ini"), a future time told in the latar, the "akhir pekan ini" / "pekan ini" split, and an agenda
whose future time no source states, end to end through `parse`. Run:

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_16/test_qa_1016.py -q -p no:cacheprovider

A failing test here is a finding, recorded in .10x/reviews/2026-10-16-qa-report.md and ticketed
(SYS-167 openings/frames with a modifier, SYS-168 future-time synonyms, SYS-169 unstated future time).
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import newscrawler.core.story_arc as sa  # noqa: E402
from newscrawler.core import arc_style  # noqa: E402
from newscrawler.core.llm_json import Rejected  # noqa: E402
from tests.unit.test_story_arc import DAY, TEXTS, TIMELINE, _answer  # noqa: E402

JUDUL, HARI_INI = "Polri mutasi Kakorlantas", "Polri memutasi 199 perwira, Minggu (11/10)."
FRAME = "Karhutla sudah lama di meja Presiden. "


# ── SYS-164 rework: "sejak" frames ──────────────────────────────────────────────────────────────

class TestSys164SejakFrames:
    @pytest.mark.parametrize("frame", [
        "Sejak Sabtu lalu, Polri sudah dua kali merombak jabatan Kapolda.",
        "Sejak kemarin, Polri sudah dua kali merombak jabatan Kapolda.",
        "Sejak dua pekan lalu, Polri sudah dua kali merombak jabatan Kapolda.",
        "Sejak akhir bulan lalu, Polri sudah dua kali merombak jabatan Kapolda.",
        "SEJAK SEPTEMBER, Polri sudah dua kali merombak jabatan Kapolda.",
        "Sejak  September 2026, Polri sudah dua kali merombak jabatan Kapolda.",
        "Sejak September lalu, Polri sudah dua kali merombak jabatan Kapolda.",
    ])
    def test_held_out_sejak_frames_are_not_anchors_and_tie(self, frame):
        assert arc_style.time_anchors(frame) == []
        assert not arc_style.opens_on_time(frame)
        assert arc_style.tied_to_today(frame, JUDUL, HARI_INI)

    def test_frame_then_three_turning_points_fits_the_cap(self):
        """Prompt rule 4: at most three time anchors, "sejak ..." not counted -- a frame plus three passes."""
        latar = ("Polri merombak jabatan sejak September. Pekan lalu 88 perwira dimutasi, 5/10 Kapolda diganti, "
                 "dan kemarin Kakorlantas dilantik.")
        assert len(arc_style.time_anchors(latar)) == 3
        assert not any("penanda waktu" in p for p in sa.chronicle(latar, JUDUL, HARI_INI, True))

    def test_a_date_after_sejak_opening_still_refuses_the_tie(self):
        """Not a regression: "Sejak 15/9, ..." opened on a date before SYS-164 too (_OPENS_ON_DATE takes sejak)."""
        assert not arc_style.tied_to_today("Sejak 15/9, Polri merombak jabatan Kapolda.", JUDUL, HARI_INI)

    @pytest.mark.parametrize("frame", ["Sejak akhir pekan lalu, Polri merombak jabatan Kapolda.",
                                       "Sejak awal pekan lalu, Polri merombak jabatan Kapolda.",
                                       "Sejak Senin pekan lalu, Polri merombak jabatan Kapolda."])
    def test_a_frame_with_a_modifier_is_not_an_anchor(self, frame):
        """SYS-167: "pekan lalu" is preceded by "sejak akhir ", not "sejak ", so the frame is counted as an anchor
        -- and named in the retry's detail, against prompt rule 4."""
        assert arc_style.time_anchors(frame) == []


# ── SYS-164: openings with a modifier before the table phrase ────────────────────────────────────

class TestSys164ModifiedOpenings:
    @pytest.mark.parametrize("opening", ["Senin pekan lalu, Polri memutasi 88 perwira.",
                                         "Jumat pekan lalu, Polri memutasi 88 perwira.",
                                         "Akhir pekan lalu, Polri memutasi 88 perwira.",
                                         "Awal pekan lalu, Polri memutasi 88 perwira."])
    def test_a_recap_opening_on_a_modified_relative_time_is_refused_by_the_tie(self, opening):
        """SYS-167: SYS-164's symptom 1 ("Pekan lalu, Polri memutasi 88 perwira." tied) with one more word in
        front. 558 of 136,983 articles write "<hari>/akhir/awal pekan lalu" (26% of the 2,131 "pekan lalu")."""
        assert arc_style.opens_on_time(opening)
        assert arc_style.time_led(opening)
        assert not arc_style.tied_to_today(opening, JUDUL, HARI_INI)


# ── SYS-165: a shared future time ───────────────────────────────────────────────────────────────

BPGMN_HARI_INI = ("Presiden Prabowo Subianto memimpin rapat terbatas soal kebakaran hutan dan lahan di Istana "
                  "Kepresidenan Jakarta, Senin (12/10). Menko Polkam Dudung Abdurachman menyebut pelantikan "
                  "pimpinan Badan Pengelola Gambut dan Mangrove Nasional diharapkan minggu depan.")
BPGMN_LATAR = "Kini Dudung menyebut Satyawan Puryatmoko, Dirjen KSDAE Kementerian Kehutanan, sebagai calon Ketua BPGMN."
BPGMN_AGENDA = "Pelantikan pimpinan BPGMN diharapkan dilakukan minggu depan menurut Dudung."


class TestSys165SharedFuture:
    def test_a_future_time_told_in_the_latar_is_shared(self):
        """The dev's call on #361: a future phrase in the latar counts as told. No dev test puts it there."""
        latar = "Pekan lalu Dudung menyebut pelantikan pimpinan Badan Pengelola Gambut dan Mangrove Nasional minggu depan."
        assert sa.agenda_repeats(BPGMN_AGENDA, latar, "Prabowo memimpin rapat karhutla, Senin (12/10).")

    @pytest.mark.parametrize("agenda_time,told_time", [("pekan depan", "minggu depan"), ("Minggu Depan", "pekan depan"),
                                                       ("minggu  depan", "pekan depan"),
                                                       ("akhir minggu ini", "akhir pekan ini")])
    def test_synonyms_case_and_spacing_meet(self, agenda_time, told_time):
        hari_ini = BPGMN_HARI_INI.replace("minggu depan", told_time)
        assert sa.agenda_repeats(BPGMN_AGENDA.replace("minggu depan", agenda_time), BPGMN_LATAR, hari_ini)

    def test_akhir_pekan_ini_is_not_pekan_ini(self):
        """The dev's call on #361: an agenda that narrows the time is kept."""
        hari_ini = BPGMN_HARI_INI.replace("minggu depan", "pekan ini")
        assert not sa.agenda_repeats(BPGMN_AGENDA.replace("minggu depan", "akhir pekan ini"), BPGMN_LATAR, hari_ini)

    def test_a_shared_future_time_below_the_share_is_kept(self):
        assert not sa.agenda_repeats("DPR memanggil Kepala BNPB soal anggaran pemadaman minggu depan.",
                                     BPGMN_LATAR, BPGMN_HARI_INI)

    def test_the_bpgmn_agenda_is_dropped_end_to_end(self):
        texts = [TEXTS[0] + " Pelantikan pimpinan BPGMN diharapkan minggu depan, kata Dudung.", *TEXTS[1:]]
        hari_ini = ("Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara, Senin (12/10). "
                    "Dudung menyebut pelantikan pimpinan BPGMN diharapkan minggu depan.")
        arc = sa.parse(_answer(hari_ini=hari_ini, agenda=BPGMN_AGENDA), texts, TIMELINE, DAY)
        assert arc.agenda == "" and arc.agenda_dropped

    @pytest.mark.parametrize("agenda_time,told_time", [("pekan mendatang", "minggu depan"),
                                                       ("esok", "besok"),
                                                       ("minggu mendatang", "pekan depan")])
    def test_held_out_synonyms_meet(self, agenda_time, told_time):
        """SYS-168: "pekan/minggu/bulan mendatang" (99/38/265 articles) and "esok" (191) are not in _FUTURE."""
        hari_ini = BPGMN_HARI_INI.replace("minggu depan", told_time)
        assert sa.agenda_repeats(BPGMN_AGENDA.replace("minggu depan", agenda_time), BPGMN_LATAR, hari_ini)


# ── SYS-166: a future time makes a scheduled step ───────────────────────────────────────────────

class TestSys166Scheduled:
    @pytest.mark.parametrize("agenda", ["Presiden berangkat ke Kairo lusa.", "Presiden berangkat ke Kairo bulan depan.",
                                        "Aturan itu terbit tahun depan.", "Presiden berangkat ke Kairo Minggu depan.",
                                        "Presiden berangkat ke Kairo akhir minggu ini.",
                                        "Presiden berangkat ke Kairo awal pekan depan."])
    def test_the_times_moved_out_of_scheduled_still_keep_an_agenda(self, agenda):
        """_SCHEDULED lost besok/lusa/pekan|bulan|tahun depan to _FUTURE: none may be dropped now."""
        assert sa._agenda_kept(agenda)

    @pytest.mark.parametrize("agenda", ["Presiden berangkat ke Kairo.", "Kasus ini diperkirakan terus bergulir.",
                                        "Presiden berangkat ke Kairo Minggu (lalu)."])
    def test_no_time_is_still_dropped(self, agenda):
        assert not sa._agenda_kept(agenda)

    @pytest.mark.parametrize("agenda", ["Presiden berangkat ke Kairo pekan mendatang.",
                                        "Presiden berangkat ke Kairo esok.",
                                        "Aturan turunan ditargetkan terbit akhir tahun ini.",
                                        "Aturan turunan ditargetkan terbit bulan mendatang.",
                                        "Aturan turunan ditargetkan terbit akhir bulan ini."])
    def test_held_out_future_times_keep_an_agenda(self, agenda):
        """SYS-168: SYS-166's own defect class (a synonym missing from the hand-written list) on the phrases news
        writes as often as "minggu depan" (348): "akhir tahun ini" 487, "bulan mendatang" 265, "esok" 191,
        "akhir bulan ini" 118, "pekan mendatang" 99."""
        assert sa._agenda_kept(agenda)


# ── SYS-148/166: an agenda's future time must be one an article states ──────────────────────────

class TestAgendaFutureTimeStated:
    def test_an_unstated_calendar_date_is_refused(self):
        """The existing rule, for contrast: no article states 16/10."""
        with pytest.raises(Rejected) as e:
            sa.parse(_answer(agenda="Rapat lanjutan dijadwalkan Jumat (16/10)."), TEXTS, TIMELINE, DAY)
        assert e.value.reason == "date"

    @pytest.mark.parametrize("agenda", ["Rapat lanjutan karhutla dijadwalkan minggu depan.",
                                        "Rapat lanjutan karhutla dijadwalkan besok.",
                                        "Rapat lanjutan karhutla dijadwalkan pekan ini."])
    def test_an_unstated_future_time_is_not_printed(self, agenda):
        """SYS-169: the articles say "Kamis (15/10)"; the agenda's "minggu depan" / "besok" / "pekan ini" is the
        model's. The prompt asks for a step "tertulis di artikel", and the same agenda with an unstated date is
        refused. Either a refusal or a drop satisfies this test; printing it does not."""
        try:
            arc = sa.parse(_answer(agenda=agenda), TEXTS, TIMELINE, DAY)
        except Rejected:
            return
        assert arc.agenda == ""

    def test_a_stated_future_time_is_kept(self):
        texts = [TEXTS[0] + " Pelantikan pimpinan BPGMN diharapkan minggu depan.", *TEXTS[1:]]
        arc = sa.parse(_answer(agenda="Pelantikan pimpinan BPGMN dijadwalkan pekan depan."), texts, TIMELINE, DAY)
        assert arc.agenda


# ── SYS-161: a change claim needs a running total or a change in the source ─────────────────────

POLRI_SRC = ("Kapolri memutasi 199 perwira melalui Surat Telegram Nomor ST/2251/X/KEP/2026. "
             "Total ada 199 pejabat Polri yang dirotasi.")


class TestSys161ChangeClaims:
    @pytest.mark.parametrize("claim", ["Kini jumlah personel yang dimutasi bertambah menjadi 199 orang.",
                                       "Kini jumlahnya bertambah lagi 111 orang menjadi 199 personel.",
                                       "Kini jumlahnya naik jadi 199.",
                                       "Jumlah personel yang dimutasi bertambah dari 88 menjadi 199."])
    def test_the_menjadi_forms_are_refused_on_a_one_event_total(self, claim):
        from newscrawler.core.source_check import unbacked_changes
        assert unbacked_changes(claim, POLRI_SRC)

    @pytest.mark.parametrize("source", ["Sebanyak 199 perwira dimutasi sepanjang Januari-Oktober 2026.",
                                        "Jumlah perwira yang dimutasi secara kumulatif 199 orang.",
                                        "Jumlah perwira yang dimutasi naik dari 88 menjadi 199."])
    def test_a_running_total_backs_it(self, source):
        from newscrawler.core.source_check import unbacked_changes
        assert not unbacked_changes("Kini jumlahnya bertambah menjadi 199 orang.", source)

    @pytest.mark.parametrize("claim", ["Jumlah yang dimutasi kini bertambah hingga 199 orang.",
                                       "Jumlah yang dimutasi kini bertambah ke angka 199 orang."])
    def test_the_hingga_and_ke_angka_forms_are_refused_too(self, claim):
        """SYS-170: the guard reads "(men)jadi N" only. News writes "<verb> hingga N" in 914 articles and
        "<verb> ke angka/level N" in 320 (vs 3,462 for "menjadi"); the replays already hold "naik hingga
        Rp500 juta". Prompt rule 3 names only "menjadi", so the model's paraphrase walks past both."""
        from newscrawler.core.source_check import unbacked_changes
        assert unbacked_changes(claim, POLRI_SRC)
