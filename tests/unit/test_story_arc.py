"""SYS-148 (#338): a top story told as an arc, and the checks that hold its
prose to today's articles and the timeline items the model chose (`alur`)."""
import json
from datetime import date

import pytest

import newscrawler.core.story_arc as sa
from newscrawler.core import arc_style, story_words
from newscrawler.core.llm_json import Rejected
from newscrawler.core.summarizer import QuotaExhausted
from newscrawler.core.thread_finder import TimelineItem

DAY = date(2026, 10, 12)
SHOWN = [
    {"source": "CNBC", "headline": "Prabowo Pimpin Rapat Karhutla di Istana",
     "l1_text": "Presiden Prabowo Subianto memimpin rapat terbatas kebakaran hutan dan lahan di Istana Negara, "
                "Senin (12/10/2026). Menko Polkam Dudung Abdurachman menyebut asap sampai ke negara tetangga. "
                "Rapat lanjutan dijadwalkan Kamis (15/10)."},
    {"source": "KONTAN", "headline": "Asap Karhutla Ganggu 1.673 Penerbangan",
     "l1_text": "Asap kebakaran hutan dan lahan mengganggu 1.673 penerbangan domestik, kata Kemenhub."},
    {"source": "DETIK", "headline": "Harga Cabai Naik di Pasar Induk", "l1_text": "Harga cabai rawit naik 37 persen."},
]
TIMELINE = [
    TimelineItem(101, date(2026, 9, 23), "CNBC", "Prabowo Dapat Laporan 209 Ha Lahan Masih Terbakar",
                 "Seskab melaporkan 209 hektare lahan masih terbakar.", 0.83, 10),
    TimelineItem(102, date(2026, 9, 24), "CNBC", "Prabowo Pimpin Ratas Pencegahan Karhutla, Bakal Panggil Ahli",
                 "Presiden menggelar rapat terbatas soal karhutla dan akan memanggil para ahli.", 0.89, 28),
    TimelineItem(103, date(2026, 10, 2), "TVONENEWS", "Prabowo Lantik Wantimpres",
                 "Presiden Prabowo melantik anggota Wantimpres di Istana.", 0.82, 98),
]
TEXTS = [sa.guard_text(a) for a in SHOWN]
N = len(SHOWN)
FRAME = "Karhutla sudah lama di meja Presiden. "     # a frame sentence, so a latar under test is not a chronicle


def _answer(**override):
    data = {"judul": "Prabowo rapat karhutla lagi, asap sampai negara tetangga",
            "hari_ini": "Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara, Senin (12/10). "
                        "Kebakaran mengganggu 1.673 penerbangan domestik.",
            "latar": "Persoalan karhutla sudah di meja Presiden sejak September. Pada 23/9 Seskab melaporkan 209 "
                     "hektare lahan masih terbakar, dan pada 24 September Prabowo menggelar rapat pertama.",
            "agenda": "Rapat lanjutan dijadwalkan Kamis (15/10).",
            "sekilas": "Prabowo kembali rapat soal karhutla di Istana.",
            "terkait": [0, 1], "tidak_terkait": [2], "alur": [N, N + 1]}
    data.update(override)
    return json.dumps(data)


def _parse(answer, lenient=False, timeline=TIMELINE):
    return sa.parse(answer, TEXTS, timeline, DAY, lenient=lenient)


def _reason(answer, **kw):
    with pytest.raises(Rejected) as e:
        _parse(answer, **kw)
    return e.value.reason, e.value.detail


def _reason_on(answer, texts, lenient=False):
    with pytest.raises(Rejected) as e:
        sa.parse(answer, texts, TIMELINE, DAY, lenient=lenient)
    return e.value.reason, e.value.detail


class TestAccepted:
    def test_a_good_arc(self):
        arc = _parse(_answer())
        assert arc.alur == [0, 1] and [t.sitemap_id for t in arc.alur_items] == [101, 102]
        assert arc.terkait == [0, 1] and arc.tidak_terkait == [2] and not arc.agenda_dropped

    def test_the_prose_is_today_then_the_back_story_closed_by_the_agenda(self):
        arc = _parse(_answer())
        today, back = arc.prose.split("\n\n")
        assert today.startswith("Presiden Prabowo") and back.endswith("Rapat lanjutan dijadwalkan Kamis (15/10).")

    def test_a_new_story_has_no_alur_and_a_dateless_latar(self):
        arc = _parse(_answer(alur=[], latar="Asap disebut sampai ke negara tetangga, menurut Menko Polkam."))
        assert arc.alur == [] and arc.alur_items == []

    def test_judul_of_12_words_is_accepted(self):
        assert _parse(_answer(judul="Prabowo kembali pimpin rapat karhutla lagi saat asap sampai ke negara tetangga"))


