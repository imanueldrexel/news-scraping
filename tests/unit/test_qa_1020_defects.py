"""QA's failing tests from the 2026-10-20 audit (qa-defects #401, #413-#424), copied unchanged from the issues.

Only the layout differs: one module, the issues' imports at the top, each issue's helpers and tests under its number
(a helper two issues share by name is suffixed with the issue's number). `sys.path.insert(0, os.getcwd())` is not
needed under pytest's rootdir.
"""
import pytest

from newscrawler.core import causal_check as cc


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


# ---- #401 (SYS-189): unlisted causal forms need no quote ----
NO_REASON = "Rupiah melemah 0,5 persen ke Rp16.500 per dolar AS pada Senin."


@pytest.mark.parametrize("prose", [
    "Rupiah melemah, terimbas data tenaga kerja AS yang kuat.",
    "Rupiah melemah, dipacu data tenaga kerja AS yang kuat.",
    "Rupiah melemah, terdorong data tenaga kerja AS yang kuat.",
    "Rupiah melemah, buntut data tenaga kerja AS yang kuat.",
])
def test_401_an_invented_link_is_refused(prose):
    assert not kept(prose, NO_REASON)


def test_401_control_a_listed_form_is_refused():
    assert not kept("Rupiah melemah, didorong data tenaga kerja AS yang kuat.", NO_REASON)


# ---- #413 (SYS-189): market-copy causal verbs need no quote ----
IHSG_NO_REASON = "IHSG ditutup turun 1,2 persen ke level 7.100 pada Senin."
RUPIAH_NO_REASON = "Rupiah melemah 0,5 persen ke Rp16.500 per dolar AS pada Senin."


@pytest.mark.parametrize("prose,source", [
    ("IHSG turun, tertekan aksi jual investor asing.", IHSG_NO_REASON),
    ("IHSG turun, ditekan aksi jual investor asing.", IHSG_NO_REASON),
    ("IHSG turun, terseret aksi jual investor asing.", IHSG_NO_REASON),
    ("IHSG turun, terbebani aksi jual investor asing.", IHSG_NO_REASON),
    ("IHSG naik, terangkat aksi beli investor asing.", IHSG_NO_REASON),
    ("IHSG naik, terkerek aksi beli investor asing.", IHSG_NO_REASON),
    ("Rupiah melemah, terpengaruh data tenaga kerja AS yang kuat.", RUPIAH_NO_REASON),
])
def test_413_an_invented_link_is_refused(prose, source):
    assert not kept(prose, source)


def test_413_control_a_listed_form_is_refused():
    assert not kept("IHSG turun, didorong aksi jual investor asing.", IHSG_NO_REASON)


# ---- #414 (SYS-192): unlisted hedges are dropped ----
FACT = "Kebakaran gudang itu dipicu korsleting listrik."


@pytest.mark.parametrize("src", [
    "Kebakaran gudang itu diprediksi dipicu korsleting listrik.",
    "Kebakaran gudang itu dicurigai dipicu korsleting listrik.",
    "Kebakaran gudang itu dikabarkan dipicu korsleting listrik.",
    "Kebakaran gudang itu tampaknya dipicu korsleting listrik.",
    "Kebakaran gudang itu barangkali dipicu korsleting listrik.",
    "Kebakaran gudang itu ditaksir dipicu korsleting listrik.",
])
def test_414_a_dropped_hedge_is_refused(src):
    assert not kept(FACT, src)


def test_414_control_a_listed_hedge_is_refused():
    assert not kept(FACT, "Kebakaran gudang itu diperkirakan dipicu korsleting listrik.")


# ---- #415 (SYS-185): unlisted denials do not negate the link ----
CLAIM = "Harga tiket pesawat domestik naik karena harga avtur melonjak."


@pytest.mark.parametrize("src", [
    "Maskapai menolak anggapan harga tiket pesawat domestik naik karena harga avtur melonjak.",
    "Maskapai menyatakan tidak tepat bahwa harga tiket pesawat domestik naik karena harga avtur melonjak.",
    "Maskapai menyebut tidak betul harga tiket pesawat domestik naik karena harga avtur melonjak.",
])
def test_415_a_denied_link_backs_no_flat_claim(src):
    assert not kept(CLAIM, src)


def test_415_control_a_listed_denial_is_read():
    assert not kept(CLAIM, "Maskapai menyangkal harga tiket pesawat domestik naik karena harga avtur melonjak.")


# ---- #416 (SYS-181): two names joined by "dan" in one clause ----
SRC_416 = "Saham BBRI dan BMRI turun pada Senin. Penurunan saham BMRI tersebut dipicu aksi jual asing."


def test_416_the_other_name_is_not_backed_through_the_anaphor():
    assert not kept("Saham BBRI turun karena aksi jual asing.", SRC_416)


def test_416_control_the_anaphors_own_name_stays_kept():
    assert kept("Saham BMRI turun karena aksi jual asing.", SRC_416)
