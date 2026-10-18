"""SYS-152 (#342, ADR-018, ADR-019): a story arc's causal claim must rest on one link of one quoted source sentence.

The six sentences are QA's hand-check of arcs-v5 (SYS-150 #340, digests/preview/arcs-v5/handcheck.csv), each with
the source text the arc model saw (scripts/experiments/sys152/dump_causal_fixtures.py, trimmed). MK is the
invented link: both halves are true, no source sentence joins them. Since ADR-019 (owner, 2026-10-17: strict per
half) OMC is refused too: its cause half is mostly the source's effect. Since ADR-020 (owner, 2026-10-18: every word
of a half covered) BPIH and Defisit are refused as well, each on one paraphrased verb.
"""
import json

import pytest

import newscrawler.core.story_arc as sa
from newscrawler.core import causal_check as cc
from newscrawler.core import story_words
from newscrawler.core.llm_json import Rejected
from tests.unit.test_story_arc import DAY, N, TEXTS, TIMELINE, _answer

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
    def test_a_true_cause_whose_sentence_is_quoted_is_kept(self):
        assert _problems(PHK, PHK_Q, PHK_SRC) == []

    @pytest.mark.parametrize("prose,quote,source,link_word,word", [(BPIH, BPIH_Q, BPIH_SRC, "lantaran", "membahas"),
                                                                   (DEF, DEF_Q, DEF_SRC, "disebabkan", "melebar")],
                             ids=["BPIH", "Defisit"])
    def test_a_paraphrased_verb_is_refused(self, prose, quote, source, link_word, word):
        """ADR-020's accepted false refusals (owner, 2026-10-18: "Every word covered"). The causes are true, but
        the prose says "membahas" where the source says "mengatur", and "melebar" where it says "meningkat". Each
        claim's effect misses that one word and nothing else; the retry writes the two facts apart."""
        claim = cc.causal_spans(prose)[0]
        [link] = [link for link in cc.links(quote, source)[0] if link.word.lower() == link_word]
        missed = [w for w in story_words.content_words(claim.effect)
                  if cc._weighs(w) and not cc._meets(cc._root(w), cc._roots(link.effect))]
        assert missed == [word]
        assert cc._covers(claim.cause, link.cause, link.effect, link.sentence)
        assert _problems(prose, quote, source)

    def test_omc_a_cause_taken_from_the_effect_side_is_refused(self):
        """ADR-019's accepted false refusal (owner, 2026-10-17). The source: smoke affects flights at the airport;
        "Hal ini" moved the OMC. The arc's cause, "asap mengganggu operasi modifikasi cuaca", shares only "asap"
        with that cause side; "operasi modifikasi cuaca" is the source's effect. The retry drops the "karena"."""
        [claim] = cc.causal_spans(OMC)
        [link] = cc.links(OMC_Q, OMC_SRC)[0]
        assert cc.overlap(claim.cause, link.cause) == 0.2 and cc.overlap(claim.cause, link.effect) >= 0.6
        assert _problems(OMC, OMC_Q, OMC_SRC)

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
        assert cc.overlap(span.before, window) >= 0.6     # the widened half passed ADR-019's 60% bar
        assert not cc.backs(window, window, span) and _problems(MK, window, window)

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
        assert cc.backs(source, source, span)

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
        """"Hal ini menyebabkan": the cause is the sentence before, the effect the rest of the second."""
        prose = ("Kini OMC yang semula dilakukan dari Palembang dipindah ke Pangkal Pinang karena asap karhutla "
                 "berdampak pada penerbangan di Bandara Sultan Mahmud Badaruddin II.")
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


# ── ADR-019: one link of the quote, by direction (SYS-152 send-back, SYS-181..185) ──────────────────

AVTUR = "Harga tiket pesawat domestik naik tajam karena harga avtur melonjak sepanjang Oktober."


def kept(prose, quote, source=None):
    return _problems(prose, quote, quote if source is None else source) == []


