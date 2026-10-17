"""QA 2026-10-17: QA's own tests for SYS-152 (#342, ADR-018) and DBT-81 (#380).

Written from the ticket text, ADR-018 and QA's design note on #342 ("the effect clause and the cause clause both
match the same source sentence, each on its own side of the connective"). None of these inputs is in the dev's
tests/unit/test_causal_check.py:
- the six Done-when items again, on new sentences (paraphrase, "Akibatnya,", attribution, tidak_terkait, sehingga);
- direction: a reversed cause and effect, and a forward connective whose halves are swapped wrongly;
- the MK shape in other forms: two adjacent sentences that each hold their own reason, two links in one sentence,
  an "..." bridge across the article, a multi-sentence quote with its full stops dropped;
- a sentence that opens on its causal word with a noun-phrase cause ("Karena X, Y", "Akibat X, Y");
- causal words outside the regex (mengakibatkan, dikarenakan, penyebabnya, ...);
- a negated effect;
- DBT-81: _tracked on a path with spaces.

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_17/test_qa_sys152.py -q -p no:cacheprovider

A failing test here is a finding, recorded in .10x/reviews/2026-10-17-qa-report.md and ticketed (class docstrings
name the ticket).
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import newscrawler.core.story_arc as sa  # noqa: E402
from newscrawler.core import causal_check as cc  # noqa: E402
from newscrawler.core.llm_json import Rejected  # noqa: E402
from tests.unit.test_story_arc import DAY, TEXTS, TIMELINE, _answer  # noqa: E402


def _problems(prose, quotes, source):
    return cc.unbacked_causes([("latar", prose)], [(0, q) for q in quotes], {0: source})


def kept(prose, quote, source):
    return _problems(prose, [quote], source) == []


AVTUR = "Harga tiket pesawat domestik naik tajam karena harga avtur melonjak sepanjang Oktober."


class TestDoneWhenHeldOut:
    """The ticket's Done-when items on QA's own sentences. Expected: all pass (they are the dev's claims)."""

    def test_true_cause_quoted_verbatim_is_kept(self):
        assert kept("Harga tiket pesawat domestik naik tajam karena harga avtur melonjak.", AVTUR, AVTUR)

    def test_paraphrased_quote_is_refused(self):
        para = "Tiket pesawat lokal makin mahal akibat avtur yang naik sepanjang Oktober."
        assert not cc.quote_in(para, AVTUR)
        assert not kept("Tiket pesawat makin mahal akibat avtur naik.", para, AVTUR)

    def test_akibatnya_opening_with_true_quote_kept_and_invented_refused(self):
        src = "Harga avtur melonjak 12 persen pekan ini. Akibatnya, maskapai menaikkan harga tiket pesawat domestik."
        good = "Harga avtur melonjak 12 persen. Akibatnya, maskapai menaikkan harga tiket pesawat domestik."
        bad = "Harga avtur melonjak 12 persen. Akibatnya, pemerintah menunda keberangkatan jemaah haji."
        assert kept(good, src, src)
        assert not kept(bad, src, src)

    def test_attributed_invented_cause_is_refused(self):
        src = "Harga tiket pesawat domestik naik tajam pekan ini. Kemenhub menyebut permintaan libur sekolah tinggi."
        prose = "Menurut Kemenhub, harga tiket pesawat domestik naik tajam karena permintaan libur sekolah tinggi."
        assert not kept(prose, src, src)          # the quote holds no causal word, and no sentence joins them

    def test_quote_from_tidak_terkait_article_is_refused_end_to_end(self):
        texts = [*TEXTS[:2], TEXTS[2] + " " + AVTUR]
        prose = "Harga tiket pesawat domestik naik tajam karena harga avtur melonjak."
        with pytest.raises(Rejected) as e:
            sa.parse(_answer(hari_ini=_answer_hari_ini(prose), sebab=[{"artikel": 2, "kutipan": AVTUR}]),
                     texts, TIMELINE, DAY, lenient=True)
        assert e.value.reason == "sebab"

    def test_correct_forward_connective_is_kept(self):
        """"Y sehingga X" restates "X karena Y" with the halves swapped: same link, same direction."""
        assert kept("Harga avtur melonjak sehingga harga tiket pesawat domestik naik tajam.", AVTUR, AVTUR)


def _answer_hari_ini(prose):
    return "Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara, Senin (12/10). " + prose


class TestDirection:
    """SYS-152 sent back (Done-when "sehingga is checked with the halves swapped"): the gate never checks which
    half is the cause. ADR-018 step 4 swaps halves for forward
    connectives (so direction is meant to matter) and QA's design note on #342 asks for each clause on its own
    side of the connective; causal_check's docstring says "the direction ... does not matter here"."""

    def test_reversed_cause_and_effect_is_refused(self):
        prose = "Harga avtur melonjak karena harga tiket pesawat domestik naik tajam."
        assert not kept(prose, AVTUR, AVTUR)

    def test_forward_connective_pointing_the_wrong_way_is_refused(self):
        prose = "Harga tiket pesawat domestik naik tajam sehingga harga avtur melonjak."
        assert not kept(prose, AVTUR, AVTUR)

    def test_mk_reversed_is_refused(self):
        src = "Permohonan para pemohon dinyatakan tidak dapat diterima karena mereka tidak memiliki kedudukan hukum."
        prose = "Para pemohon tidak memiliki kedudukan hukum karena permohonan dinyatakan tidak dapat diterima."
        assert not kept(prose, src, src)


MK_TWO = ("MK tidak dapat mendiskualifikasi Gibran karena hal tersebut bukan ranah MK, tapi lembaga lain. "
          "Permohonan para pemohon dinyatakan tidak dapat diterima karena mereka tidak memiliki kedudukan hukum.")
MK_PROSE = "MK tidak dapat mendiskualifikasi Gibran karena permohonan para pemohon tidak dapat diterima."


class TestHalvesFromDifferentLinks:
    """SYS-181: both halves are measured against the whole quote, so a quote holding two causal links lets the
    prose join the effect of one to the cause of the other -- the MK failure itself, when the two reasons sit
    in adjacent sentences (the two-sentence allowance) or in one sentence."""

    def test_mk_with_both_reasons_in_two_adjacent_sentences_is_refused(self):
        assert cc.quote_in(MK_TWO, MK_TWO) and cc.quotable(MK_TWO)
        assert not kept(MK_PROSE, MK_TWO, MK_TWO)

    def test_two_links_in_one_sentence_crossed_is_refused(self):
        src = "Harga beras naik karena gagal panen di Jawa, sementara harga cabai turun karena pasokan melimpah."
        assert not kept("Harga beras naik karena pasokan cabai melimpah.", src, src)

    def test_hal_ini_menyebabkan_still_kept(self):
        """The allowance's purpose must survive the fix: the cause is the previous sentence."""
        src = "Asap karhutla menyelimuti Palembang sejak Senin. Hal ini menyebabkan 15 penerbangan dibatalkan."
        assert kept("Sebanyak 15 penerbangan dibatalkan karena asap karhutla menyelimuti Palembang.", src, src)


MK_ARTICLE = ("MK menyatakan tidak dapat mendiskualifikasi Gibran. Menurut hakim, hal itu bukan ranah MK tapi "
              "lembaga lain. Sidang dihadiri puluhan pengunjung dan berlangsung tertib sejak pagi. Kuasa hukum "
              "pemohon menyatakan kecewa atas putusan itu. Permohonan para pemohon dinyatakan tidak dapat diterima "
              "karena mereka tidak memiliki kedudukan hukum.")


class TestQuoteSpan:
    """SYS-182: the one-sentence / two-adjacent-sentences rule is counted on the quote as the model wrote it, not
    on the source text it covers. "..." bridges any distance and dropped full stops hide sentences, so one
    "quote" can glue the first and the fifth sentence of an article around a dangling causal word."""

    def test_ellipsis_bridge_across_the_article_is_refused(self):
        quote = "MK menyatakan tidak dapat mendiskualifikasi Gibran ... permohonan para pemohon dinyatakan tidak " \
                "dapat diterima karena"
        assert cc.quote_in(quote, MK_ARTICLE)
        assert not kept(MK_PROSE, quote, MK_ARTICLE)

    def test_full_stops_dropped_to_hide_sentences_is_refused(self):
        sents = cc.sentences(MK_ARTICLE)
        quote = " ".join(s.rstrip(".") for s in sents)      # all 5 source sentences, full stops dropped
        assert cc.quote_in(quote, MK_ARTICLE) and cc.quotable(quote)
        assert not kept(MK_PROSE, quote, MK_ARTICLE)

    def test_ellipsis_inside_one_sentence_still_allowed(self):
        quote = "Harga tiket pesawat ... naik tajam karena harga avtur melonjak"
        assert kept("Harga tiket pesawat naik tajam karena harga avtur melonjak.", quote, AVTUR)


class TestSentenceInitialCause:
    """SYS-183: "Karena X, Y" / "Akibat X, Y" -- the cause opens the sentence and the effect follows the comma.
    causal_spans takes the PREVIOUS sentence as the other half and the cause clause "X" as the after half, so the
    effect Y is never checked (a false accept), and at the start of a field it is refused (a false refusal)."""

    def test_invented_effect_after_a_fronted_cause_is_refused(self):
        src = "Hujan deras mengguyur Jakarta sejak pagi karena dipicu siklon tropis di Samudra Hindia."
        prose = "Hujan deras mengguyur Jakarta sejak pagi. Karena hujan deras, KRL berhenti beroperasi."
        assert not kept(prose, src, src)

    def test_fronted_akibat_with_its_true_sentence_is_kept_at_field_start(self):
        src = "Sebanyak 15 penerbangan di Palembang terganggu akibat asap karhutla."
        assert kept("Akibat asap karhutla, 15 penerbangan di Palembang terganggu.", src, src)

    def test_fronted_cause_effect_half_is_the_clause_after_the_comma(self):
        [span] = cc.causal_spans("Harga naik. Karena gagal panen, harga beras melonjak di Jawa.")
        assert "harga beras melonjak" in (span.before + " " + span.after)


class TestCausalWordForms:
    """SYS-184: CAUSAL matches whole words only, so affixed forms of its own roots and common synonyms carry a
    causal claim past the gate with no `sebab` entry at all. ADR-018 asks for equivalence classes."""

    @pytest.mark.parametrize("prose", [
        "Asap karhutla mengakibatkan 15 penerbangan dibatalkan.",
        "Sebanyak 15 penerbangan dibatalkan diakibatkan asap karhutla.",
        "Sebanyak 15 penerbangan dibatalkan dikarenakan asap karhutla.",
        "Penyebabnya, asap karhutla menutup bandara.",
        "Asap karhutla menjadi pemicu pembatalan 15 penerbangan.",
        "Sebanyak 15 penerbangan dibatalkan gara-gara asap karhutla.",
        "Pembatalan 15 penerbangan berimbas pada jadwal haji.",
    ], ids=["mengakibatkan", "diakibatkan", "dikarenakan", "penyebabnya", "pemicu", "gara-gara", "berimbas"])
    def test_an_affixed_or_synonym_causal_word_needs_a_quote(self, prose):
        assert _problems(prose, [], "") != []


class TestNegation:
    """SYS-185: "tidak"/"bukan" are stop words, so a quote backs a sentence that says the opposite."""

    def test_negated_effect_is_refused(self):
        assert not kept("Harga tiket pesawat domestik tidak naik karena harga avtur melonjak.", AVTUR, AVTUR)

    def test_negated_cause_is_refused(self):
        assert not kept("Harga tiket pesawat domestik naik tajam bukan karena harga avtur melonjak.", AVTUR, AVTUR)


class TestDbt81:
    def test_tracked_keeps_spaced_path(self):
        from tests.unit import test_repo_hygiene as h
        paths = h._tracked("*.md")
        assert os.path.join(ROOT, "reports/In prompt causal claim checking.md") in paths
        assert all(os.path.exists(p) for p in paths)


def _outcome(prose, sebab, extra):
    texts = [TEXTS[0] + " " + extra, *TEXTS[1:]]
    try:
        sa.parse(_answer(hari_ini=_answer_hari_ini(prose), sebab=sebab), texts, TIMELINE, DAY, lenient=True)
    except Rejected as e:
        return e.reason
    return "kept"


class TestServedPath:
    """The findings above reach the printed arc: story_arc.parse (the lenient retry, the last gate) keeps them."""

    @pytest.mark.parametrize("prose,quote,source,ticket", [
        ("Harga avtur melonjak karena harga tiket pesawat domestik naik tajam.", AVTUR, AVTUR, "SYS-152"),
        (MK_PROSE, MK_TWO, MK_TWO, "SYS-181"),
        (MK_PROSE, "MK menyatakan tidak dapat mendiskualifikasi Gibran ... permohonan para pemohon dinyatakan "
                   "tidak dapat diterima karena", MK_ARTICLE, "SYS-182"),
        ("Hujan deras mengguyur Jakarta sejak pagi. Karena hujan deras, KRL berhenti beroperasi.",
         "Hujan deras mengguyur Jakarta sejak pagi karena dipicu siklon tropis di Samudra Hindia.",
         "Hujan deras mengguyur Jakarta sejak pagi karena dipicu siklon tropis di Samudra Hindia.", "SYS-183"),
        ("Asap karhutla mengakibatkan 15 penerbangan dibatalkan.", None, "", "SYS-184"),
        ("Harga tiket pesawat domestik tidak naik karena harga avtur melonjak.", AVTUR, AVTUR, "SYS-185"),
    ], ids=["reversed", "mk-two-sentences", "ellipsis-bridge", "fronted-cause", "mengakibatkan", "negated"])
    def test_refused_as_sebab(self, prose, quote, source, ticket):
        sebab = [] if quote is None else [{"artikel": 0, "kutipan": quote}]
        assert _outcome(prose, sebab, source) == "sebab", ticket
