"""QA 2026-10-19: QA's own held-out tests for the 13 arc tickets the dev marked ready-for-qa on 2026-10-18
(ADR-020: SYS-181, SYS-183, SYS-185, SYS-187, SYS-188, SYS-189, SYS-192; time checks: SYS-177, SYS-186, SYS-190,
SYS-191, SYS-193; DBT-83 is checked by mutants).

Written from the tickets' text and ADR-020, before reading the dev's unit tests. No input here is in tests/unit or
in QA's earlier files: each class uses a held-out sentence of the ticket's own symptom class, plus controls (true
claims) so a fix cannot over-correct.

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_19/test_qa_1019_arcs.py -q -p no:cacheprovider

Run from a tree copy at 40a2edc (the baseline) to see which tests catch the original defects.
"""
import json
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import newscrawler.core.story_arc as sa  # noqa: E402
from newscrawler.core import causal_check as cc  # noqa: E402
from newscrawler.core import source_check as sc  # noqa: E402
from newscrawler.core.llm_json import Rejected  # noqa: E402
from tests.unit.test_story_arc import DAY, FRAME, TEXTS, TIMELINE, _answer  # noqa: E402


def kept(prose, quote, source=None):
    source = quote if source is None else source
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: source}) == []


# ── SYS-188: every word of a half covered; a swapped subject is refused ───────────────────────────────

class TestQaSys188HeldOut:
    @pytest.mark.parametrize("prose,src", [
        ("Laba BBNI naik karena penyaluran kredit tumbuh.", "Laba BMRI naik karena penyaluran kredit tumbuh."),
        ("Kenaikan harga minyak memicu inflasi di Jepang.", "Kenaikan harga minyak memicu inflasi di Korea Selatan."),
        ("Rupiah melemah karena data inflasi AS.", "Rupiah melemah karena data inflasi China."),
        ("Harga emas naik akibat ketegangan di Timur Tengah.", "Harga minyak naik akibat ketegangan di Timur Tengah."),
    ])
    def test_a_swapped_subject_is_refused(self, prose, src):
        assert not kept(prose, src)

    def test_an_added_qualifier_is_refused(self):
        """Owner rule: a half may drop words of its source, never add one."""
        assert not kept("Harga beras naik karena cuaca buruk di Jawa Barat.", "Harga beras naik karena cuaca buruk.")

    def test_a_shorter_true_claim_is_kept(self):
        assert kept("Harga beras naik karena cuaca buruk.",
                    "Harga beras medium naik 5 persen karena cuaca buruk di sentra produksi.")

    def test_a_quantifier_weighs_nothing(self):
        assert kept("Sebanyak 200 rumah terendam karena tanggul jebol.", "200 rumah terendam karena tanggul jebol.")


# ── SYS-181: name room and the anaphor ─────────────────────────────────────────────────────────────

class TestQaSys181HeldOut:
    def test_swapped_places_forward_word(self):
        assert not kept("Gempa di Cianjur menyebabkan kerusakan di Sukabumi.",
                        "Gempa di Sukabumi menyebabkan kerusakan di Cianjur.")

    def test_swapped_places_akibat(self):
        assert not kept("Penerbangan di Pekanbaru terganggu akibat asap dari Jambi.",
                        "Penerbangan di Jambi terganggu akibat asap dari Pekanbaru.")

    def test_the_true_place_order_is_kept(self):
        assert kept("Penerbangan di Jambi terganggu akibat asap dari Pekanbaru.",
                    "Penerbangan di Jambi terganggu akibat asap dari Pekanbaru.")

    def test_an_anaphor_subject_sharing_a_word_does_not_lend_the_whole_previous_sentence(self):
        """The anaphor's subject ("Penurunan saham BBRI tersebut") shares words with the previous sentence, so
        the previous sentence is lent; but the source states foreign selling caused BBRI's fall, not the IHSG's."""
        src = ("IHSG turun 1 persen dan saham BBRI turun 3 persen pada Senin. Penurunan saham BBRI tersebut dipicu "
               "aksi jual asing.")
        assert not kept("IHSG turun karena aksi jual asing.", src)

    def test_the_anaphors_own_subject_is_kept(self):
        src = ("IHSG turun 1 persen dan saham BBRI turun 3 persen pada Senin. Penurunan saham BBRI tersebut dipicu "
               "aksi jual asing.")
        assert kept("Saham BBRI turun karena aksi jual asing.", src)


