"""SYS-152 (#342, ADR-018): a story arc's causal claim must rest on one quoted source sentence.

The six sentences are QA's hand-check of arcs-v5 (SYS-150 #340, digests/preview/arcs-v5/handcheck.csv), each with
the source text the arc model saw (scripts/experiments/sys152/dump_causal_fixtures.py, trimmed). MK is the
invented link: both halves are true, no source sentence joins them.
"""
import json

import pytest

import newscrawler.core.story_arc as sa
from newscrawler.core import causal_check as cc
from newscrawler.core.llm_json import Rejected
from tests.unit.test_story_arc import DAY, TEXTS, TIMELINE, _answer

PHK_SRC = ("63.789 Orang Kena PHK sejak Januari-September 2026 Kemnaker mencatat 63.789 pekerja terkena PHK sepanjang "
           "Januari-September 2026. Total PHK meningkat dari 53.490 orang hingga Agustus, namun Kemnaker menyatakan data "
           "enam bulan terakhir masih dinamis karena klaim dapat diajukan sampai enam bulan setelah PHK.")
BPIH_SRC = ("Tiket Pesawat Mahal, Kemenhaj Bahas Ulang Biaya Haji\nKementerian Haji dan Umrah tengah mengatur ulang "
            "pembiayaan haji. Hal itu dilakukan lantaran sejumlah komponen biaya haji disebut mengalami kenaikan, "
            "terutama mahalnya tiket pesawat akibat kenaikan harga avtur. \"Mau tidak mau kita harus hati-hati")
DEF_SRC = ("Suahasil Akui Defisit APBN 2026 Bisa Melebar ke 2,85% PDB, Ini Biang Keroknya\n- Menteri Keuangan Suahasil "
           "Nazara memproyeksikan defisit APBN 2026 meningkat menjadi 2,85 persen terhadap PDB di Jakarta. - Peningkatan "
           "proyeksi defisit tersebut disebabkan oleh tingginya dinamika ekonomi global, konflik geopolitik, serta "
           "fluktuasi harga komoditas.")
OMC_SRC = ("JAKARTA, KOMPAS.com - Plt. Kepala Pusat Data, Informasi dan Komunikasi Kebencanaan BNPB, Berton SP Panjaitan "
           "mengatakan, asap kebakaran hutan dan lahan (Karhutla) berdampak pada penerbangan di Bandara Internasional "
           "Sultan Mahmud Badaruddin II, Palembang, Sumatera Selatan. Hal ini menyebabkan operasi modifikasi cuaca (OMC) "
           "untuk mendatangkan hujan yang semula akan dilakukan dari Palembang dipindah ke Pangkal Pinang .")
MK_SRC = ("Hal tersebut disampaikan oleh Budianto setelah adanya putusan Mahkamah Konstitusi (MK) yang menyatakan gugatan "
          "ijazah Gibran tidak dapat diterima atau niet ontvankelijk verklaard (NO). Permohonan para pemohon dinyatakan "
          "tidak dapat diterima karena mereka tidak memiliki kedudukan hukum.")
OJOL_SRC = ("Menteri UMKM Ungkap Alasan Perpres Ojol Belum Terbit\nMenteri UMKM Maman Abdurrahman mengungkapkan alasan "
            "Peraturan Presiden (Perpres) mengenai ekosistem transportasi digital termasuk ojek daring ( ojol ) yang belum "
            "terbit. Salah satunya sednag mensinergikan dengan undang-undang lain")

PHK = ("Kini jumlahnya bertambah setelah data September masuk, dan Kemnaker menyatakan data enam bulan terakhir masih "
       "dinamis karena klaim dapat diajukan sampai enam bulan setelah PHK.")
BPIH = ("Sebelumnya, Kementerian Haji dan Umrah membahas ulang pembiayaan haji karena sejumlah komponen biaya naik, "
        "terutama tiket pesawat akibat kenaikan harga avtur.")
DEF = ("Setelah itu Suahasil memproyeksikan defisit APBN 2026 bisa melebar ke 2,85% PDB karena dinamika ekonomi global, "
       "konflik geopolitik, dan fluktuasi harga komoditas.")
OMC = ("Kemarin, 15 penerbangan kembali terganggu, dan kini OMC yang semula digelar dari Palembang dipindah ke Pangkal "
       "Pinang karena asap mengganggu operasi modifikasi cuaca.")
MK = ("MK menyatakan tidak menemukan bukti meyakinkan Gibran Rakabuming Raka memiliki ijazah setara SMA, tetapi tidak "
      "dapat mendiskualifikasinya karena permohonan tidak dapat diterima.")