class TestNumbersAndDates:
    def test_a_number_in_no_source(self):
        reason, detail = _reason(_answer(hari_ini="Kebakaran mengganggu 2.000 penerbangan, Senin (12/10)."))
        assert reason == "number" and detail.count("2.000") == 1          # named once, not twice

    def test_a_number_only_a_tidak_terkait_article_states_is_refused(self):
        """37 is in today's cabai article, which the answer marks tidak_terkait."""
        assert _reason(_answer(hari_ini="Asap karhutla naik 37 persen, Senin (12/10)."))[0] == "number"

    def test_a_number_only_an_unchosen_item_states_is_refused(self):
        assert _reason(_answer(alur=[N + 1]))[0] == "number"          # 209 is only in item [N]

    def test_an_items_date_does_not_license_its_digits_as_numbers(self):
        """24/9 is item [N+1]'s date: '24' as a number is still not stated anywhere."""
        reason, detail = _reason(_answer(latar=FRAME + "Pada 24/9 Prabowo menggelar rapat; 24 ahli dipanggil."))
        assert reason == "number" and '"24"' in detail

    def test_a_chosen_items_own_date_passes_in_either_form(self):
        assert _parse(_answer(latar=FRAME + "Pada 24/9 Prabowo menggelar rapat pertama soal karhutla."))
        assert _parse(_answer(latar=FRAME + "Pada 24 September Prabowo menggelar rapat pertama soal karhutla."))

    def test_an_unchosen_items_date_is_refused_as_a_date(self):
        reason, detail = _reason(_answer(latar=FRAME + "Pada 2/10 Prabowo menggelar rapat soal karhutla."))
        assert reason == "date" and "2/10" in detail

    def test_without_alur_latar_holds_no_past_date(self):
        reason, _ = _reason(_answer(alur=[], latar="Rapat soal karhutla sudah digelar Senin (12/10) dan 15/10."))
        assert reason == "date"
        assert _parse(_answer(alur=[], latar="Rapat soal karhutla digelar Senin (12/10) di Istana Negara."))

    def test_number_problems_are_named_before_date_problems(self):
        reason, detail = _reason(_answer(latar=FRAME + "Pada 2/10 sebanyak 999 hektare terbakar."))
        assert reason == "number" and "2/10" in detail and "999" in detail


class TestSubjectAndThread:
    def test_an_off_thread_item_is_refused_first(self):
        reason, detail = _reason(_answer(alur=[N, N + 1, N + 2]))
        assert reason == "alur" and "Wantimpres" in detail

    def test_on_the_retry_it_is_moved_out(self):
        arc = _parse(_answer(alur=[N, N + 1, N + 2]), lenient=True)
        assert arc.alur == [0, 1] and arc.demoted_alur == 1

    def test_a_fact_from_the_moved_out_item_still_fails(self):
        latar = FRAME + "Pada 2/10 Prabowo melantik Wantimpres di Istana, setelah rapat karhutla 24/9."
        assert _reason(_answer(alur=[N + 1, N + 2], latar=latar), lenient=True)[0] == "date"

    def test_an_article_off_the_subject_is_refused_then_moved_out(self):
        answer = _answer(terkait=[0, 1, 2], tidak_terkait=[])
        assert _reason(answer)[0] == "subject"
        arc = _parse(answer, lenient=True)
        assert arc.terkait == [0, 1] and arc.tidak_terkait == [2] and arc.demoted == 1


class TestAgenda:
    def test_an_agenda_without_a_date_number_or_schedule_is_dropped(self):
        arc = _parse(_answer(agenda="Pemerintah terus memantau perkembangan karhutla."))
        assert arc.agenda == "" and arc.agenda_dropped and "memantau" not in arc.prose

    def test_a_scheduled_step_is_kept(self):
        assert _parse(_answer(agenda="Rapat lanjutan dijadwalkan pekan depan, menurut Menko Polkam.")).agenda

    def test_an_agenda_number_is_still_checked(self):
        assert _reason(_answer(agenda="Rapat lanjutan dijadwalkan Jumat (16/10)."))[0] == "date"

    @pytest.mark.parametrize("agenda", ["Presiden berangkat ke Kairo minggu depan.",
                                        "Hasil seleksi diumumkan pekan ini.",
                                        "Presiden berangkat ke Kairo akhir pekan ini.",
                                        "Presiden berangkat ke Kairo besok."])
    def test_a_future_time_makes_a_scheduled_step(self, agenda):
        """SYS-166 (#363): "minggu depan" is "pekan depan"; a near time is a step, not a guess."""
        assert sa._agenda_kept(agenda)
        assert not sa._agenda_kept("Presiden berangkat ke Kairo.")