# ── SYS-189: causal verbs outside the old table ────────────────────────────────────────────────────

NO_REASON = "Rupiah melemah 0,5 persen ke Rp16.500 per dolar AS pada Senin."


class TestQaSys189HeldOut:
    @pytest.mark.parametrize("prose", [
        "Rupiah melemah, ditopang data tenaga kerja AS yang kuat.",
        "Rupiah melemah, dilatarbelakangi data tenaga kerja AS yang kuat.",
        "Pelemahan rupiah bermula dari data tenaga kerja AS yang kuat.",
        "Data tenaga kerja AS yang kuat menekan rupiah.",
        "Data tenaga kerja AS yang kuat memengaruhi rupiah.",
        "Data tenaga kerja AS yang kuat menimbulkan pelemahan rupiah.",
        "Rupiah melemah berkat data tenaga kerja AS yang kuat.",
    ])
    def test_an_invented_link_with_a_listed_verb_is_refused(self, prose):
        assert not kept(prose, NO_REASON)

    @pytest.mark.parametrize("prose", [
        "Rupiah melemah imbas data tenaga kerja AS yang kuat.",
        "Rupiah melemah, terimbas data tenaga kerja AS yang kuat.",
        "Rupiah melemah, dipacu data tenaga kerja AS yang kuat.",
        "Rupiah melemah, terdorong data tenaga kerja AS yang kuat.",
        "Rupiah melemah, buntut data tenaga kerja AS yang kuat.",
    ])
    def test_unlisted_causal_forms_of_market_copy(self, prose):
        """Held-out forms the ticket did not name (imbas/terimbas/dipacu/terdorong/buntut). A failure here is a
        new finding of SYS-189's class, not a send-back of the listed forms."""
        assert not kept(prose, NO_REASON)

    def test_a_purpose_mendorong_needs_no_quote(self):
        assert kept("Pemerintah berupaya mendorong ekspor nikel.", NO_REASON)

    def test_a_purpose_menekan_needs_no_quote(self):
        assert kept("BI menaikkan suku bunga guna menekan inflasi.", NO_REASON)

    def test_a_true_seiring_link_is_kept(self):
        src = "Rupiah menguat seiring penurunan ekspektasi kenaikan suku bunga Fed."
        assert kept("Rupiah menguat seiring penurunan ekspektasi kenaikan suku bunga Fed.", src)


# ── SYS-185: lexical and frame negation ────────────────────────────────────────────────────────────

AVTUR = "Harga tiket pesawat domestik naik tajam karena harga avtur melonjak sepanjang Oktober."


class TestQaSys185HeldOut:
    @pytest.mark.parametrize("prose", [
        "Harga tiket pesawat domestik tak jadi naik karena harga avtur melonjak.",
        "Harga tiket pesawat domestik urung naik karena harga avtur melonjak.",
        "Harga tiket pesawat domestik naik tajam tanpa dipicu harga avtur.",
    ])
    def test_a_negated_claim_is_refused(self, prose):
        assert not kept(prose, AVTUR)

    @pytest.mark.parametrize("src", [
        "Maskapai menyangkal harga tiket pesawat domestik naik karena harga avtur melonjak.",
        "Kemenhub menampik harga tiket pesawat domestik naik karena harga avtur melonjak.",
        "Anggapan bahwa harga tiket pesawat domestik naik karena harga avtur melonjak dibantah maskapai.",
    ])
    def test_a_denied_source_link_backs_no_flat_claim(self, src):
        assert not kept("Harga tiket pesawat domestik naik karena harga avtur melonjak.", src)

    def test_a_negation_on_both_sides_is_kept(self):
        src = "Sebanyak 20 kapal nelayan tidak melaut karena cuaca buruk."
        assert kept("Sebanyak 20 kapal nelayan tidak melaut karena cuaca buruk.", src)


# ── SYS-192: a hedge dropped ───────────────────────────────────────────────────────────────────────

