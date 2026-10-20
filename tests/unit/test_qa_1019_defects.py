"""QA's failing tests for the 2026-10-19 qa-defects (#398-#412), copied unchanged from
scripts/experiments/qa_2026_10_19/defects/ (imports adjusted only), one section per defect.

Not copied, because the dev disputes them (comments on the issues; QA rules):
- #401's "terimbas" case: SYS-184's accepted test_affected_is_no_link pins "terimbas" as no causal word;
- #405 (one generic shared root): the stricter subject rule refuses the live MSCI source's true end.
Both stay red in QA's folder.
"""
from datetime import date

import pytest

import newscrawler.core.story_arc as sa
from newscrawler.core import causal_check as cc
from newscrawler.core import source_check as sc
from newscrawler.core.llm_json import Rejected
from newscrawler.web import followup as fu
from newscrawler.web import keywords as kw
from tests.unit.test_story_arc import FRAME, TEXTS, TIMELINE, _answer


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


MSCI = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. "
        "Freeze MSCI berpotensi berlanjut hingga semester II-2027. Wilbert memperkirakan MSCI akan memperpanjang "
        "kebijakan pembekuan pada evaluasi November 2026.")
ANTAM = ["Berapa harga emas Antam hari ini?"]
FED = ["Apa keputusan The Fed terbaru?"]


# ── #398 (SYS-181): an anaphor sharing one root lends another subject ──────────────────────────────

SRC_398 = "IHSG turun 1 persen pada Senin. Penurunan saham BBRI tersebut dipicu aksi jual asing."


def test_398_another_subject_is_not_backed_through_the_anaphor():
    assert not kept("IHSG turun karena aksi jual asing.", SRC_398)


def test_398_control_the_anaphors_own_subject_stays_kept():
    assert kept("Saham BBRI turun karena aksi jual asing.", SRC_398)


# ── #399 / #400 (SYS-185): a denial after the link; "menyangkal" ───────────────────────────────────

CLAIM_385 = "Harga tiket pesawat domestik naik karena harga avtur melonjak."


def test_399_a_denial_after_the_link_backs_no_flat_claim():
    src = "Anggapan bahwa harga tiket pesawat domestik naik karena harga avtur melonjak dibantah maskapai."
    assert not kept(CLAIM_385, src)


def test_399_control_a_denial_before_the_link_is_read():
    assert not kept(CLAIM_385, "Maskapai membantah harga tiket pesawat domestik naik karena harga avtur melonjak.")


@pytest.mark.parametrize("src", [
    "Maskapai menyangkal harga tiket pesawat domestik naik karena harga avtur melonjak.",
    "Kabar harga tiket pesawat domestik naik karena harga avtur melonjak disangkal maskapai.",
])
def test_400_a_denied_link_backs_no_flat_claim(src):
    assert not kept(CLAIM_385, src)


# ── #401 (SYS-189): unlisted causal forms ("terimbas" disputed, see the module docstring) ──────────

NO_REASON = "Rupiah melemah 0,5 persen ke Rp16.500 per dolar AS pada Senin."


@pytest.mark.parametrize("prose", [
    "Rupiah melemah, dipacu data tenaga kerja AS yang kuat.",
    "Rupiah melemah, terdorong data tenaga kerja AS yang kuat.",
    "Rupiah melemah, buntut data tenaga kerja AS yang kuat.",
])
def test_401_an_invented_link_is_refused(prose):
    assert not kept(prose, NO_REASON)


def test_401_control_a_listed_form_is_refused():
    assert not kept("Rupiah melemah, didorong data tenaga kerja AS yang kuat.", NO_REASON)


# ── #402 (SYS-192): unlisted hedges ────────────────────────────────────────────────────────────────

FACT = "Kebakaran gudang itu dipicu korsleting listrik."


@pytest.mark.parametrize("src", [
    "Kebakaran gudang itu diperkirakan dipicu korsleting listrik.",
    "Kebakaran gudang itu diyakini dipicu korsleting listrik.",
    "Kebakaran gudang itu disebut-sebut dipicu korsleting listrik.",
])
def test_402_a_dropped_hedge_is_refused(src):
    assert not kept(FACT, src)


def test_402_control_a_listed_hedge_is_refused():
    assert not kept(FACT, "Kebakaran gudang itu diduga dipicu korsleting listrik.")


# ── #403 (SYS-191): end points opened by stop verbs and deadlines ──────────────────────────────────

@pytest.mark.parametrize("prose", [
    "Pembekuan dihentikan pada November 2026.",
    "Pembekuan diakhiri pada November 2026.",
    "Pembekuan hanya bertahan paling lambat November 2026.",
])
def test_403_an_unstated_end_is_refused(prose):
    assert sc.unbacked_end_times(prose, MSCI) != []


def test_403_control_a_listed_opener_is_refused():
    assert sc.unbacked_end_times("Pembekuan berakhir pada November 2026.", MSCI) != []


# ── #404 (SYS-193): a fronted end point ("#405" disputed, see the module docstring) ────────────────

