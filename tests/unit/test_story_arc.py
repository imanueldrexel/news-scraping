"""SYS-148 (#338): a top story told as an arc, and the checks that hold its
prose to today's articles and the timeline items the model chose (`alur`)."""
import json
from datetime import date

import pytest

import newscrawler.core.story_arc as sa
from newscrawler.core import arc_style
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
         "2 kalimat latar disusun dengan tanggal"),
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
        assert reason == "length" and "kalimat latar disusun dengan tanggal" in detail and sa.STYLE_ASK in detail

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
        assert "kalimat latar disusun dengan tanggal" in s.prompts[1] and sa.STYLE_ASK in s.prompts[1]


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


class TestOrdinals:
    """SYS-158 (#353): a count no larger than the chosen timeline, a record only when stated."""

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
