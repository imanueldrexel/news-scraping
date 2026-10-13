"""SYS-148 (#338): a top story told as an arc, and the checks that hold its
prose to today's articles and the timeline items the model chose (`alur`)."""
import json
from datetime import date

import pytest

import newscrawler.core.story_arc as sa
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
        reason, detail = _reason(_answer(latar="Pada 24/9 Prabowo menggelar rapat; 24 ahli dipanggil."))
        assert reason == "number" and '"24"' in detail

    def test_a_chosen_items_own_date_passes_in_either_form(self):
        assert _parse(_answer(latar="Pada 24/9 Prabowo menggelar rapat pertama soal karhutla."))
        assert _parse(_answer(latar="Pada 24 September Prabowo menggelar rapat pertama soal karhutla."))

    def test_an_unchosen_items_date_is_refused_as_a_date(self):
        reason, detail = _reason(_answer(latar="Pada 2/10 Prabowo menggelar rapat soal karhutla."))
        assert reason == "date" and "2/10" in detail

    def test_without_alur_latar_holds_no_past_date(self):
        reason, _ = _reason(_answer(alur=[], latar="Rapat soal karhutla sudah digelar Senin (12/10) dan 15/10."))
        assert reason == "date"
        assert _parse(_answer(alur=[], latar="Rapat soal karhutla digelar Senin (12/10) di Istana Negara."))

    def test_number_problems_are_named_before_date_problems(self):
        reason, detail = _reason(_answer(latar="Pada 2/10 sebanyak 999 hektare terbakar."))
        assert reason == "number" and "2/10" in detail and "999" in detail


class TestSubjectAndThread:
    def test_an_off_thread_item_is_refused_first(self):
        reason, detail = _reason(_answer(alur=[N, N + 1, N + 2]))
        assert reason == "alur" and "Wantimpres" in detail

    def test_on_the_retry_it_is_moved_out(self):
        arc = _parse(_answer(alur=[N, N + 1, N + 2]), lenient=True)
        assert arc.alur == [0, 1] and arc.demoted_alur == 1

    def test_a_fact_from_the_moved_out_item_still_fails(self):
        latar = "Pada 2/10 Prabowo melantik Wantimpres di Istana, setelah rapat karhutla 24/9."
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


class TestPrompt:
    def test_indexes_continue_from_today_into_the_timeline(self):
        prompt = sa.build_prompt(SHOWN, TIMELINE, DAY)
        assert "[0] CNBC Indonesia — Prabowo Pimpin Rapat Karhutla" in prompt
        assert f"[{N}] Rabu, 23 Sep · CNBC Indonesia — Prabowo Dapat Laporan 209 Ha" in prompt
        assert f"[{N + 2}] Jumat, 2 Okt · tvOnenews — Prabowo Lantik Wantimpres" in prompt
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