SRC_404 = ("Defisit APBN hingga September 2026 mencapai Rp319 triliun. Pembekuan saham berlanjut setelah evaluasi "
           "November 2026.")


def test_404_a_fronted_end_needs_its_subject():
    assert sc.unbacked_end_times("Hingga 2026, pembekuan saham berlanjut.", SRC_404) != []


def test_404_control_the_same_end_not_fronted_is_refused():
    assert sc.unbacked_end_times("Pembekuan saham berlanjut hingga 2026.", SRC_404) != []


# ── #406 (SYS-186): a spatial "hingga <place> pada <time>" ─────────────────────────────────────────

SRC_406 = "Asap meluas sejak Kamis (22/10). Rapat lanjutan belum dijadwalkan."


def test_406_a_spatial_hingga_is_no_end_point():
    assert sc.unbacked_end_times("Sebelumnya, asap meluas hingga Riau pada akhir Oktober.", SRC_406) == []


def test_406_control_a_time_end_point_is_still_read():
    assert sc.unbacked_end_times("Pembekuan berlanjut hingga akhir Oktober.", SRC_406) != []


# ── #407 (SYS-177): plan words outside the cue list ────────────────────────────────────────────────

D26 = date(2026, 10, 26)
LATAR = FRAME + "Pada 23/9 Seskab melaporkan 209 hektare lahan masih terbakar. "
PAST = [TEXTS[0].replace("Rapat lanjutan dijadwalkan Kamis (15/10).",
                         "Rapat lanjutan belum dijadwalkan. Asap meluas sejak Kamis (22/10)."), *TEXTS[1:]]


def reason(latar):
    try:
        sa.parse(_answer(latar=LATAR + latar, agenda=""), PAST, TIMELINE, D26)
    except Rejected as e:
        return e.reason
    return "kept"


@pytest.mark.parametrize("latar", ["Aturan barunya dipastikan terbit akhir Oktober.",
                                   "Aturan barunya dijanjikan terbit akhir Oktober."])
def test_407_an_invented_schedule_is_refused(latar):
    assert reason(latar) == "date"


def test_407_control_a_listed_cue_is_refused():
    assert reason("Aturan barunya diperkirakan terbit akhir Oktober.") == "date"


# ── #408 / #409 (SYS-144/145): a switch whose only name is in an object phrase ─────────────────────

@pytest.mark.parametrize("question", [
    "Apa yang harusnya dilakukan pemerintah terhadap Garuda Indonesia?",
    "Apa yang aslinya terjadi pada Garuda Indonesia?",
    "Apa yang mestinya terjadi pada Sritex?",
    "Kayaknya ada masalah di Waskita Karya, apa itu?",
])
def test_408_a_switch_stays_alone_on_the_fallback(question):
    assert fu.resolve(question, ANTAM, None).how == fu.FALLBACK_OWN


def test_408_control_a_listed_adverb_stays_alone():
    assert fu.resolve("Apa yang sebenarnya terjadi pada Garuda Indonesia?", ANTAM, None).how == fu.FALLBACK_OWN


@pytest.mark.parametrize("question", [
    "Apa yang harusnya dilakukan pemerintah terhadap Garuda Indonesia?",
    "Apa yang aslinya terjadi pada Garuda Indonesia?",
])
def test_409_a_kept_switch_stays_kept(question):
    assert fu.resolve(question, ANTAM, question).how == fu.KEPT


def test_409_control_a_kept_effect_question_uses_the_thread():
    q = "Bagaimana dampaknya ke rupiah?"
    assert fu.resolve(q, FED, q).how == fu.KEPT_THREAD


# ── #410 (SYS-145): a name as the 5th word of an object phrase ─────────────────────────────────────

def test_410_a_name_late_in_the_object_phrase_keeps_the_thread():
    q = "Bagaimana dampaknya ke saham bank BUMN seperti BBRI?"
    assert fu.resolve(q, FED, q).how == fu.KEPT_THREAD


def test_410_control_a_short_object_phrase_keeps_the_thread():
    q = "Bagaimana dampaknya ke saham BBRI?"
    assert fu.resolve(q, FED, q).how == fu.KEPT_THREAD


# ── #411 / #412 (SYS-146): -nya words in the keyword terms ─────────────────────────────────────────

@pytest.mark.parametrize("question,plain", [
    ("Apa yang mestinya terjadi pada Sritex?", "Apa yang terjadi pada Sritex?"),
    ("Apa yang harusnya dilakukan Garuda?", "Apa yang dilakukan Garuda?"),
    ("Apa yang aslinya terjadi pada Garuda?", "Apa yang terjadi pada Garuda?"),
])
def test_411_an_adverb_adds_no_keyword(question, plain):
    assert [t.word for t in kw.terms(question)] == [t.word for t in kw.terms(plain)]


@pytest.mark.parametrize("question,word", [("Apa jawaban Menkeu saat ditanya soal utang?", "ditanya"),
                                           ("Siapa yang menanya soal utang?", "menanya")])
def test_412_a_non_clitic_word_is_kept_whole(question, word):
    words = [t.word for t in kw.terms(question)]
    assert word in words and word[:-3] not in words