FIRE = "Kebakaran gudang itu dipicu korsleting listrik."


class TestQaSys192HeldOut:
    @pytest.mark.parametrize("src", [
        "Kebakaran gudang itu disinyalir dipicu korsleting listrik.",
        "Kebakaran gudang itu ditengarai dipicu korsleting listrik.",
        "Dugaan sementara, kebakaran gudang itu dipicu korsleting listrik.",
        "Polisi menduga kebakaran gudang itu dipicu korsleting listrik.",
        "Ada indikasi kebakaran gudang itu dipicu korsleting listrik.",
    ])
    def test_a_listed_hedge_dropped_is_refused(self, src):
        assert not kept(FIRE, src)

    @pytest.mark.parametrize("src", [
        "Kebakaran gudang itu diperkirakan dipicu korsleting listrik.",
        "Kebakaran gudang itu diyakini dipicu korsleting listrik.",
        "Kebakaran gudang itu disebut-sebut dipicu korsleting listrik.",
    ])
    def test_unlisted_hedges(self, src):
        """Held-out hedges outside the dev's list. A failure is a new finding of SYS-192's class."""
        assert not kept(FIRE, src)

    def test_the_claim_may_hedge_a_flat_source(self):
        assert kept("Kebakaran gudang itu diduga dipicu korsleting listrik.", FIRE)


# ── SYS-187: every item of a list checked ──────────────────────────────────────────────────────────

class TestQaSys187HeldOut:
    @pytest.mark.parametrize("prose", [
        "Harga cabai naik karena cuaca buruk, gagal panen, dan distribusi terganggu.",
        "Harga cabai naik karena cuaca buruk, termasuk gagal panen di Brebes.",
        "Harga cabai naik karena cuaca buruk serta gagal panen di Brebes.",
    ])
    def test_an_invented_item_after_the_first_is_refused(self, prose):
        assert not kept(prose, "Harga cabai naik karena cuaca buruk.")

    def test_an_invented_effect_list_is_refused(self):
        assert not kept("Banjir menyebabkan jalan terputus, listrik padam, dan sekolah diliburkan.",
                        "Banjir menyebabkan jalan terputus.")

    def test_an_invented_sehingga_list_is_refused(self):
        assert not kept("Hujan deras mengguyur Bogor sehingga jalan tergenang, KRL terhenti.",
                        "Hujan deras mengguyur Bogor sehingga jalan tergenang.")

    def test_a_true_list_is_kept(self):
        src = "Harga cabai naik karena cuaca buruk, gagal panen, dan distribusi terganggu."
        assert kept("Harga cabai naik karena cuaca buruk, gagal panen, dan distribusi terganggu.", src)

    def test_a_trailing_ujar_is_attribution(self):
        assert kept("Harga cabai naik karena cuaca buruk, ujar Kepala Dinas Perdagangan.",
                    "Harga cabai naik karena cuaca buruk.")

    def test_an_attribution_in_the_middle_does_not_hide_an_item(self):
        assert not kept("Harga cabai naik karena cuaca buruk, kata pedagang, dan gagal panen di Brebes.",
                        "Harga cabai naik karena cuaca buruk.")


# ── SYS-183: a fronted cause ───────────────────────────────────────────────────────────────────────

class TestQaSys183HeldOut:
    def test_an_invented_effect_after_akibat_is_refused(self):
        assert not kept("Hujan deras mengguyur Jakarta sejak pagi. Akibat hujan deras, sekolah diliburkan.",
                        "Hujan deras mengguyur Jakarta sejak pagi karena dipicu siklon tropis di Samudra Hindia.")

    def test_an_invented_effect_after_lantaran_is_refused(self):
        assert not kept("Lantaran cuaca buruk, harga cabai naik.", "Kapal nelayan tidak melaut karena cuaca buruk.")

    def test_a_true_fronted_cause_with_negation_is_kept(self):
        assert kept("Karena cuaca buruk, 20 kapal nelayan tidak melaut.",
                    "Sebanyak 20 kapal nelayan tidak melaut karena cuaca buruk.")

    def test_a_fronted_cause_list_is_checked_whole(self):
        assert not kept("Karena cuaca buruk dan gagal panen, harga cabai naik.", "Harga cabai naik karena cuaca buruk.")

    def test_karena_itu_still_refers_back(self):
        assert kept("Harga avtur melonjak. Karena itu, harga tiket pesawat domestik naik.", AVTUR)