class TestDirection:
    """SYS-152 send-back: the cause half must match the source's cause side, the effect half its effect side."""

    def test_halves_are_named_by_the_direction_of_the_word(self):
        [back] = cc.causal_spans("Harga naik karena pasokan seret.")
        [forward] = cc.causal_spans("Pasokan seret sehingga harga naik.")
        assert (back.cause, back.effect) == ("pasokan seret.", "Harga naik")
        assert (forward.cause, forward.effect) == ("Pasokan seret", "harga naik.")

    def test_a_reversed_claim_is_refused(self):
        assert kept("Harga tiket pesawat domestik naik tajam karena harga avtur melonjak.", AVTUR)
        assert not kept("Harga avtur melonjak karena harga tiket pesawat domestik naik tajam.", AVTUR)

    def test_a_forward_connective_is_checked_with_its_halves_swapped(self):
        assert kept("Harga avtur melonjak sehingga harga tiket pesawat domestik naik tajam.", AVTUR)
        assert not kept("Harga tiket pesawat domestik naik tajam sehingga harga avtur melonjak.", AVTUR)

    def test_mk_reversed_is_refused(self):
        assert not kept("Para pemohon tidak memiliki kedudukan hukum karena permohonan dinyatakan tidak dapat "
                        "diterima.", MK_Q, MK_SRC)


MK_TWO = ("MK tidak dapat mendiskualifikasi Gibran karena hal tersebut bukan ranah MK, tapi lembaga lain. "
          "Permohonan para pemohon dinyatakan tidak dapat diterima karena mereka tidak memiliki kedudukan hukum.")
BERAS = "Harga beras naik karena gagal panen di Jawa, sementara harga cabai turun karena pasokan melimpah."


class TestOneLink:
    """SYS-181 (#381): the two halves come from the two sides of ONE causal word of the quote."""

    def test_mk_from_two_adjacent_sentences_each_with_its_own_reason_is_refused(self):
        assert not kept("MK tidak dapat mendiskualifikasi Gibran karena permohonan para pemohon tidak dapat "
                        "diterima.", MK_TWO)

    def test_two_links_of_one_sentence_are_not_crossed(self):
        assert not kept("Harga beras naik karena pasokan cabai melimpah.", BERAS)

    def test_each_link_still_backs_its_own_claim(self):
        assert kept("Harga beras naik karena gagal panen di Jawa.", BERAS)
        assert kept("Harga cabai turun karena pasokan melimpah.", BERAS)

    def test_an_unrelated_sentence_before_lends_nothing(self):
        source = "Harga avtur melonjak 12 persen. Harga tiket naik karena permintaan libur sekolah tinggi."
        assert not kept("Harga avtur melonjak karena permintaan libur sekolah tinggi.", source)

    def test_hal_ini_menyebabkan_takes_the_sentence_before_as_its_cause(self):
        source = "Asap karhutla menyelimuti Palembang sejak Senin. Hal ini menyebabkan 15 penerbangan dibatalkan."
        assert kept("Sebanyak 15 penerbangan dibatalkan karena asap karhutla menyelimuti Palembang.", source)

    def test_adjacent_causal_words_are_one_link(self):
        source = "Banjir terjadi karena dipicu hujan deras."
        assert {(s.cause, s.effect) for s in cc.links(source, source)[0]} == {("hujan deras.", "Banjir terjadi")}
        assert kept("Banjir terjadi karena hujan deras.", source)

    def test_a_name_may_stand_anywhere_in_the_links_sentence(self):
        """Replay 10-11 (v4): the source names the place after its next causal word; the event words are on the
        effect side."""
        source = ("Hujan deras pada Sabtu siang memicu luapan air sungai hingga menyebabkan tanggul jebol di Koto Tangah "
                  "dan Kuranji.")
        assert kept("Sehari sebelumnya, hujan deras memicu luapan air sungai di Koto Tangah dan Kuranji.", source)

    def test_names_never_carry_the_event_words(self):
        source = "Banjir surut karena pompa di Pluit, Ancol dan Muara Baru bekerja penuh."
        prose = "Kemarin, warga Pluit Ancol Muara Baru tergenang karena pompa bekerja penuh."
        assert cc.overlap("pompa bekerja penuh", "pompa di Pluit, Ancol dan Muara Baru bekerja penuh.") == 1.0
        assert not kept(prose, source)            # 3 of 5 words are names in the sentence; no event word is

    def test_a_negator_or_a_frame_word_is_no_fact(self):
        """"belum", "disebut", "lalu" weigh nothing: the negation is checked on its own (replay 10-08, 10-10)."""
        assert cc.overlap("Perpres Ojol disebut belum terbit", "Perpres Ojol Tak Kunjung Terbit") == 1.0
        assert cc.overlap("lalu memproyeksikan defisit", "memproyeksikan defisit") == 1.0

    def test_a_side_stops_at_another_causal_word(self):
        [first, second] = cc.causal_spans("Hujan deras memicu luapan sungai, sehingga tim SAR mengevakuasi warga.")
        assert first.effect == "luapan sungai" and second.cause == "luapan sungai"
        [first, second] = cc.causal_spans("Hujan deras memicu luapan sungai sehingga tim SAR mengevakuasi warga.")
        assert first.effect == "luapan sungai" and second.cause == "luapan sungai"