# SYS-163 (#358): the v5 replay's agendas (digests/preview/arcs-v5), as the model wrote them.
EL_SISI = {"hari_ini": "Presiden Mesir Abdel Fattah El-Sisi tiba di Lanud Halim Perdanakusuma, Jakarta, Sabtu (10/10) "
                       "sekitar pukul 17.25 WIB untuk kunjungan kenegaraan hingga Minggu (11/10). Kedatangannya "
                       "disambut "
                       "pengawalan jet tempur TNI AU dan sambutan pelajar.",
           "latar": "Kunjungan ini menyusul lawatan El-Sisi ke Korea Selatan dan Malaysia, dan dijadwalkan bertemu "
                    "Presiden Prabowo Subianto di Istana Kepresidenan, Jakarta, Minggu (11/10) pukul 10.30 WIB. "
                    "Menurut "
                    "Menteri Luar Negeri Arrmanatha Nasir, pertemuan akan diawali pertemuan tete a tete, dilanjutkan "
                    "pertemuan bilateral, dan penandatanganan sejumlah nota kesepahaman.",
           "agenda": "Minggu (11/10) pukul 10.30 WIB, Prabowo menerima El-Sisi di Istana, menurut Menlu Arrmanatha "
                     "Nasir."}
OJOL = {"hari_ini": "Pemerintah resmi menerbitkan Perpres Nomor 27 Tahun 2026 tentang Perlindungan Ekosistem "
                    "Transportasi Berbasis Digital pada Kamis (8/10). Aturan ini mengatur tarif, kemitraan, pengiriman "
                    "makanan dan barang, jaminan sosial, serta bagi hasil aplikator maksimal 8 persen.",
        "latar": "Perpres ini terbit setelah proses sinkronisasi dan harmonisasi yang mempertimbangkan aspirasi pelaku "
                 "ekosistem ojol. Sebelumnya, Menteri UMKM Maman Abdurrahman menyebut penyusunan regulasi cukup lama "
                 "karena harus diselaraskan dengan aturan ketenagakerjaan serta lalu lintas dan angkutan jalan, dan "
                 "pada pertengahan September ia mengungkapkan salah satu alasannya adalah mensinergikan dengan "
                 "undang-undang lain. Status pengemudi tetap sebagai mitra perusahaan aplikasi dengan hak dan "
                 "kewajiban yang jelas.",
        "agenda": "Aturan pelaksana Perpres Ojol harus tuntas paling lambat 31 Desember 2026, menurut Wamensesneg "
                  "Bambang Eko Suhariyanto."}


# SYS-165 (#361): v5 2026-10-12 (digests/preview/arcs-v5/2026-10-12-Y.md), as the model wrote it.
BPGMN = {"hari_ini": "Presiden Prabowo Subianto memimpin rapat terbatas soal kebakaran hutan dan lahan di Istana "
                     "Kepresidenan Jakarta, Senin (12/10). Menko Polkam Dudung Abdurachman menyebut pelantikan "
                     "pimpinan Badan Pengelola Gambut dan Mangrove Nasional diharapkan minggu depan.",
         "latar": "Kini Dudung menyebut Satyawan Puryatmoko, Dirjen KSDAE Kementerian Kehutanan, sebagai calon Ketua "
                  "BPGMN.",
         "agenda": "Pelantikan pimpinan BPGMN diharapkan dilakukan minggu depan menurut Dudung."}


class TestAgendaRepeats:
    def test_the_el_sisi_agenda_repeats_the_latar(self):
        assert sa.agenda_repeats(EL_SISI["agenda"], EL_SISI["latar"], EL_SISI["hari_ini"])

    def test_the_ojol_agenda_is_new(self):
        assert not sa.agenda_repeats(OJOL["agenda"], OJOL["latar"], OJOL["hari_ini"])

    def test_the_same_date_with_new_words_is_kept(self):
        """Half the words are not enough: the agenda must mostly repeat what was told."""
        assert not sa.agenda_repeats("Kamis (15/10) DPR memanggil Kapolri soal anggaran pemadaman dan evakuasi.",
                                     "Prabowo menggelar rapat karhutla lanjutan Kamis (15/10).", "")

    def test_the_same_words_without_its_date_is_kept(self):
        assert not sa.agenda_repeats("Prabowo menerima El-Sisi di Istana Merdeka.", EL_SISI["latar"],
                                     EL_SISI["hari_ini"])

    def test_repeating_hari_ini_rather_than_the_latar_is_dropped(self):
        """DBT-78 (#362): what was told is the latar and hari_ini both."""
        hari_ini = "Prabowo memimpin rapat karhutla, Senin (12/10). Rapat lanjutan dijadwalkan Kamis (15/10) di Istana."
        assert sa.agenda_repeats("Rapat lanjutan dijadwalkan Kamis (15/10) di Istana.", "Karhutla meluas.", hari_ini)

    def test_exactly_the_share_is_a_repeat(self):
        """DBT-78 (#362): AGENDA_REPEAT_SHARE is "at least": 2 of 4 content words (rapat, karhutla)."""
        agenda = "Kapolri memanggil rapat karhutla, Kamis (15/10)."
        latar = "Prabowo menggelar rapat karhutla lanjutan Kamis (15/10)."
        words = story_words.content_words(agenda)
        assert sum(w in story_words.content_words(latar) for w in words) == sa.AGENDA_REPEAT_SHARE * len(words)
        assert sa.agenda_repeats(agenda, latar, "")

    def test_the_bpgmn_agenda_repeats_hari_ini_in_relative_time(self):
        """SYS-165 (#361): digests/preview/arcs-v5/2026-10-12-Y.md -- no date, the shared time is
        "minggu depan" (6 of 7 content words told)."""
        assert sa.agenda_repeats(BPGMN["agenda"], BPGMN["latar"], BPGMN["hari_ini"])

    def test_a_future_time_is_shared_under_its_synonym(self):
        agenda = BPGMN["agenda"].replace("minggu depan", "pekan depan")
        assert sa.agenda_repeats(agenda, BPGMN["latar"], BPGMN["hari_ini"])
        assert sa.future_times("Minggu depan, lalu akhir pekan ini.") == {"pekan depan", "akhir pekan ini"}

    @pytest.mark.parametrize("time", ["bulan depan", "besok", ""])
    def test_another_future_time_or_none_is_kept(self, time):
        """Same words, but not the time hari_ini gave: a different step (or a guess), not a repeat."""
        agenda = BPGMN["agenda"].replace("minggu depan", time)
        assert not sa.agenda_repeats(agenda, BPGMN["latar"], BPGMN["hari_ini"])

    def test_a_new_step_at_the_same_future_time_is_kept(self):
        agenda = "DPR memanggil Kepala BNPB soal anggaran pemadaman minggu depan."
        assert not sa.agenda_repeats(agenda, BPGMN["latar"], BPGMN["hari_ini"])

    def test_dropped_in_parse_not_refused(self):
        latar = FRAME + "Rapat lanjutan Prabowo soal karhutla dijadwalkan Kamis (15/10)."
        arc = _parse(_answer(latar=latar, agenda="Rapat lanjutan karhutla dijadwalkan Kamis (15/10)."))
        assert arc.agenda == "" and arc.agenda_dropped and arc.back_story == latar