OJOL = ("Sebelumnya, Menteri UMKM Maman Abdurrahman menyebut penyusunan regulasi cukup lama karena harus diselaraskan "
        "dengan aturan ketenagakerjaan serta lalu lintas dan angkutan jalan.")

PHK_Q = ("Total PHK meningkat dari 53.490 orang hingga Agustus, namun Kemnaker menyatakan data enam bulan terakhir masih "
         "dinamis karena klaim dapat diajukan sampai enam bulan setelah PHK.")
BPIH_Q = ("Kementerian Haji dan Umrah tengah mengatur ulang pembiayaan haji. Hal itu dilakukan lantaran sejumlah komponen "
          "biaya haji disebut mengalami kenaikan, terutama mahalnya tiket pesawat akibat kenaikan harga avtur.")
DEF_Q = ("Menteri Keuangan Suahasil Nazara memproyeksikan defisit APBN 2026 meningkat menjadi 2,85 persen terhadap PDB di "
         "Jakarta. - Peningkatan proyeksi defisit tersebut disebabkan oleh tingginya dinamika ekonomi global, konflik "
         "geopolitik, serta fluktuasi harga komoditas.")
OMC_Q = ("asap kebakaran hutan dan lahan (Karhutla) berdampak pada penerbangan di Bandara Internasional Sultan Mahmud "
         "Badaruddin II, Palembang, Sumatera Selatan. Hal ini menyebabkan operasi modifikasi cuaca (OMC) untuk "
         "mendatangkan hujan yang semula akan dilakukan dari Palembang dipindah ke Pangkal Pinang .")
MK_Q = "Permohonan para pemohon dinyatakan tidak dapat diterima karena mereka tidak memiliki kedudukan hukum."
OJOL_Q = "Salah satunya sednag mensinergikan dengan undang-undang lain"


def _problems(prose, quote, source):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: source})


class TestHandCheckedSentences:
    @pytest.mark.parametrize("prose,quote,source", [(PHK, PHK_Q, PHK_SRC), (BPIH, BPIH_Q, BPIH_SRC),
                                                    (DEF, DEF_Q, DEF_SRC), (OMC, OMC_Q, OMC_SRC)],
                             ids=["PHK", "BPIH", "Defisit", "OMC"])
    def test_a_true_cause_whose_sentence_is_quoted_is_kept(self, prose, quote, source):
        assert _problems(prose, quote, source) == []

    def test_mk_the_invented_link_is_refused(self):
        """Each half is true; the quoted sentence holds the cause half and a "karena", not the effect half."""
        assert cc.quote_in(MK_Q, MK_SRC) and cc.CAUSAL.search(MK_Q)
        [problem] = _problems(MK, MK_Q, MK_SRC)
        assert '"karena"' in problem and "sebab dan akibatnya sekaligus" in problem

    def test_mk_is_refused_on_the_two_sentence_source_the_replay_found(self):
        """The replay of 10-09 found this window: the first clause of MK's sentence and its cause are both in it,
        "mendiskualifikasi" is not. Widening the effect half to the first clause must not carry it."""
        window = ("MK dalam putusannya menyatakan tidak menemukan bukti meyakinkan yang menunjukkan Gibran memiliki "
                  "ijazah, sertifikat, atau diploma pendidikan luar negeri yang dapat dijadikan dasar penyetaraan dengan "
                  "pendidikan paling rendah tamat SMA atau sederajat. Namun, pada saat yang sama, MK menyatakan "
                  "permohonan para Pemohon tidak dapat diterima karena persoalan kedudukan hukum.")
        [span] = cc.causal_spans(MK)
        assert cc.overlap(span.before, window) >= cc.MIN_HALF_OVERLAP     # the widened half alone would pass
        assert not cc.supports(window, span) and _problems(MK, window, window)

    def test_a_glued_paragraph_is_no_quote(self):
        glued = ("Ray menyebut putusan MK sudah bisa ditebak.Dia mengaku sempat memprediksi gugatan itu tidak "
                 "dikabulkan." + " Kata dia, putusan itu bersayap." * 12 + " Gibran tidak didiskualifikasi karena itu.")
        assert not cc.quotable(glued)
        assert "70 kata" in cc.valid_quotes([(0, glued)], {0: glued})[1][0]

    def test_mk_is_refused_with_any_quote_from_its_source(self):
        for quote in cc.sentences(MK_SRC):
            assert _problems(MK, quote, MK_SRC)

    def test_ojol_a_fragment_without_a_causal_word_is_refused(self):
        """ADR-018's accepted false refusal: the source never states the cause, so the retry drops "karena"."""
        problems = _problems(OJOL, OJOL_Q, OJOL_SRC)
        assert len(problems) == 2 and "tidak memuat kata sebab-akibat" in problems[1]

    def test_both_causal_words_of_one_sentence_are_checked(self):
        assert [s.word for s in cc.causal_spans(BPIH)] == ["karena", "akibat"]