TIKET_ARTICLE = ("Harga avtur melonjak sepanjang Oktober. Maskapai mengeluhkan biaya operasional. Harga tiket "
                 "pesawat domestik naik tajam karena harga avtur melonjak.")
TIKET = "Harga tiket pesawat domestik naik tajam karena harga avtur melonjak."


class TestQuoteSpan:
    """SYS-182 (#382): the sentences a quote covers are counted in the SOURCE."""

    def test_an_ellipsis_bridging_three_source_sentences_is_refused(self):
        quote = "Harga avtur melonjak sepanjang Oktober ... naik tajam karena harga avtur melonjak"
        assert cc.quote_in(quote, TIKET_ARTICLE) and cc.quotable(quote)
        [problem] = cc.valid_quotes([(0, quote)], {0: TIKET_ARTICLE})[1]
        assert "lebih dari 2 kalimat" in problem and not kept(TIKET, quote, TIKET_ARTICLE)

    def test_full_stops_dropped_to_hide_sentences_are_counted_in_the_source(self):
        quote = " ".join(s.rstrip(".") for s in cc.sentences(TIKET_ARTICLE))
        assert cc.quotable(quote) and not kept(TIKET, quote, TIKET_ARTICLE)

    def test_the_one_sentence_quoted_is_kept(self):
        assert kept(TIKET, TIKET, TIKET_ARTICLE)

    def test_an_ellipsis_inside_one_sentence_is_allowed(self):
        assert kept("Harga tiket pesawat naik tajam karena harga avtur melonjak.",
                    "Harga tiket pesawat ... naik tajam karena harga avtur melonjak", AVTUR)

    def test_the_causal_word_must_be_inside_the_quote(self):
        """The quote points at its own text: a fragment without the sentence's "karena" backs nothing."""
        good, problems = cc.valid_quotes([(0, "Harga tiket pesawat domestik naik tajam")], {0: AVTUR})
        assert good == [] and "tidak memuat kata sebab-akibat" in problems[0]

    def test_an_ellipsis_cannot_hide_a_negation(self):
        source = "Harga tiket pesawat domestik naik tajam bukan karena harga avtur melonjak."
        assert not kept("Harga tiket pesawat domestik naik tajam karena harga avtur melonjak.",
                        "Harga tiket pesawat domestik naik tajam ... karena harga avtur melonjak", source)

    def test_glued_sentences_are_two(self):
        assert cc.sentences("Ray menyebut putusan sudah bisa ditebak.Dia mengaku kecewa.") == [
            "Ray menyebut putusan sudah bisa ditebak.", "Dia mengaku kecewa."]


class TestFrontedCause:
    """SYS-183 (#383): "Karena X, Y" carries both halves in its own sentence."""

    def test_the_cause_is_the_clause_after_the_word_and_the_effect_the_rest(self):
        [span] = cc.causal_spans("Harga naik. Karena gagal panen, harga beras melonjak di Jawa.")
        assert (span.cause, span.effect) == ("gagal panen", "harga beras melonjak di Jawa.")

    def test_an_invented_effect_after_a_fronted_cause_is_refused(self):
        source = "Hujan deras mengguyur Jakarta sejak pagi karena dipicu siklon tropis di Samudra Hindia."
        assert not kept("Hujan deras mengguyur Jakarta sejak pagi. Karena hujan deras, KRL berhenti beroperasi.",
                        source)

    def test_a_fronted_cause_at_a_fields_start_is_kept_with_its_sentence(self):
        assert kept("Akibat asap karhutla, 15 penerbangan di Palembang terganggu.",
                    "Sebanyak 15 penerbangan di Palembang terganggu akibat asap karhutla.")

    def test_without_a_boundary_the_effect_cannot_be_told_and_is_refused(self):
        source = "Sebanyak 15 penerbangan di Palembang terganggu akibat asap karhutla."
        assert not kept("Akibat asap karhutla 15 penerbangan di Palembang terganggu.", source)

    def test_karena_itu_is_forward_with_the_sentence_before_as_cause(self):
        [span] = cc.causal_spans("Harga avtur melonjak 12 persen. Karena itu, maskapai menaikkan harga tiket.")
        assert span.cause == "Harga avtur melonjak 12 persen." and "maskapai menaikkan" in span.effect

    def test_penyebabnya_takes_the_sentence_before_as_its_effect(self):
        [span] = cc.causal_spans("Harga beras naik. Penyebabnya, gagal panen di Jawa.")
        assert (span.cause, span.effect) == ("gagal panen di Jawa.", "Harga beras naik.")

    def test_penyebab_x_adalah_y_splits_at_the_copula(self):
        [span] = cc.causal_spans("Penyebab banjir adalah hujan deras.")
        assert (span.cause, span.effect) == ("hujan deras.", "banjir")