class TestShape:
    @pytest.mark.parametrize("override,detail", [
        ({"alur": [1]}, "bukan cuplikan LINI MASA"),
        ({"terkait": [0, N]}, "bukan artikel HARI INI"),
        ({"terkait": []}, "tidak boleh kosong"),
        ({"terkait": [0], "tidak_terkait": [2]}, "tepat sekali"),
        ({"alur": [N, N]}, "dua kali"),
        ({"hari_ini": ""}, "tidak kosong"),
    ])
    def test_refused_as_json(self, override, detail):
        reason, text = _reason(_answer(**override))
        assert reason == "json" and detail in text

    def test_an_empty_timeline_takes_no_alur(self):
        reason, detail = _reason(_answer(alur=[N]), timeline=[])
        assert reason == "json" and "harus kosong" in detail

    def test_latar_and_agenda_may_be_left_out(self):
        data = json.loads(_answer(alur=[]))
        del data["latar"], data["agenda"], data["alur"]
        arc = _parse(json.dumps(data))
        assert (arc.latar, arc.agenda, arc.alur) == ("", "", [])

    def test_the_retry_says_how_much_to_cut_down_to_what_is_asked(self):
        latar = "Karhutla sudah lama di meja Presiden. " + " ".join(["kata"] * 70) + "."
        detail = _reason(_answer(latar=latar))[1]
        assert "latar 76 kata, maks 70 -- buang paling sedikit 16 kata (mis. satu kalimat)" in detail

    def test_the_prompt_asks_what_asked_says(self):
        assert f"judul: maks {sa.ASKED['judul']} kata" in sa.PROMPT
        assert f"latar: 2-3 kalimat, maks {sa.ASKED['latar']} kata" in sa.PROMPT
        assert all(sa.ASKED[k] <= sa.LIMITS[k] for k in sa.LIMITS)

    def test_every_broken_limit_is_named(self):
        reason, detail = _reason(_answer(judul=" ".join(["kata"] * 13), sekilas=" ".join(["kata"] * 16)))
        assert reason == "length" and "judul 13 kata" in detail and "sekilas 16 kata" in detail


def _texts(extra, i=0):
    """TEXTS with `extra` added to today's article [i] (what that article states)."""
    return [t + (" " + extra if k == i else "") for k, t in enumerate(TEXTS)]


