"""QA's failing tests from the 2026-11-11 audit (qa-defects #458, #459, #460, #461), copied unchanged from the issues.

Only the layout differs: one module, the issues' imports at the top, each issue's constants and tests under its number
(each test is prefixed with the issue's number). `sys.path.insert(0, os.getcwd())` is not needed under pytest's
rootdir.
"""
import json
from datetime import date

import pytest

from newscrawler.core import causal_check as cc
from newscrawler.core import source_check as sc
from newscrawler.core import story_arc as sa
from newscrawler.core.llm_json import Rejected


# ---- #458 (#387, SYS-186): a named event before a month after "dari <name>" is read as a place ----
MSCI = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. "
        "Freeze MSCI berpotensi berlanjut hingga semester II-2027.")
PROMO = "Maskapai memberi diskon tiket untuk penerbangan domestik."


@pytest.mark.parametrize("prose,source", [
    ("Pembekuan dari MSCI berlaku hingga Review November 2026.", MSCI),
    ("Diskon tiket dari Garuda Indonesia berlaku hingga Lebaran Maret 2027.", PROMO),
    ("Keringanan dari OJK berlaku hingga RDK Desember 2026.", "OJK memberi keringanan kredit bagi debitur."),
])
def test_458_a_named_event_before_a_month_is_an_end_point(prose, source):
    assert sc.unbacked_end_times(prose, source) != []


def test_458_control_453_a_place_before_a_month_is_no_end_point():
    assert sc.unbacked_end_times("Bantuan disalurkan dari Sabang hingga Merauke akhir Oktober.",
                                 "Asap meluas sejak Kamis (22/10). Rapat lanjutan belum dijadwalkan.") == []


def test_458_control_446_a_named_time_before_a_year_is_an_end_point():
    assert sc.unbacked_end_times("Diskon tiket dari Garuda Indonesia berlaku hingga Lebaran 2027.", PROMO) != []


# ---- #459 (#392, SYS-191): a shifted time-first completion backs "diselesaikan pada <time>" ----
AUDIT = "Audit diselesaikan pada Desember 2026."
BRIDGE = "Pembangunan jembatan diselesaikan pada Desember 2026."


@pytest.mark.parametrize("prose,source", [
    (AUDIT, "Audit itu dimulai setelah Desember 2026 selesai."),
    (AUDIT, "Audit baru dimulai sesudah Desember 2026 selesai."),
    (AUDIT, "Audit dijadwalkan sebelum Desember 2026 selesai."),
    (AUDIT, "Audit tidak boleh molor melewati Desember 2026 rampung."),
    (BRIDGE, "Pembangunan jembatan dilanjutkan setelah musim hujan Desember 2026 selesai."),
    (BRIDGE, "Pembangunan jembatan dimulai usai Desember 2026 selesai."),
])
def test_459_a_shifted_time_backs_no_completion(prose, source):
    assert sc.unbacked_end_times(prose, source) != []


def test_459_control_454_a_time_first_completion_is_kept():
    assert sc.unbacked_end_times("Kasus itu diselesaikan pada Oktober 2026.", "Pada Oktober 2026 kasus itu selesai.") == []


# ---- #460 (#390, SYS-189): movement_words.txt holds "sejalan", so "tertekan sejalan dengan <cause>" needs no quote ----
IHSG = "IHSG ditutup turun 1,2 persen ke level 7.100 pada Senin."
BBCA = "Saham BBCA naik 3 persen pada Senin."
RUPIAH = "Rupiah melemah 0,5 persen ke Rp16.500 per dolar AS pada Senin."


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


@pytest.mark.parametrize("prose,source", [
    ("IHSG tertekan sejalan dengan pelemahan bursa Asia.", IHSG),
    ("Saham BBCA terangkat sejalan dengan kenaikan laba kuartal III.", BBCA),
    ("Rupiah terseret sejalan pelemahan mata uang regional.", RUPIAH),
])
def test_460_an_unquoted_sejalan_cause_is_refused(prose, source):
    assert not kept(prose, source)


def test_460_control_the_listed_synonym_seiring_is_refused():
    assert not kept("IHSG tertekan seiring dengan pelemahan bursa Asia.", IHSG)


def test_460_control_a_plain_movement_is_kept():
    assert kept("IHSG tertekan tajam pada perdagangan Senin.", IHSG)


# ---- #461 (#457, SYS-203): the repair cuts inside a sentence at an abbreviation or initial ----
DAY = date(2026, 11, 9)
ART = ("Perum Bulog menyalurkan beras SPHP ke pasar tradisional di Jakarta. Direktur Utama Bulog Ahmad R. Rizal "
       "meninjau penyaluran itu. Penyaluran tertuang dalam surat edaran Bulog No. 104 tahun ini. Stok beras nasional "
       "disebut mencukupi.")
SHOWN = [ART, "Timnas Indonesia menang atas Vietnam di Stadion Gelora Bung Karno."]
# 60 words of whole sentences; each tail below brings the latar to 71 (> LIMITS["latar"] = 70).
BASE = ("Harga beras di pasar tradisional menjadi perhatian pedagang dan warga Jakarta yang setiap hari membeli beras "
        "bagi kebutuhan rumah tangga di berbagai wilayah ibu kota. Bulog menyebut stok beras nasional mencukupi, dan "
        "penyaluran beras SPHP menjangkau banyak pasar tradisional di Jakarta serta kota lain di sekitarnya yang "
        "menjadi pusat belanja warga. Warga ibu kota menyambut beras SPHP itu dengan antusias.")


def answer(latar):
    return json.dumps({"sebab": [], "judul": "Bulog salurkan beras SPHP ke pasar Jakarta",
                       "hari_ini": "Perum Bulog menyalurkan beras SPHP ke pasar tradisional di Jakarta.",
                       "latar": latar, "agenda": "", "sekilas": "Bulog salurkan beras SPHP ke pasar tradisional Jakarta.",
                       "terkait": [0], "tidak_terkait": [1], "alur": []}, ensure_ascii=False)


@pytest.mark.parametrize("tail", [
    "Penyaluran itu ditinjau langsung oleh Direktur Utama Bulog Ahmad R. Rizal.",
    "Penyaluran itu tertuang dalam surat edaran Bulog No. 104 tahun ini.",
])
def test_461_a_length_repair_never_cuts_inside_a_sentence(tail):
    a = answer(f"{BASE} {tail}")
    with pytest.raises(Rejected) as refused:
        sa.parse(a, SHOWN, [], DAY)
    assert refused.value.reason == "length"
    arc = sa.repair([a], [refused.value], SHOWN, [], DAY)
    # Either the whole last sentence goes (the latar is BASE) or the story falls back (None); never a fragment.
    assert arc is None or arc.latar == BASE, arc.latar


def test_461_control_a_plain_trailing_sentence_is_dropped_whole():
    tail = "Pedagang beras di pasar tradisional Jakarta menyambut penyaluran itu dengan antusias pagi tadi."
    a = answer(f"{BASE} {tail}")
    with pytest.raises(Rejected) as refused:
        sa.parse(a, SHOWN, [], DAY)
    arc = sa.repair([a], [refused.value], SHOWN, [], DAY)
    assert arc is not None and arc.latar == BASE