# ── SYS-186 / SYS-191 / SYS-193: end points ───────────────────────────────────────────────────────

MSCI = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. "
        "Freeze MSCI berpotensi berlanjut hingga semester II-2027. Wilbert memperkirakan MSCI akan memperpanjang "
        "kebijakan pembekuan pada evaluasi November 2026.")


class TestQaEndPointsHeldOut:
    @pytest.mark.parametrize("prose", [
        "Pembekuan diperkirakan bertahan sampai review November 2026.",                  # sampai + 1 gap word
        "Pembekuan berlangsung hingga periode evaluasi November 2026.",                  # 2 gap words
        "Pembekuan berlaku sampai dengan November 2026.",
        "Pembekuan berakhir November 2026.",                                             # berakhir without pada
        "Pembekuan selesai pada November 2026.",
        "Pembekuan berlanjut hingga akhir November 2026.",                               # a month part
        "Pembekuan berlanjut hingga kuartal IV 2026.",
        "Pembekuan berlanjut hingga Desember 2026.",
    ])
    def test_the_msci_false_end_held_out(self, prose):
        assert sc.unbacked_end_times(prose, MSCI) != []

    @pytest.mark.parametrize("prose", [
        "Pembekuan dihentikan pada November 2026.",
        "Pembekuan diakhiri pada November 2026.",
        "Pembekuan hanya bertahan paling lambat November 2026.",
    ])
    def test_unlisted_end_verbs(self, prose):
        """Held-out end verbs outside SYS-191's opener list. A failure is a new finding of its class."""
        assert sc.unbacked_end_times(prose, MSCI) != []

    @pytest.mark.parametrize("prose", ["Pembekuan berlanjut hingga semester II 2027.",
                                       "Pembekuan berpotensi berlanjut sampai semester II 2027."])
    def test_the_stated_end_is_kept(self, prose):
        assert sc.unbacked_end_times(prose, MSCI) == []

    def test_a_source_berakhir_pada_backs_a_hingga(self):
        assert sc.unbacked_end_times("Program diskon tarif berlanjut hingga Juni 2027.",
                                     "Program diskon tarif berakhir pada Juni 2027.") == []

    def test_sys193_a_fronted_end_point_needs_its_subject_too(self):
        """"Hingga 2026, pembekuan saham berlanjut" is the SYS-193 false end, fronted: the clause before the opener
        is empty, so the dev's rule matches the time alone."""
        src = ("Defisit APBN hingga September 2026 mencapai Rp319 triliun. Pembekuan saham berlanjut setelah "
               "evaluasi November 2026.")
        assert sc.unbacked_end_times("Hingga 2026, pembekuan saham berlanjut.", src) != []

    def test_sys193_one_generic_shared_word_is_not_the_subject(self):
        """The shared root is "saham" only; the source's end belongs to retail stock sales."""
        src = ("Penjualan saham ritel hingga September 2026 naik 12 persen. Pembekuan saham berlanjut setelah "
               "evaluasi November 2026.")
        assert sc.unbacked_end_times("Pembekuan saham berlanjut hingga 2026.", src) != []

    @pytest.mark.parametrize("prose,src", [
        ("Inflasi tertahan hingga 2026.", "Defisit APBN hingga Oktober 2026 mencapai Rp350 triliun."),
    ])
    def test_sys193_another_subject_does_not_back(self, prose, src):
        assert sc.unbacked_end_times(prose, src) != []

    def test_sys193_the_period_to_date_subject_backs(self):
        assert sc.unbacked_end_times("Defisit APBN hingga Oktober 2026 mencapai Rp350 triliun.",
                                     "Defisit APBN hingga 31 Oktober 2026 mencapai Rp350 triliun.") == []


# ── SYS-190: a whole future month or period, judged by field ──────────────────────────────────────