# Written out, not read from causal_check: a form dropped from its table must fail here (DBT-82).
FORMS = ["karena", "dikarenakan", "lantaran", "sebab", "gara-gara", "akibat", "diakibatkan", "dipicu", "disebabkan",
         "imbas", "penyebabnya", "pemicunya", "sehingga", "akibatnya", "karenanya", "imbasnya", "mengakibatkan",
         "berakibat", "menyebabkan", "memicu", "berimbas", "penyebab", "pemicu",
         # SYS-189 (#390)
         "didorong", "dipengaruhi", "ditopang", "berkat", "seiring", "dilatarbelakangi", "bermula dari",
         "memengaruhi", "mempengaruhi", "menimbulkan", "membuat", "mendorong", "menekan"]


class TestCausalWords:
    """SYS-184 (#384): every causal form needs a quote; the prompt lists the same forms."""

    @pytest.mark.parametrize("word", FORMS)
    def test_every_form_needs_a_quote(self, word):
        assert cc.unbacked_causes([("latar", f"Harga beras naik {word} gagal panen di Jawa.")], [], {}) != []

    @pytest.mark.parametrize("prose", ["Asap karhutla mengakibatkan 15 penerbangan dibatalkan.",
                                       "Penyebabnya, asap karhutla menutup bandara.",
                                       "Sebanyak 15 penerbangan dibatalkan gara-gara asap karhutla.",
                                       "Pembatalan 15 penerbangan berimbas pada jadwal haji."])
    def test_qa_cases(self, prose):
        assert cc.unbacked_causes([("latar", prose)], [], {}) != []

    def test_the_table_is_the_list(self):
        assert sorted(cc.CAUSAL_WORDS) == sorted(FORMS)

    @pytest.mark.parametrize("prose", ["Sebanyak 498 jiwa terdampak banjir.", "Banjir berdampak pada 120 rumah.",
                                       "Sektor pariwisata terimbas pandemi.", "Warga terpicu emosinya."])
    def test_affected_is_no_link(self, prose):
        assert cc.causal_spans(prose) == []

    def test_the_prompt_lists_every_form(self):
        assert [w for w in FORMS if f'"{w}"' not in sa.PROMPT] == []


class TestNegation:
    """SYS-185 (#385): a negation in a half, or before the causal word, must agree with the link."""

    def test_a_negated_effect_is_refused(self):
        assert not kept("Harga tiket pesawat domestik tidak naik karena harga avtur melonjak.", AVTUR)

    def test_a_denied_link_is_refused(self):
        assert not kept("Harga tiket pesawat domestik naik tajam bukan karena harga avtur melonjak.", AVTUR)

    def test_a_negation_the_source_has_must_be_kept(self):
        source = "Harga tiket kereta tidak naik karena subsidi pemerintah ditambah."
        assert not kept("Harga tiket kereta naik karena subsidi pemerintah ditambah.", source)
        assert kept("Harga tiket kereta tidak naik karena subsidi pemerintah ditambah.", source)

    def test_a_modal_between_the_negator_and_its_verb_is_skipped(self):
        assert cc.negation_agrees("MK tidak dapat mendiskualifikasinya", "MK tidak dapat mendiskualifikasi Gibran")
        assert cc.negation_agrees("Perpres Ojol belum terbit", "Perpres Ojol Tak Kunjung Terbit")
        assert cc.negation_agrees("Harga tiket tidak dapat naik", "Harga tiket tidak naik karena subsidi")

    def test_a_denied_link_backs_a_denied_claim(self):
        source = "Harga tiket naik bukan karena harga avtur melonjak, melainkan karena permintaan libur tinggi."
        assert kept("Harga tiket naik bukan karena harga avtur melonjak.", source)


# ── DBT-82 (#386): the rules QA's surviving mutants left unpinned ──────────────────────────────────

def _reason(texts=None, timeline=None, **override):
    try:
        sa.parse(_answer(**override), texts or TEXTS, timeline or TIMELINE, DAY)
    except Rejected as e:
        return e.reason
    return "kept"