class TestStyle:
    """SYS-156 (#351): a chronicle latar is refused as `style` and asked again."""

    @pytest.mark.parametrize("latar,detail", [
        (FRAME + "Seskab melaporkan 209 hektare terbakar pada 23/9, rapat digelar 24/9, dan 12/10 lagi.",
         "3 tanggal kalender"),
        (FRAME + "Pada 23/9 Seskab melaporkan 209 hektare terbakar. Pada 24/9 Prabowo menggelar rapat.",
         "2 kalimat latar dibuka dengan tanggal"),
        ("Karhutla sudah lama di meja Presiden. Karhutla meluas sejak September.", 'dibuka dengan kata "karhutla"'),
    ])
    def test_each_rule_refuses(self, latar, detail):
        reason, text = _reason(_answer(latar=latar))
        assert reason == "style" and detail in text and sa.STYLE_ASK in text

    def test_the_date_led_sentences_are_quoted(self):
        latar = FRAME + "Pada 23/9 Seskab melaporkan 209 hektare terbakar. Pada 24/9 Prabowo menggelar rapat."
        detail = _reason(_answer(latar=latar))[1]
        assert '"Pada 23/9 Seskab melaporkan 209 hektare terbakar. ..."' in detail
        assert '"Pada 24/9 Prabowo menggelar rapat. ..."' in detail

    def test_a_length_refusal_also_names_the_style_problems(self):
        """The retry that shortens the latar hears the style rules too."""
        latar = ("Pada 23/9 Seskab melaporkan 209 hektare lahan masih terbakar. Pada 24/9 Prabowo menggelar rapat "
                 + " ".join(["karhutla"] * 60) + ".")
        reason, detail = _reason(_answer(latar=latar))
        assert reason == "length" and "kalimat latar dibuka dengan tanggal" in detail and sa.STYLE_ASK in detail

    def test_a_date_inside_two_sentences_is_held_only_by_the_date_count(self):
        """Re-run 2026-10-12: '... menembus batas bawah pada 25 September' and '..., ditutup menguat
        pada Jumat (9/10)' were refused as date-led; neither sentence opens on its date."""
        latar = ("Karhutla sudah lama di meja Presiden, dan Seskab melaporkan 209 hektare terbakar pada 23/9. "
                 "Prabowo menggelar rapat pertama soal karhutla pada 24 September.")
        assert _parse(_answer(latar=latar))

    def test_a_latar_at_the_limits_passes(self):
        """Two dates, one date-led sentence, distinct openings, tied to today."""
        assert _parse(_answer())

    def test_still_refused_on_the_retry(self):
        latar = FRAME + "Pada 23/9 Seskab melaporkan 209 hektare terbakar. Pada 24/9 Prabowo menggelar rapat."
        assert _reason(_answer(latar=latar), lenient=True)[0] == "style"

    def test_style_is_named_before_numbers_and_both_are_told(self):
        latar = "Pada 23/9 Seskab melaporkan 999 hektare terbakar. Pada 24/9 Prabowo menggelar rapat."
        reason, detail = _reason(_answer(latar=latar))
        assert reason == "style" and '"999"' in detail

    def test_counted_and_the_retry_carries_the_detail(self):
        chronicle = _answer(latar=FRAME + "Pada 23/9 Seskab melapor. Pada 24/9 Prabowo menggelar rapat.")
        s, rejections = _Script(chronicle, _answer()), []
        assert sa.write_arc(s, SHOWN, TIMELINE, DAY, rejections) and rejections == ["style"]
        assert "kalimat latar dibuka dengan tanggal" in s.prompts[1] and sa.STYLE_ASK in s.prompts[1]


class TestContinuity:
    """SYS-159 (#354): with `alur`, the latar's first sentence ties the past to today's event."""

    def test_a_tied_first_sentence_passes(self):
        assert _parse(_answer(latar="Ini rapat karhutla kedua Prabowo. Rapat pertama digelar akhir September."))

    def test_a_free_standing_recap_is_refused(self):
        reason, detail = _reason(_answer(latar="Pada 23/9 Seskab melaporkan 209 hektare lahan masih terbakar."))
        assert reason == "style" and "tidak mengaitkan alur dengan peristiwa hari ini" in detail

    def test_a_first_sentence_sharing_no_word_with_today_is_refused(self):
        reason, _ = _reason(_answer(latar="Persoalan ini sudah lama berjalan. Seskab melaporkan 209 hektare."))
        assert reason == "style"

    def test_a_latar_without_alur_is_exempt(self):
        """Without alur the latar says why it matters; it need not share a word with today."""
        latar = "Dampaknya dirasakan warga Sumatera, menurut Menko Polkam."
        answer = json.loads(_answer())
        assert not arc_style.tied_to_today(latar, answer["judul"], answer["hari_ini"])
        assert _parse(_answer(alur=[], latar=latar))


