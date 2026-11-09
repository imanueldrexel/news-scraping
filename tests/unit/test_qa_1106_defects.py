"""QA's failing tests from the 2026-11-06 audit (qa-defects #440, #445, #446, #448, #449) and the held-out cases QA
posted on #421, #422 and #423 that day, copied unchanged from the issues.

Only the layout differs: one module, the issues' imports at the top, each issue's helpers and tests under its number
(a helper or constant two issues share by name is suffixed with the issue's number). `sys.path.insert(0, os.getcwd())`
is not needed under pytest's rootdir.

#445 carries only the case the owner kept (ADR-031, 2026-11-06: "diselesaikan pada"; "dituntaskan pada" and
"rampung <month>" are accepted gaps), QA's controls, and the inverse probe the owner's Done-when names.
"""
import pytest

from newscrawler.core import causal_check as cc
from newscrawler.core import source_check as sc
from newscrawler.web import followup as fu
from newscrawler.web import keywords as kw

ANTAM = ["Berapa harga emas Antam hari ini?"]
FED = ["Apa keputusan The Fed terbaru?"]


# ---- #448 (SYS-144): a thread follow-up opening on a time word or particle is searched alone ----
@pytest.mark.parametrize("question,previous", [
    ("Kemarin harganya berapa?", ANTAM),
    ("Besok harganya naik?", ANTAM),
    ("Benarkah harganya turun?", ANTAM),
    ("Mungkinkah harganya naik lagi?", ANTAM),
    ("Kira-kira harganya berapa?", ANTAM),
    ("Kok harganya turun?", ANTAM),
    ("Masa harganya turun?", ANTAM),
    ("Kemarin dampaknya ke rupiah bagaimana?", FED),
    ("Tadi dampaknya ke IHSG apa?", FED),
])
def test_448_a_thread_follow_up_keeps_its_thread_on_the_fallback(question, previous):
    assert fu.resolve(question, previous, None).how == fu.FALLBACK_THREAD


@pytest.mark.parametrize("question", ["Sekarang harganya berapa?", "Hari ini harganya berapa?",
                                      "Lalu harganya berapa?"])
def test_448_control_a_listed_opener_keeps_its_thread(question):
    assert fu.resolve(question, ANTAM, None).how == fu.FALLBACK_THREAD


def test_448_control_a_new_subject_still_goes_alone():
    assert fu.resolve("Sritex ujung-ujungnya bangkrut?", ANTAM, None).how == fu.FALLBACK_OWN


# ---- #449 (SYS-145): the same on the kept path ----
@pytest.mark.parametrize("question,previous", [
    ("Kemarin harganya berapa?", ANTAM),
    ("Besok harganya naik?", ANTAM),
    ("Benarkah harganya turun?", ANTAM),
    ("Kok harganya turun?", ANTAM),
    ("Kemarin dampaknya ke rupiah bagaimana?", FED),
    ("Tadi dampaknya ke IHSG apa?", FED),
])
def test_449_a_kept_thread_follow_up_uses_the_thread(question, previous):
    assert fu.resolve(question, previous, question).how == fu.KEPT_THREAD


def test_449_control_a_kept_effect_question_uses_the_thread():
    q = "Bagaimana dampaknya ke rupiah?"
    assert fu.resolve(q, FED, q).how == fu.KEPT_THREAD


def test_449_control_a_kept_switch_stays_kept():
    q = "Sritex ujung-ujungnya bangkrut?"
    assert fu.resolve(q, ANTAM, q).how == fu.KEPT


# ---- #421 / #422 / #423: QA's 2026-11-06 held-out cases ("<x>nya, <interrogative> ...", no "yang") ----
@pytest.mark.parametrize("question", [
    "Anehnya, kenapa saham di Garuda Indonesia anjlok?",
    "Parahnya, kenapa saham di Waskita Karya anjlok?",
])
def test_421_heldout_a_switch_stays_alone_on_the_fallback(question):
    assert fu.resolve(question, ANTAM, None).how == fu.FALLBACK_OWN