class TestDbt82:
    def test_a_causal_judul_is_checked(self):
        assert _reason() == "kept"
        assert _reason(judul="Prabowo rapat karhutla karena asap sampai negara tetangga") == "sebab"

    def test_a_causal_agenda_is_checked(self):
        assert _reason(agenda="Rapat lanjutan dijadwalkan Kamis (15/10) karena asap sampai negara tetangga.") == \
            "sebab"

    def test_a_true_cause_quoted_from_a_chosen_alur_item_is_kept(self):
        item = TIMELINE[1]._replace(opening="Presiden menggelar rapat terbatas karena titik api meluas di Kalimantan.")
        latar = ("Persoalan karhutla sudah di meja Presiden sejak September. Pada 23/9 Seskab melaporkan 209 hektare "
                 "lahan masih terbakar, dan pada 24 September Presiden menggelar rapat terbatas karena titik api "
                 "meluas di Kalimantan.")
        sebab = [{"artikel": N + 1, "kutipan": "Presiden menggelar rapat terbatas karena titik api meluas di "
                                               "Kalimantan."}]
        timeline = [TIMELINE[0], item, TIMELINE[2]]
        assert _reason(timeline=timeline, latar=latar, sebab=sebab) == "kept"
        assert _reason(timeline=timeline, latar=latar, sebab=[]) == "sebab"

    def test_every_word_of_a_half_is_covered(self):
        """ADR-020 (owner, 2026-10-18): no share. One word the source lacks refuses the half; dropping source words
        ("domestik", "tajam") does not."""
        assert kept("Harga tiket pesawat naik karena harga avtur melonjak.", AVTUR)
        assert not kept("Harga tiket pesawat kereta naik karena harga avtur melonjak.", AVTUR)
        assert not kept("Harga tiket pesawat naik karena harga avtur dan minyak melonjak.", AVTUR)

    def test_a_widened_half_never_carries_a_core_clause_the_link_lacks(self):
        """"ditunda" alone is one content word, so the effect is widened by the clause before it; that clause is in
        the source, "ditunda" is not. The core clause must be covered on its own (the MK replay window's shape)."""
        source = "MK menyatakan tidak menemukan bukti ijazah Gibran setara SMA karena dokumen tidak lengkap."
        prose = ("MK menyatakan tidak menemukan bukti ijazah Gibran setara SMA, tetapi ditunda karena dokumen tidak "
                 "lengkap.")
        [claim] = cc.causal_spans(prose)
        assert claim.effect_core == "ditunda" and cc.overlap(claim.effect, source) >= 0.6
        assert not kept(prose, source)

    def test_a_comma_ends_the_core_clause(self):
        """The clause before the comma is another fact, never part of the effect the quote must cover."""
        assert kept("Rupiah melemah tajam dan obligasi negara tertekan, harga tiket pesawat domestik naik tajam "
                    "karena harga avtur melonjak.", AVTUR)


class TestSys188EveryWord:
    """SYS-188 (#389, ADR-020 decision 1): every word of a half is on its side, so a swapped subject is refused."""

    @pytest.mark.parametrize("prose,source", [
        ("Saham BBCA turun karena aksi jual asing.", "Saham BBRI turun karena aksi jual asing."),
        ("Harga cabai naik karena cuaca buruk.", "Harga beras naik karena cuaca buruk."),
        ("Rupiah melemah karena The Fed menaikkan suku bunga.", "Rupiah melemah karena ECB menaikkan suku bunga."),
    ])
    def test_a_swapped_subject_is_refused(self, prose, source):
        assert not kept(prose, source)

    def test_a_noun_meets_its_verb(self):
        """The circumfix: "kenaikan" is "naik", "pelemahan" is "melemah" (`story_words.root`)."""
        assert kept("Harga tiket naik karena rupiah melemah.", "Kenaikan harga tiket dipicu pelemahan rupiah.")

    @pytest.mark.parametrize("word,stem", [("kenaikan", "naik"), ("pelemahan", "lemah"), ("peningkatan", "ingkat"),
                                           ("pertengahan", "tengah"), ("menunda", "unda"), ("pekan", "pekan"),
                                           ("selatan", "selatan")])
    def test_the_root(self, word, stem):
        assert story_words.root(word) == stem

    def test_time_parts_and_quantifiers_weigh_nothing(self):
        source = "Asap karhutla menyelimuti Palembang sejak Senin. Hal ini menyebabkan 15 penerbangan dibatalkan."
        assert kept("Sebanyak 15 penerbangan dibatalkan pada pagi hari karena asap karhutla menyelimuti Palembang.",
                    source)

    def test_a_prose_reference_takes_its_own_previous_sentence(self):
        """DBT-83 (qa18_reference_side_not_widened): "Kondisi tersebut memicu" is caused by the prose's previous
        sentence, which must be the source's."""
        source = "Harga beras naik tajam. Kondisi tersebut memicu inflasi pangan."
        assert kept("Harga beras naik tajam. Kondisi tersebut memicu inflasi pangan.", source)
        assert not kept("Harga cabai naik tajam. Kondisi tersebut memicu inflasi pangan.", source)
        [claim] = cc.causal_spans("Harga beras naik tajam. Kondisi tersebut memicu inflasi pangan.")
        assert claim.cause == "Harga beras naik tajam."