class TestRelativeTime:
    """SYS-157 (#352): a relative time spans today, a chosen item's date or a stated date, or is stated."""

    def test_backed_by_a_chosen_item(self):
        assert _parse(_answer(latar="Karhutla sudah di meja Presiden sejak akhir September, saat Seskab melaporkan "
                                    "209 hektare lahan masih terbakar."))

    def test_unbacked_is_refused_as_a_date(self):
        reason, detail = _reason(_answer(latar="Karhutla sudah di meja Presiden sejak awal September, saat Seskab "
                                               "melaporkan 209 hektare lahan masih terbakar."))
        assert reason == "date" and '"awal September"' in detail

    def test_only_a_chosen_items_date_backs_it(self):
        """'awal Oktober' spans 2/10, the date of the unchosen Wantimpres item."""
        assert _reason(_answer(latar="Karhutla sudah dibahas awal Oktober di Istana."))[0] == "date"

    def test_stated_verbatim_in_an_article_passes(self):
        latar = "Karhutla sudah di meja Presiden sejak awal September, saat Seskab melaporkan 209 hektare terbakar."
        texts = _texts("Kebakaran meluas sejak awal September.")
        assert sa.parse(_answer(latar=latar), texts, TIMELINE, DAY)

    def test_backed_by_a_date_an_article_states(self):
        hari_ini = "Presiden Prabowo memimpin rapat karhutla, Senin (12/10), setelah titik api bertambah kemarin."
        assert _reason(_answer(hari_ini=hari_ini))[0] == "date"
        assert sa.parse(_answer(hari_ini=hari_ini), _texts("Titik api bertambah pada Minggu (11/10)."), TIMELINE, DAY)

    def test_the_edition_date_backs_it(self):
        """'pertengahan Oktober' (11-20/10) holds only today, 12/10: no chosen item, no stated date."""
        texts = [TEXTS[0].replace(" Rapat lanjutan dijadwalkan Kamis (15/10).", "")] + TEXTS[1:]
        answer = _answer(hari_ini="Presiden Prabowo memimpin rapat karhutla pertengahan Oktober.", agenda="")
        assert sa.parse(answer, texts, TIMELINE, DAY)
        assert sa.unbacked_times("pertengahan Oktober", DAY, set(), "") == ["pertengahan Oktober"]


    def test_a_count_of_weeks_is_read_with_its_own_span(self):
        """SYS-157 rework: 'tiga pekan lalu' (18-24/9) holds the chosen 23/9 item; read as 'pekan lalu'
        (5-11/10) it was refused. 'dua bulan lalu' (August) holds none."""
        latar = FRAME + "Tiga pekan lalu Seskab melaporkan 209 hektare lahan masih terbakar."
        assert _parse(_answer(latar=latar))
        reason, detail = _reason(_answer(latar=latar.replace("Tiga pekan lalu", "Dua bulan lalu")))
        assert reason == "date" and '"Dua bulan lalu"' in detail

    def test_a_phrase_in_an_old_timeline_item_does_not_license_it(self):
        """SYS-162 (#357): the 23/9 item's 'Kemarin' meant 22/9; it cannot back today's 'Kemarin' (11/10)."""
        timeline = [TIMELINE[0]._replace(opening="Kemarin Seskab melaporkan 209 hektare lahan masih terbakar.")] \
            + TIMELINE[1:]
        latar = FRAME + "Kemarin Seskab melaporkan 209 hektare lahan masih terbakar."
        reason, detail = _reason(_answer(latar=latar), timeline=timeline)
        assert reason == "date" and '"Kemarin"' in detail
        assert sa.parse(_answer(latar=latar), _texts("Kemarin Seskab melaporkan karhutla."), timeline, DAY)

    def test_a_phrase_only_a_tidak_terkait_article_states_does_not_license_it(self):
        """DBT-78 (#362): article [2] (cabai) was not chosen as today's story, so its 'Kemarin' is not."""
        latar = FRAME + "Kemarin Seskab melaporkan 209 hektare lahan masih terbakar."
        reason, detail = _reason_on(_answer(latar=latar), _texts("Kemarin harga cabai naik.", i=2))
        assert reason == "date" and '"Kemarin"' in detail
        assert sa.parse(_answer(latar=latar), _texts("Kemarin asap makin tebal.", i=1), TIMELINE, DAY)

    def test_a_phrase_in_an_article_moved_out_on_the_retry_does_not_license_it(self):
        """DBT-78 (#362): the retry moves the off-subject article [2] out of terkait; its text goes with it."""
        latar = FRAME + "Kemarin Seskab melaporkan 209 hektare lahan masih terbakar."
        answer = _answer(latar=latar, terkait=[0, 1, 2], tidak_terkait=[])
        reason, detail = _reason_on(answer, _texts("Kemarin harga cabai naik.", i=2), lenient=True)
        assert reason == "date" and '"Kemarin"' in detail