KAMIS_LINE = "Rapat lanjutan dijadwalkan Kamis (15/10)."
NONE = "Rapat lanjutan belum dijadwalkan."
HARI_INI = "Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara. "
LATAR = FRAME + "Pada 23/9 Seskab melaporkan 209 hektare lahan masih terbakar."


def _texts(sentence=NONE):
    return [TEXTS[0].replace(KAMIS_LINE, sentence), *TEXTS[1:]]


def _outcome(answer, texts=None, day=DAY):
    try:
        arc = sa.parse(answer, _texts() if texts is None else texts, TIMELINE, day)
    except Rejected as e:
        return e.reason
    return "kept" if json.loads(answer).get("agenda", "") == arc.agenda else "dropped"


def _field(field, value):
    data = {"agenda": ""}
    if field == "latar":
        data[field] = LATAR + " " + value
    elif field == "hari_ini":
        data[field] = HARI_INI + value
    else:
        data[field] = value
    return _answer(**data)


class TestQaSys190HeldOut:
    @pytest.mark.parametrize("phrase", ["Januari 2027", "Desember nanti", "Desember tahun ini", "pada bulan Desember 2026",
                                        "kuartal keempat 2026", "semester kedua 2026", "triwulan IV 2026",
                                        "awal 2027", "pertengahan 2027"])
    @pytest.mark.parametrize("field", ["agenda", "hari_ini"])
    def test_a_held_out_future_period_is_refused(self, field, phrase):
        """The source states the year 2027 and the ordinal 4 for something else, so the number guard passes and
        the period check alone must refuse the invented schedule."""
        texts = _texts(NONE + " Anggaran 2027 dibahas untuk keempat kalinya.")
        # "kuartal keempat" is refused by SYS-158's ordinal guard before the date check: any refusal counts
        assert _outcome(_field(field, f"Aturan karhutla dijadwalkan terbit {phrase}."), texts) not in ("kept", "dropped")

    @pytest.mark.parametrize("field,value", [
        ("sekilas", "Aturan karhutla terbit Desember."),
        ("judul", "Aturan karhutla terbit Desember"),
        ("latar", "Aturan karhutla dijadwalkan terbit Desember."),
    ])
    def test_the_other_fields(self, field, value):
        assert _outcome(_field(field, value)) == "date"

    def test_a_past_month_in_the_latar_stays(self):
        assert _outcome(_field("latar", "Pada September, Presiden menggelar rapat pertama soal karhutla.")) != "date"

    def test_a_stated_period_backs_it(self):
        assert _outcome(_field("agenda", "Aturan karhutla dijadwalkan terbit kuartal IV 2026."),
                        _texts("Aturan karhutla dijadwalkan terbit kuartal IV 2026.")) == "kept"

    def test_a_stated_date_inside_the_month_backs_the_month(self):
        assert _outcome(_field("agenda", "Aturan karhutla dijadwalkan terbit Desember."),
                        _texts("Aturan karhutla dijadwalkan terbit 15 Desember 2026.")) == "kept"


# ── SYS-177: the latar's cue, by clause ───────────────────────────────────────────────────────────

D26 = date(2026, 10, 26)
PAST = NONE + " Asap meluas sejak Kamis (22/10)."


class TestQaSys177HeldOut:
    @pytest.mark.parametrize("latar", [
        "Aturan barunya dijanjikan terbit akhir Oktober.",
        "Aturan barunya ditargetkan rampung dan terbit akhir Oktober.",
        "Aturan barunya dipastikan terbit akhir Oktober.",
        "Aturan barunya baru akan terbit akhir Oktober.",
        "Aturan barunya akan segera terbit akhir Oktober.",
    ])
    def test_a_held_out_future_cue_makes_it_a_schedule(self, latar):
        assert _outcome(_field("latar", latar), _texts(PAST), D26) == "date"

    @pytest.mark.parametrize("latar", ["Sebelumnya, asap meluas hingga Riau pada akhir Oktober.",
                                       "Asap mulai meluas ke Jambi akhir Oktober."])
    def test_past_narration_in_the_running_span_stays_backed(self, latar):
        assert _outcome(_field("latar", latar), _texts(PAST), D26) != "date"