class TestSys181NameRoom:
    """SYS-181 send-back (ADR-020 decision 2): a name may stand elsewhere in the link's sentence, never on the link's
    other side."""

    def test_swapped_places_are_refused(self):
        source = "Banjir di Padang memicu longsor di Solok."
        assert kept("Banjir di Padang memicu longsor di Solok.", source)
        assert not kept("Banjir di Solok memicu longsor di Padang.", source)

    def test_swapped_places_around_a_backward_word_are_refused(self):
        source = "Ribuan warga Bekasi mengungsi karena tanggul di Karawang jebol."
        assert not kept("Warga Karawang mengungsi karena tanggul di Bekasi jebol.", source)

    def test_a_half_of_names_only_gets_no_room(self):
        """A name locates an event; with no event word in the half, the name IS the claim and must be on its side.
        BBCA stands in the sentence, outside both sides of the "karena" link."""
        source = "BBCA menguat sementara IHSG turun karena aksi jual asing."
        assert kept("IHSG turun karena aksi jual asing.", source)
        assert not kept("IHSG turun karena BBCA.", source)


class TestSys181Anaphor:
    """SYS-181 send-back (ADR-020 decision 3): the previous sentence is lent to an anaphor on the side's own subject
    only when that subject names the previous sentence."""

    MK_TWO = ("MK menyatakan tidak berwenang mendiskualifikasi calon. Permohonan pemohon tersebut tidak dapat "
              "diterima karena melewati tenggat.")

    def test_another_subject_with_tersebut_lends_nothing(self):
        assert not kept("MK tidak berwenang mendiskualifikasi calon karena permohonan melewati tenggat.", self.MK_TWO)
        assert kept("Permohonan pemohon tidak dapat diterima karena melewati tenggat.", self.MK_TWO)

    def test_an_anaphor_off_the_subject_lends_nothing(self):
        source = "Banjir merendam 200 rumah di Desa Sukamaju. Longsor di desa tersebut dipicu tanggul jebol."
        assert not kept("Banjir merendam 200 rumah di Desa Sukamaju karena tanggul jebol.", source)

    def test_a_subject_naming_the_previous_sentence_borrows_it(self):
        source = ("Defisit APBN 2026 diproyeksikan melebar ke 2,9 persen PDB. Peningkatan proyeksi defisit tersebut "
                  "disebabkan penerimaan pajak yang lebih rendah.")
        assert kept("Defisit APBN 2026 diproyeksikan melebar karena penerimaan pajak lebih rendah.", source)

    @pytest.mark.parametrize("side,lends", [("Peningkatan proyeksi defisit tersebut", True),
                                            ("Permohonan pemohon tersebut tidak dapat diterima", False),
                                            ("Longsor di desa tersebut", False), ("Hal ini", True)])
    def test_refers_back(self, side, lends):
        assert cc._refers_back(side, "Defisit APBN 2026 diproyeksikan melebar.") is lends