class TestOrdinals:
    """SYS-158 (#353): a count no larger than the chosen timeline, a record only when stated."""

    def test_a_record_is_held_to_its_whole_time(self):
        """QA 2026-10-14: 'terendah sejak awal Maret' in a source licensed 'terendah sejak awal tahun'."""
        latar = FRAME + "Luas karhutla kali ini tertinggi sejak awal tahun."
        with pytest.raises(Rejected) as e:
            sa.parse(_answer(latar=latar), _texts("Luas karhutla tertinggi sejak awal Agustus."), TIMELINE, DAY)
        assert e.value.reason == "number" and '"tertinggi sejak awal tahun"' in e.value.detail
        assert sa.parse(_answer(latar=latar), _texts("Luas karhutla tertinggi sejak awal tahun ini."), TIMELINE, DAY)

    def test_a_record_may_drop_its_year_but_not_change_it(self):
        latar = FRAME + "Luas karhutla kali ini tertinggi sejak Maret."
        texts = _texts("Luas karhutla tertinggi sejak Maret 2025.")
        assert sa.parse(_answer(latar=latar), texts, TIMELINE, DAY)
        with pytest.raises(Rejected) as e:
            sa.parse(_answer(latar=latar.replace("Maret.", "Maret 2026.")), _texts("Luas karhutla tertinggi sejak "
                                                                                   "Maret 2025, pada 2026."),
                     TIMELINE, DAY)
        assert e.value.reason == "number" and '"tertinggi sejak Maret 2026"' in e.value.detail

    def test_n_times_in_a_row_is_held_to_the_items(self):
        """'tiga kali berturut-turut' is a series no digit check sees: one item does not back it."""
        latar = FRAME + "Prabowo menggelar rapat karhutla tiga kali berturut-turut."
        reason, detail = _reason(_answer(alur=[N + 1], latar=latar))
        assert reason == "number" and '"tiga kali berturut-turut"' in detail
        assert _parse(_answer(latar=latar))

    def test_a_collective_after_a_verb_costs_no_retry(self):
        """No alur, a crime-desk hari_ini: 'menahan kedua tersangka' = held both suspects."""
        hari_ini = "Polisi menahan kedua tersangka karhutla di Istana Negara, Senin (12/10)."
        assert _parse(_answer(alur=[], latar="", hari_ini=hari_ini, judul="Polisi tahan dua tersangka karhutla",
                              terkait=[0], tidak_terkait=[1, 2]))

    def test_backed_by_enough_items(self):
        assert _parse(_answer(latar="Ini rapat karhutla ketiga sejak September. Seskab melaporkan 209 hektare."))

    def test_more_than_the_items_is_refused(self):
        reason, detail = _reason(_answer(alur=[N + 1], latar="Ini rapat karhutla ketiga sejak September."))
        assert reason == "number" and '"karhutla ketiga"' in detail

    def test_a_series_count_is_held_to_the_items(self):
        """Two chosen items back three days in a row, not four."""
        assert _parse(_answer(sekilas="Prabowo rapat karhutla tiga hari berturut-turut."))
        reason, detail = _reason(_answer(sekilas="Prabowo rapat karhutla empat hari berturut-turut."))
        assert reason == "number" and '"empat hari berturut-turut"' in detail

    def test_a_record_needs_a_source(self):
        latar = "Karhutla kali ini terluas pertama kali sejak Agustus. Seskab melaporkan 209 hektare."
        reason, detail = _reason(_answer(latar=latar))
        assert reason == "number" and '"pertama kali sejak Agustus"' in detail
        assert sa.parse(_answer(latar=latar), _texts("Karhutla meluas pertama kali sejak Agustus."), TIMELINE, DAY)

    def test_an_ordinal_copied_from_an_article_passes(self):
        hari_ini = "Presiden Prabowo memimpin rapat terbatas ketiga soal karhutla, Senin (12/10)."
        assert _reason(_answer(alur=[], hari_ini=hari_ini, latar=""))[0] == "number"
        assert sa.parse(_answer(alur=[], hari_ini=hari_ini, latar=""), _texts("Ini rapat terbatas ketiga."),
                        TIMELINE, DAY)


class TestChangeClaims:
    """SYS-161 (#356): "bertambah/naik/turun menjadi N" needs a source that states N as a total or a change."""

    def test_a_figure_the_source_does_not_call_a_total_is_refused(self):
        """KONTAN states 1.673 disrupted flights as today's event; nothing says it grew to that."""
        hari_ini = "Presiden Prabowo memimpin rapat karhutla, Senin (12/10). Penerbangan terganggu kini bertambah " \
                   "menjadi 1.673."
        reason, detail = _reason(_answer(hari_ini=hari_ini))
        assert reason == "number" and '"bertambah menjadi 1.673"' in detail and "peristiwa hari ini" in detail

    def test_a_running_total_the_source_states_passes(self):
        hari_ini = "Presiden Prabowo memimpin rapat karhutla, Senin (12/10). Penerbangan terganggu kini bertambah " \
                   "menjadi 1.673."
        assert sa.parse(_answer(hari_ini=hari_ini), _texts("Total 1.673 penerbangan terganggu sejak awal Oktober.",
                                                            i=1), TIMELINE, DAY)

    def test_the_prompt_says_so(self):
        assert "bertambah/naik/turun menjadi N" in sa.PROMPT and "peristiwa terpisah" in sa.PROMPT