class TestQuote:
    def test_case_spacing_and_punctuation_do_not_decide(self):
        assert cc.quote_in("TOTAL PHK meningkat dari 53.490 orang hingga Agustus,namun Kemnaker", PHK_SRC)
        assert cc.quote_in("Rp 10 ribu", "harganya Rp10 ribu saja")

    def test_an_ellipsis_bridges_in_order_only(self):
        assert cc.quote_in("Kementerian Haji dan Umrah ... akibat kenaikan harga avtur", BPIH_SRC)
        assert not cc.quote_in("akibat kenaikan harga avtur ... Kementerian Haji dan Umrah", BPIH_SRC)

    def test_a_changed_word_is_not_in_the_source(self):
        assert not cc.quote_in("Permohonan para pemohon dinyatakan tidak dapat diterima karena MK tidak berwenang.",
                               MK_SRC)

    def test_more_than_two_sentences_are_refused(self):
        three = "Harga avtur naik. Tiket pesawat mahal. Karena itu biaya haji naik."
        good, problems = cc.valid_quotes([(0, three)], {0: three})
        assert good == [] and "lebih dari 2 kalimat" in problems[0]

    def test_a_quote_must_point_at_a_quotable_source(self):
        good, problems = cc.valid_quotes([(5, PHK_Q)], {0: PHK_SRC})
        assert good == [] and "bukan artikel terkait atau cuplikan alur" in problems[0]

    def test_an_empty_quote_is_not_in_any_source(self):
        assert not cc.quote_in("...", PHK_SRC)


class TestHalves:
    def test_a_sentence_opening_on_its_causal_word_takes_the_previous_sentence(self):
        text = "Harga avtur melonjak tajam pekan ini. Akibatnya, maskapai menaikkan tiket pesawat."
        [span] = cc.causal_spans(text)
        assert span.word == "Akibatnya" and span.before == "Harga avtur melonjak tajam pekan ini."
        assert "maskapai menaikkan tiket pesawat" in span.after

    def test_an_attribution_is_no_fact_of_either_half(self):
        text = "Rupiah melemah ke level terendah, yang menurut analis Phintraco Sekuritas dipicu aksi jual asing."
        [span] = cc.causal_spans(text)
        assert "Phintraco" not in span.before and "Rupiah melemah" in span.before

    def test_a_decimal_comma_is_no_clause_boundary(self):
        [span] = cc.causal_spans("Defisit melebar ke 2,85% PDB karena harga minyak naik.")
        assert span.before == "Defisit melebar ke 2,85% PDB"

    def test_a_forward_connective_is_checked_on_both_halves(self):
        source = "Harga avtur naik tajam sehingga maskapai menaikkan harga tiket pesawat."
        assert _problems("Harga avtur naik sehingga maskapai menaikkan tiket pesawat.", source, source) == []
        assert _problems("Harga avtur naik sehingga pemerintah menunda haji.", source, source)

    def test_dan_joining_names_is_no_clause_boundary(self):
        """Replay 10-11: "di Koto Tangah dan Kuranji" is one place list, not two clauses."""
        [_, span] = cc.causal_spans("Hujan deras memicu luapan sungai di Koto Tangah dan Kuranji, sehingga tim SAR "
                                    "mengevakuasi warga.")
        assert span.word == "sehingga" and "Koto Tangah dan Kuranji" in span.before_core

    def test_a_temporal_conjunction_opens_the_clause_next_to_the_causal_word(self):
        """Replay 10-08 (v4): the cause belongs to "Perpres Ojol disebut belum terbit", not to the frame before it."""
        [span] = cc.causal_spans("Penerbitan ini menuntaskan penantian panjang setelah Perpres Ojol disebut belum "
                                 "terbit karena masih sinkronisasi aturan pada pertengahan September.")
        assert span.before_core == "Perpres Ojol disebut belum terbit"
        source = "Perpres Ojol Tak Kunjung Terbit karena Masih Sinkronisasi Aturan"
        assert cc.supports(source, span)

    def test_a_half_sharing_only_half_its_words_is_refused(self):
        """The bar is 60%: "maskapai menghentikan" shares 1 of 2 content words with the source."""
        source = "Harga avtur naik tajam sehingga maskapai menaikkan harga tiket pesawat."
        assert cc.overlap("maskapai menghentikan", source) == 0.5
        assert _problems("Harga avtur naik sehingga maskapai menghentikan.", source, source)

    def test_generic_modal_words_never_carry_a_half(self):
        assert cc.overlap("tidak dapat mendiskualifikasinya", MK_Q) == 0.0

    def test_voice_and_nya_still_meet(self):
        assert cc.overlap("rapat ditunda", "Panitia menunda rapat itu.") == 1.0
        assert cc.overlap("mendiskualifikasinya", "MK tidak bisa mendiskualifikasi Gibran.") == 1.0

    def test_no_causal_word_needs_no_entry(self):
        assert cc.unbacked_causes([("latar", "Harga naik. Lalu rapat digelar.")], [], {}) == []