class TestSys183And187Lists:
    """SYS-183 send-back + SYS-187 (#388, ADR-020 decision 7): a fronted cause runs to the last punctuation boundary;
    a prose cause (or effect) after its causal word runs over every comma item."""

    FRONTED = "Karena kenaikan suku bunga, pelemahan rupiah, dan arus modal keluar, IHSG anjlok 3 persen."

    def test_a_fronted_list_is_one_cause(self):
        [link] = cc.causal_spans(self.FRONTED)
        assert link.effect == "IHSG anjlok 3 persen."
        assert link.cause == "kenaikan suku bunga, pelemahan rupiah, dan arus modal keluar"

    def test_one_list_item_is_not_the_cause_of_the_others(self):
        assert kept("IHSG anjlok 3 persen karena kenaikan suku bunga.", self.FRONTED)
        assert not kept("Kenaikan suku bunga memicu pelemahan rupiah dan arus modal keluar.", self.FRONTED)

    def test_a_fronted_cause_never_runs_past_a_conjunction(self):
        [link] = cc.causal_spans("Karena hujan deras, jalan ditutup, sementara warga bertahan di rumah.")
        assert link.cause == "hujan deras" and link.effect == "jalan ditutup"

    DEFISIT = "Defisit melebar karena dinamika ekonomi global."

    @pytest.mark.parametrize("prose", [
        "Defisit melebar karena dinamika ekonomi global, dan perang dagang Amerika Serikat dengan China.",
        "Defisit melebar karena dinamika ekonomi global, perang dagang, serta kenaikan suku bunga The Fed."])
    def test_every_item_of_a_cause_list_is_checked(self, prose):
        assert not kept(prose, self.DEFISIT)

    def test_a_true_list_is_kept(self):
        source = "Defisit melebar karena dinamika ekonomi global, konflik geopolitik, serta fluktuasi harga komoditas."
        assert kept("Defisit melebar karena dinamika ekonomi global, konflik geopolitik, dan fluktuasi harga.", source)

    def test_an_effect_list_after_a_forward_word_is_checked(self):
        source = "Hujan deras memicu banjir di tiga kecamatan."
        assert not kept("Hujan deras memicu banjir di tiga kecamatan, longsor, dan pemadaman listrik.", source)

    def test_the_list_ends_at_a_clause_of_its_own(self):
        [claim] = cc.causal_spans("IHSG turun karena aksi jual asing, sementara rupiah menguat.")
        assert claim.cause == "aksi jual asing"

    def test_a_trailing_attribution_is_no_item(self):
        source = "Realisasi naik 2,7 persen, terutama didorong PIP dan KIP Kuliah semester II 2026."
        assert kept("Realisasi naik 2,7 persen, terutama didorong PIP dan KIP Kuliah semester II 2026, kata Menteri "
                    "Keuangan Suahasil Nazara.", source)

    def test_a_source_side_stops_at_tetapi(self):
        """DBT-83 (qa18_side_runs_past_tetapi): "Ekspor naik, tetapi impor turun karena X" says nothing of exports."""
        assert not kept("Ekspor naik karena harga batu bara melonjak.",
                        "Ekspor naik, tetapi impor turun karena harga batu bara melonjak.")


class TestSys185LexicalNegation:
    """SYS-185 send-back (ADR-020 decision 5): batal/gagal/urung/tanpa negate the next word; a denial before the
    causal word denies the link."""

    @pytest.mark.parametrize("negator", ["batal", "gagal", "urung"])
    def test_a_lexical_negator_must_agree(self, negator):
        source = f"Harga BBM {negator} naik karena subsidi energi ditambah."
        assert not kept("Harga BBM naik karena subsidi energi ditambah.", source)
        assert kept(f"Harga BBM {negator} naik karena subsidi energi ditambah.", source)

    def test_tanpa_negates_its_noun(self):
        source = "Proyek itu berjalan tanpa izin karena pengawasan lemah."
        assert not kept("Proyek itu berjalan dengan izin karena pengawasan lemah.", source)
        assert kept("Proyek itu berjalan tanpa izin karena pengawasan lemah.", source)

    @pytest.mark.parametrize("frame", ["menyatakan tidak benar", "membantah", "menepis anggapan bahwa", "menampik"])
    def test_a_denied_link_backs_only_a_denial(self, frame):
        source = f"Kemenkeu {frame} harga BBM naik karena utang Pertamina membengkak."
        assert not kept("Harga BBM naik karena utang Pertamina membengkak.", source)
        assert kept(f"Kemenkeu {frame} harga BBM naik karena utang Pertamina membengkak.", source)

    def test_a_denial_may_be_written_in_other_words(self):
        """Denial words are checked by the denial rule, never as facts of the half."""
        source = "Kemenkeu membantah harga BBM naik karena utang Pertamina membengkak."
        assert kept("Kemenkeu menepis harga BBM naik karena utang Pertamina membengkak.", source)

    def test_gagal_panen_still_fronts_a_cause(self):
        [span] = cc.causal_spans("Karena gagal panen, harga beras melonjak di Jawa.")
        assert span.cause == "gagal panen"