class TestTimeAnchors:
    """SYS-164 (#359): relative time counts as a time anchor in the latar's caps."""

    def test_more_than_three_anchors_is_refused(self):
        latar = (FRAME + "Akhir September Seskab melaporkan 209 hektare terbakar, Prabowo menggelar rapat 23/9 dan "
                 "24/9, lalu kemarin karhutla meluas.")
        reason, detail = _reason(_answer(latar=latar))
        assert reason == "style" and "4 penanda waktu" in detail and '"Akhir September"' in detail

    def test_three_anchors_and_a_since_frame_pass(self):
        latar = ("Karhutla sudah di meja Presiden sejak akhir September. Seskab melaporkan 209 hektare terbakar "
                 "pada 23/9, dan Prabowo menggelar rapat 24/9 serta akhir September.")
        assert _parse(_answer(latar=latar))

    def test_two_sentences_opening_on_relative_time_are_refused(self):
        latar = (FRAME + "Akhir September Seskab melaporkan 209 hektare terbakar. Tiga pekan lalu Prabowo menggelar "
                 "rapat.")
        reason, detail = _reason(_answer(latar=latar))
        assert reason == "style" and "2 kalimat latar dibuka dengan tanggal atau waktu" in detail

    def test_a_first_sentence_opening_on_relative_time_is_not_a_frame(self):
        reason, detail = _reason(_answer(latar="Akhir September Seskab melaporkan 209 hektare lahan masih terbakar."))
        assert reason == "style" and "tidak mengaitkan alur" in detail

    def test_the_prompt_caps_the_anchors(self):
        assert "paling banyak tiga penanda waktu" in sa.PROMPT


def _example() -> dict:
    """The worked example's JSON, as the model reads it (doubled braces undone, its display wrapping joined)."""
    block = sa.PROMPT.split("CONTOH JAWABAN")[1].split("HARI INI\n")[0]
    block = " ".join(block[block.index("{{"):block.rindex("}}") + 2].split())
    return json.loads(block.replace("{{", "{").replace("}}", "}"))


class TestPrompt:
    def test_no_dated_fact_per_timeline_item_is_asked(self):
        """SYS-154: the rules that made the chronicle are gone."""
        assert "setiap fakta bertanggal" not in sa.PROMPT and "ditulis dengan tanggalnya" not in sa.PROMPT
        assert "urut waktu" not in sa.PROMPT
        assert "Setiap fakta dari LINI MASA harus berasal dari cuplikannya." in sa.PROMPT

    @pytest.mark.parametrize("rule", ["Kalimat pertama adalah bingkai", "paling banyak dua titik balik",
                                      "Kaitkan setiap fakta lampau dengan hari ini",
                                      "waktu relatif yang tertera dalam kurung di LINI MASA",
                                      "Jangan membuka dua kalimat dengan kata yang sama",
                                      "HANYA jika artikel menyebutnya"])
    def test_the_six_story_rules(self, rule):
        assert rule in sa.PROMPT.replace("\n    ", " ").replace("\n       ", " ")

    def test_the_example_latar_reads_as_a_story(self):
        """SYS-155: the example is what the model copies; it passes the style check it will be held to."""
        ex = _example()
        assert ex["alur"] and sa.chronicle(ex["latar"], ex["judul"], ex["hari_ini"], has_alur=True) == []
        assert not arc_style.date_led(arc_style.sentences(ex["latar"])[0])

    def test_indexes_continue_from_today_into_the_timeline(self):
        prompt = sa.build_prompt(SHOWN, TIMELINE, DAY)
        assert "[0] CNBC Indonesia — Prabowo Pimpin Rapat Karhutla" in prompt
        assert f"[{N}] Rabu, 23 Sep (akhir September) · CNBC Indonesia — Prabowo Dapat Laporan 209 Ha" in prompt
        assert f"[{N + 2}] Jumat, 2 Okt (awal Oktober) · tvOnenews — Prabowo Lantik Wantimpres" in prompt
        assert "3 artikel Senin, 12 Oktober 2026" in prompt and "3 cuplikan" in prompt

    def test_an_empty_timeline_says_so(self):
        assert "LINI MASA\n(kosong)" in sa.build_prompt(SHOWN, [], DAY)

    def test_the_example_is_from_outside_the_replay_week(self):
        assert "Jumat (2/10)" in sa.PROMPT and "12/10" not in sa.PROMPT.split("CONTOH JAWABAN")[1]


class _Script:
    def __init__(self, *items):
        self.items, self.prompts = list(items), []

    def summarize(self, prompt):
        self.prompts.append(prompt)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestWriteArc:
    def test_accepted(self):
        rejections = []
        assert sa.write_arc(_Script(_answer()), SHOWN, TIMELINE, DAY, rejections).alur == [0, 1]
        assert rejections == []

    def test_refused_then_repaired_leniently(self):
        s, rejections = _Script(_answer(alur=[N, N + 1, N + 2]), _answer(alur=[N, N + 1, N + 2])), []
        arc = sa.write_arc(s, SHOWN, TIMELINE, DAY, rejections)
        assert arc.demoted_alur == 1 and rejections == ["alur"]
        assert "Jawaban sebelumnya ditolak: cuplikan [5] bukan bagian dari alur" in s.prompts[1]

    def test_two_refusals_are_none(self):
        rejections = []
        assert sa.write_arc(_Script("x", "y"), SHOWN, TIMELINE, DAY, rejections) is None
        assert rejections == ["json", "json"]

    def test_a_quota_keeps_the_first_refusal_counted(self):
        rejections = []
        with pytest.raises(QuotaExhausted):
            sa.write_arc(_Script("x", QuotaExhausted("429")), SHOWN, TIMELINE, DAY, rejections)
        assert rejections == ["json"]