def test_422_heldout_a_kept_switch_stays_kept():
    q = "Anehnya, kenapa saham di Garuda Indonesia anjlok?"
    assert fu.resolve(q, ANTAM, q).how == fu.KEPT


@pytest.mark.parametrize("question,plain", [
    ("Anehnya, kenapa Garuda rugi?", "Kenapa Garuda rugi?"),
    ("Parahnya, bagaimana nasib Waskita?", "Bagaimana nasib Waskita?"),
])
def test_423_heldout_an_opening_adverb_adds_no_keyword(question, plain):
    assert [t.word for t in kw.terms(question)] == [t.word for t in kw.terms(plain)]


# ---- #440 (SYS-189): an adverb, preposition or predicate after "tertekan / terkerek ..." is no cause ----
IHSG_DOWN = "IHSG ditutup turun 1,2 persen ke level 7.100 pada Senin."
IHSG_UP = "IHSG ditutup naik 1,2 persen ke level 7.100 pada Senin."
RUPIAH = "Rupiah melemah 0,5 persen ke Rp16.500 per dolar AS pada Senin."
BBRI = "Saham BBRI turun 3 persen pada Senin."


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


@pytest.mark.parametrize("prose,source", [
    ("IHSG tertekan tajam pada perdagangan Senin.", IHSG_DOWN),
    ("IHSG tertekan cukup dalam pada perdagangan Senin.", IHSG_DOWN),
    ("Rupiah tertekan sepanjang perdagangan Senin.", RUPIAH),
    ("Rupiah tertekan lagi pada Senin.", RUPIAH),
    ("Rupiah tertekan signifikan pada Senin.", RUPIAH),
    ("IHSG terkerek naik 1,2 persen pada Senin.", IHSG_UP),
    ("IHSG terangkat tipis pada Senin.", IHSG_UP),
    ("Saham BBRI terseret turun pada Senin.", BBRI),
])
def test_440_a_plain_movement_is_no_causal_claim(prose, source):
    assert kept(prose, source)


def test_440_control_a_named_cause_still_needs_a_quote():
    assert not kept("IHSG turun, tertekan aksi jual investor asing.", IHSG_DOWN)


# ---- #445 (SYS-191, narrowed by the owner to "diselesaikan pada"): an unstated end point is printed ----
MSCI = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. "
        "Freeze MSCI berpotensi berlanjut hingga semester II-2027. Wilbert memperkirakan MSCI akan memperpanjang "
        "kebijakan pembekuan pada evaluasi November 2026.")


@pytest.mark.parametrize("prose", [
    "Pembekuan diselesaikan pada November 2026.",
])
def test_445_an_unstated_end_is_refused(prose):
    assert sc.unbacked_end_times(prose, MSCI) != []


@pytest.mark.parametrize("prose", ["Pembekuan rampung pada November 2026.", "Pembekuan selesai November 2026."])
def test_445_control_a_read_opener_is_refused(prose):
    assert sc.unbacked_end_times(prose, MSCI) != []


# ---- #446 (SYS-186): after "dari <name>" a named end ("hingga Lebaran 2027") is read as a place ----
SRC_446 = "Maskapai memberi diskon tiket untuk penerbangan domestik. Program dimulai pekan ini."


@pytest.mark.parametrize("prose", [
    "Diskon tiket dari Garuda Indonesia berlaku hingga Lebaran 2027.",
    "Bantuan dari Kemensos disalurkan hingga Natal 2026.",
    "Program dari Pertamina berjalan hingga HUT RI 2027.",
])
def test_446_an_invented_end_after_dari_name_is_refused(prose):
    assert sc.unbacked_end_times(prose, SRC_446) != []


def test_446_control_a_range_of_places_is_no_end_point():
    assert sc.unbacked_end_times("Sebelumnya, bantuan disalurkan dari Sabang hingga Merauke pada akhir Oktober.",
                                 "Asap meluas sejak Kamis (22/10). Rapat lanjutan belum dijadwalkan.") == []