class TestSys192Hedges:
    """SYS-192 (#393, ADR-020 decision 6): a hedged link backs only a hedged claim; any hedge word will do (owner)."""

    FLAT = "Kebakaran gudang itu dipicu korsleting listrik."

    @pytest.mark.parametrize("source", ["Kebakaran gudang itu diduga dipicu korsleting listrik.",
                                        "Polisi menyelidiki apakah kebakaran gudang itu dipicu korsleting listrik.",
                                        "Kebakaran gudang itu ditengarai dipicu korsleting listrik.",
                                        "Kebakaran gudang itu dipicu kemungkinan korsleting listrik."])
    def test_a_hedged_link_does_not_back_a_flat_claim(self, source):
        assert not kept(self.FLAT, source)

    def test_any_hedge_word_carries_it(self):
        assert kept("Kebakaran gudang itu diduga dipicu korsleting listrik.",
                    "Kebakaran gudang itu kemungkinan dipicu korsleting listrik.")

    def test_a_claim_may_hedge_a_flat_link(self):
        assert kept("Kebakaran gudang itu diduga dipicu korsleting listrik.", self.FLAT)


class TestSys189MarketVerbs:
    """SYS-189 (#390, ADR-020 decision 4): the causal verbs of market copy are causal words with a direction;
    membuat/mendorong/menekan are none after a purpose word (owner, 2026-10-18: "Gate, exempt purpose")."""

    SRC = "Rupiah melemah 0,11 persen ke Rp17.895 per dolar AS pada Senin."

    @pytest.mark.parametrize("prose", ["Rupiah melemah, didorong aksi jual investor asing.",
                                       "Pelemahan rupiah dipengaruhi aksi jual investor asing.",
                                       "Rupiah melemah seiring aksi jual investor asing.",
                                       "Aksi jual investor asing membuat rupiah melemah.",
                                       "Aksi jual investor asing mendorong pelemahan rupiah."])
    def test_an_unquoted_claim_is_refused(self, prose):
        assert cc.unbacked_causes([("latar", prose)], [], {0: self.SRC}) != []

    @pytest.mark.parametrize("word", ["didorong", "dipengaruhi", "ditopang", "berkat", "seiring", "dilatarbelakangi",
                                      "bermula dari"])
    def test_backward_verbs_keep_their_direction(self, word):
        source = f"Harga tiket pesawat naik {word} lonjakan harga avtur."
        assert kept(f"Harga tiket pesawat naik {word} lonjakan harga avtur.", source)
        assert not kept(f"Lonjakan harga avtur terjadi {word} harga tiket pesawat naik.", source)

    @pytest.mark.parametrize("word", ["memengaruhi", "mempengaruhi", "menimbulkan", "membuat", "mendorong", "menekan"])
    def test_forward_verbs_keep_their_direction(self, word):
        source = f"Lonjakan harga avtur {word} harga tiket pesawat naik."
        assert kept(f"Lonjakan harga avtur {word} harga tiket pesawat naik.", source)
        assert not kept(f"Harga tiket pesawat naik {word} lonjakan harga avtur.", source)

    @pytest.mark.parametrize("prose", ["Kedua presiden sepakat memperkuat kerja sama, termasuk mendorong pembentukan EPA.",
                                       "Kebijakan ini untuk mendorong budidaya dalam negeri.",
                                       "Pemerintah berupaya terus mendorong ekspor.",
                                       "BI turun tangan guna menekan volatilitas rupiah."])
    def test_a_purpose_verb_after_a_purpose_word_is_no_link(self, prose):
        """The replays' 5 "mendorong" are all of this shape (arcs-v4/v5/v6, 2026-10-11/12)."""
        assert cc.causal_spans(prose) == []

    def test_only_the_three_verbs_are_exempt(self):
        """"termasuk akibat cuaca buruk" ("including because of") is still a causal claim."""
        [claim] = cc.causal_spans("Harga cabai naik, termasuk akibat cuaca buruk.")
        assert claim.word == "akibat"

    def test_a_purpose_verb_with_a_subject_is_a_link(self):
        [claim] = cc.causal_spans("Banjir di tiga kecamatan Kota Padang membuat 672 orang mengungsi.")
        assert claim.word == "membuat" and claim.effect == "672 orang mengungsi."

    def test_a_two_word_form_is_one_word_whatever_its_spacing(self):
        [claim] = cc.causal_spans("Sengketa itu bermula  dari utang yang tak dibayar.")
        assert cc._kind(claim.word) == cc.BACKWARD and claim.cause.startswith("utang")


class TestMatchCounts:
    """SYS-152 Done-when: how many quotes fail an exact match before normalisation, measured on the live editions."""

    def test_verbatim_normalised_and_absent_are_told_apart(self):
        counts = cc.match_counts([(0, AVTUR), (0, AVTUR.upper()), (0, "Harga tiket ... karena harga avtur"),
                                  (0, "Harga tiket turun."), (5, AVTUR)], {0: AVTUR})
        assert counts == {"verbatim": 2, "normalised": 1, "absent": 2}
