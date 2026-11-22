"""QA's failing tests from the 2026-11-08 audit (qa-defects #450, #451, #452, #453, #454), copied unchanged from the
issues.

Only the layout differs: one module, the issues' imports at the top, each issue's constants and tests under its number
(a name two issues share is suffixed with the issue's number). `sys.path.insert(0, os.getcwd())` is not needed under
pytest's rootdir.
"""
import pytest

from newscrawler.core import causal_check as cc
from newscrawler.core import source_check as sc
from newscrawler.web import followup as fu

ANTAM = ["Berapa harga emas Antam hari ini?"]
BCA = ["Berapa laba BCA kuartal III 2026?"]


# ---- #450 (SYS-144): a follow-up opening on a common-noun subject is searched with the old thread ----
@pytest.mark.parametrize("question,previous", [
    ("Gula harganya naik?", ANTAM),
    ("Beras harganya berapa sekarang?", ANTAM),
    ("Nikel harganya turun?", ANTAM),
    ("Timah labanya berapa?", ANTAM),
    ("Mandiri labanya naik?", BCA),
])
def test_450_a_new_subject_stays_alone_on_the_fallback(question, previous):
    assert fu.resolve(question, previous, None).how == fu.FALLBACK_OWN


@pytest.mark.parametrize("question", ["Kemarin harganya berapa?", "Kok harganya turun?", "Benarkah harganya turun?"])
def test_450_control_448_time_words_and_particles_keep_the_thread(question):
    assert fu.resolve(question, ANTAM, None).how == fu.FALLBACK_THREAD


def test_450_control_a_capitalised_name_stays_alone():
    assert fu.resolve("Sritex utangnya berapa?", ANTAM, None).how == fu.FALLBACK_OWN


# ---- #451 (SYS-145): the same on the kept path ----
@pytest.mark.parametrize("question,previous", [
    ("Gula harganya naik?", ANTAM),
    ("Beras harganya berapa sekarang?", ANTAM),
    ("Timah labanya berapa?", ANTAM),
    ("Mandiri labanya naik?", BCA),
])
def test_451_a_kept_switch_stays_kept(question, previous):
    assert fu.resolve(question, previous, question).how == fu.KEPT


def test_451_control_449_a_kept_time_word_follow_up_uses_the_thread():
    q = "Kemarin harganya berapa?"
    assert fu.resolve(q, ANTAM, q).how == fu.KEPT_THREAD


# ---- #452 (SYS-189): movement_words.txt holds -nya nouns and quantifiers ----
OIL = "Harga minyak dunia naik 2 persen pada Senin."
ADRO = "Saham ADRO naik 3 persen pada Senin."
RUPIAH = "Rupiah melemah 0,5 persen ke Rp16.500 per dolar AS pada Senin."
BBRI = "Saham BBRI turun 3 persen pada Senin."


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


@pytest.mark.parametrize("prose,source", [
    ("Harga minyak terkerek eskalasinya konflik Timur Tengah.", OIL),
    ("Harga minyak terkerek intensitasnya serangan di Laut Merah.", OIL),
    ("Saham ADRO terangkat ekspornya yang melonjak.", ADRO),
    ("Rupiah tertekan nilainya impor yang membengkak.", RUPIAH),
    ("Saham BBRI terseret mayoritas saham perbankan.", BBRI),
    ("Harga minyak terangkat payung kebijakan OPEC.", OIL),
])
def test_452_an_invented_cause_needs_a_quote(prose, source):
    assert not kept(prose, source)


def test_452_control_440_a_plain_movement_is_kept():
    assert kept("IHSG tertekan tajam pada perdagangan Senin.", "IHSG ditutup turun 1,2 persen ke level 7.100 pada Senin.")


# ---- #453 (SYS-186): a range of places without "pada" is refused as an end point ----
SRC_453 = "Asap meluas sejak Kamis (22/10). Rapat lanjutan belum dijadwalkan."


@pytest.mark.parametrize("prose", [
    "Asap meluas hingga Riau akhir Oktober.",
    "Bantuan disalurkan dari Sabang hingga Merauke akhir Oktober.",
])
def test_453_a_range_of_places_is_no_end_point(prose):
    assert sc.unbacked_end_times(prose, SRC_453) == []


def test_453_control_446_a_named_time_after_dari_name_is_refused():
    assert sc.unbacked_end_times("Diskon tiket dari Garuda Indonesia berlaku hingga Lebaran 2027.",
                                 "Maskapai memberi diskon tiket untuk penerbangan domestik.") != []


# ---- #454 (SYS-191): a true "diselesaikan pada <time>" is refused when the source restates the time ----
@pytest.mark.parametrize("prose,source", [
    ("Kasus itu diselesaikan pada Oktober 2026.", "Kasus itu diselesaikan secara damai pada Oktober 2026."),
    ("Sengketa diselesaikan pada 12 Oktober.", "Sengketa itu diselesaikan Senin (12/10)."),
    ("Naskah IEU-CEPA segera diselesaikan pada akhir September.",
     "\"Kalau itu bisa, ya mudah-mudahan akhir September selesai,\" ujarnya soal perundingan IEU-CEPA."),
])
def test_454_a_true_completion_date_is_kept(prose, source):
    assert sc.unbacked_end_times(prose, source) == []


def test_454_control_445_the_msci_false_end_is_refused():
    msci = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November "
            "2026. Freeze MSCI berpotensi berlanjut hingga semester II-2027.")
    assert sc.unbacked_end_times("Pembekuan diselesaikan pada November 2026.", msci) != []
