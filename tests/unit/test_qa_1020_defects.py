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


# ---- #417 (SYS-191): unlisted end openers ----
from newscrawler.core import source_check as sc  # noqa: E402

MSCI = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. "
        "Freeze MSCI berpotensi berlanjut hingga semester II-2027. Wilbert memperkirakan MSCI akan memperpanjang "
        "kebijakan pembekuan pada evaluasi November 2026.")


@pytest.mark.parametrize("prose", [
    "Pembekuan rampung pada November 2026.",
    "Pembekuan tuntas pada November 2026.",
    "Masa pembekuan habis pada November 2026.",
    "Pembekuan ditutup pada November 2026.",
])
def test_417_an_unstated_end_is_refused(prose):
    assert sc.unbacked_end_times(prose, MSCI) != []


def test_417_control_a_listed_opener_is_refused():
    assert sc.unbacked_end_times("Pembekuan dihentikan pada November 2026.", MSCI) != []


# ---- #418 (SYS-186): a spatial "hingga" is no end point ----
SRC_418 = "Asap meluas sejak Kamis (22/10). Rapat lanjutan belum dijadwalkan."


@pytest.mark.parametrize("prose", [
    "Sebelumnya, antrean kendaraan mengular hingga Cikampek pada akhir Oktober.",
    "Sebelumnya, banjir merendam permukiman hingga Kampung Melayu pada akhir Oktober.",
    "Sebelumnya, bantuan disalurkan dari Sabang hingga Merauke pada akhir Oktober.",
])
def test_418_a_spatial_hingga_is_no_end_point(prose):
    assert sc.unbacked_end_times(prose, SRC_418) == []


def test_418_control_a_listed_spread_verb_is_spatial():
    assert sc.unbacked_end_times("Sebelumnya, asap meluas hingga Riau pada akhir Oktober.", SRC_418) == []


# ---- #419 / #420 (SYS-177): plan cues of a latar schedule ----
from datetime import date  # noqa: E402

import newscrawler.core.story_arc as sa  # noqa: E402

DAY, ITEM = date(2026, 10, 8), date(2026, 10, 2)


@pytest.mark.parametrize("verb", ["diproyeksi", "diprakirakan", "disiapkan", "dicanangkan", "berpotensi",
                                  "diestimasikan"])
def test_419_a_plan_verb_makes_a_schedule(verb):
    assert sa.unbacked_times(f"Aturan barunya {verb} terbit awal Oktober.", DAY, {DAY, ITEM}, "") == ["awal Oktober"]


def test_419_control_a_listed_cue_makes_a_schedule():
    assert sa.unbacked_times("Aturan barunya dijanjikan terbit awal Oktober.", DAY, {DAY, ITEM}, "") == ["awal Oktober"]


@pytest.mark.parametrize("latar", [
    "Target penerimaan pajak tercapai pada awal Oktober.",
    "Mentan memastikan stok beras aman pada awal Oktober.",
    "Janji kampanye itu ditagih warga pada awal Oktober.",
])
def test_420_a_past_narration_is_no_schedule(latar):
    assert sa.unbacked_times(latar, DAY, {DAY, ITEM}, "") == []


def test_420_control_a_bare_past_narration_is_no_schedule():
    assert sa.unbacked_times("Penerimaan pajak tercapai pada awal Oktober.", DAY, {DAY, ITEM}, "") == []


# ---- #424 (SYS-153): a written-out date's year is checked ----
@pytest.mark.parametrize("prose,source", [
    ("Pada 24 September 2025 rapat digelar.", "Rapat digelar Rabu (24/9/2026)."),
    ("Kebijakan berlaku hingga 31 Desember 2027.", "Kebijakan berlaku hingga 31 Desember 2026."),
])
def test_424_an_invented_year_is_refused(prose, source):
    assert sc.unsupported_number(prose, source) is not None


def test_424_control_the_right_year_passes():
    assert sc.unsupported_number("Pada 24 September 2026 rapat digelar.", "Rapat digelar Rabu (24/9/2026).") is None