# ── End to end through story_arc.parse ─────────────────────────────────────────────────────────────

HARI_INI = "Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara, Senin (12/10). "


def _outcome(prose, sebab, extra=PHK_SRC, lenient=False):
    texts = [TEXTS[0] + " " + extra, *TEXTS[1:]]
    try:
        sa.parse(_answer(hari_ini=HARI_INI + prose, sebab=sebab), texts, TIMELINE, DAY, lenient=lenient)
    except Rejected as e:
        return e.reason
    return "kept"


class TestParse:
    def test_a_quoted_true_cause_is_kept(self):
        assert _outcome(PHK, [{"artikel": 0, "kutipan": PHK_Q}]) == "kept"

    def test_two_adjacent_sentences_are_one_quote(self):
        prose = "Kini OMC yang semula digelar dari Palembang dipindah ke Pangkal Pinang karena asap mengganggu operasi."
        assert _outcome(prose, [{"artikel": 0, "kutipan": OMC_Q}], extra=OMC_SRC) == "kept"

    def test_mk_is_refused_as_sebab(self):
        assert _outcome(MK, [{"artikel": 0, "kutipan": MK_Q}], extra=MK_SRC) == "sebab"

    def test_mk_is_still_refused_on_the_lenient_retry(self):
        assert _outcome(MK, [{"artikel": 0, "kutipan": MK_Q}], extra=MK_SRC, lenient=True) == "sebab"

    def test_a_causal_word_without_any_entry_is_refused(self):
        assert _outcome(PHK, []) == "sebab"

    def test_a_missing_sebab_field_with_a_causal_word_is_refused(self):
        texts = [TEXTS[0] + " " + PHK_SRC, *TEXTS[1:]]
        with pytest.raises(Rejected) as e:
            sa.parse(_answer(hari_ini=HARI_INI + PHK), texts, TIMELINE, DAY)
        assert e.value.reason == "sebab"

    def test_an_attributed_but_invented_cause_is_refused(self):
        prose = "Menurut Kemnaker, PHK bertambah karena harga avtur naik."
        assert _outcome(prose, [{"artikel": 0, "kutipan": PHK_Q}]) == "sebab"

    def test_a_fabricated_quote_is_refused(self):
        fake = "Kemnaker menyatakan data enam bulan terakhir masih dinamis karena banyak pabrik tutup."
        assert _outcome("Kemnaker menyatakan data masih dinamis karena banyak pabrik tutup.",
                        [{"artikel": 0, "kutipan": fake}]) == "sebab"

    def test_a_quote_from_an_unrelated_article_is_refused(self):
        """[2] is tidak_terkait in the fixture: its sentences back nothing in the arc."""
        texts = [*TEXTS[:2], TEXTS[2] + " " + PHK_SRC]
        with pytest.raises(Rejected) as e:
            sa.parse(_answer(hari_ini=HARI_INI + PHK, sebab=[{"artikel": 2, "kutipan": PHK_Q}]), texts, TIMELINE,
                     DAY)
        assert e.value.reason == "sebab" and "bukan artikel terkait" in e.value.detail

    @pytest.mark.parametrize("bad", ["PHK", [{"artikel": "0", "kutipan": PHK_Q}], [{"artikel": 0}],
                                     [{"artikel": True, "kutipan": PHK_Q}], [PHK_Q]])
    def test_a_malformed_sebab_is_json(self, bad):
        assert _outcome(PHK, bad) == "json"

    def test_an_arc_without_causal_words_needs_no_sebab(self):
        assert _outcome("Kebakaran mengganggu 1.673 penerbangan domestik.", None) == "kept"

    def test_the_prompt_asks_for_sebab_first_and_its_example_has_none(self):
        assert '"sebab": [{"artikel": 1' in sa.PROMPT.replace("{{", "{")
        block = sa.PROMPT.split("CONTOH JAWABAN")[1].split("HARI INI\n")[0]
        example = json.loads(" ".join(block[block.index("{{"):block.rindex("}}") + 2].split())
                             .replace("{{", "{").replace("}}", "}"))
        assert list(example)[0] == "sebab" and example["sebab"] == []

    def test_sebab_is_a_refusal_reason(self):
        assert "sebab" in sa.REASONS
