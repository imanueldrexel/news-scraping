"""QA 2026-10-18: QA's own tests for the SYS-152 send-back queue (ADR-019: SYS-152, SYS-181..185, DBT-82), SYS-186
and SYS-174/177/178/179.

Written from the tickets' text, ADR-019 and the dev's "judgement calls to check" (handoff 2026-10-17). None of these
inputs is in tests/unit or in QA's earlier files:
- the measured deviation, "a NAME may stand anywhere in the link's sentence": a swapped place;
- negation beyond the four negators: "batal/gagal/urung naik", a denied frame ("tidak benar", "membantah",
  "menepis anggapan");
- ADR-019 decision 5's anaphor allowance when the second sentence has its own subject (the MK shape again);
- a fronted cause that is a list ("Karena A, B, dan C, Y");
- causal verbs outside the table that the arcs print ("didorong", "dipengaruhi", "seiring", "membuat");
- the live MSCI end point rephrased ("hingga evaluasi indeks pada November 2026", three gap words, "akhir 2027" vs
  "akhir Juni 2027", "per November 2026", "berakhir pada");
- the latar's future-verb cue: verbs outside the list, a cue further than 4 words, a cue after the phrase;
- a whole future month or period in the agenda ("dijadwalkan terbit Desember").
Held-out controls (true claims and the dev's shapes) are kept in each class, so a fix cannot over-correct.

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_18/test_qa_1018.py -q -p no:cacheprovider

A failing test here is a finding, recorded in .10x/reviews/2026-10-18-qa-report.md and ticketed (each class
docstring names its ticket).
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


# ── SYS-181 send-back: a half matched outside its side ─────────────────────────────────────────────

class TestSys181NameRoom:
    """SYS-181 (sent back). The measured deviation lets a half's names stand anywhere in the link's sentence. A place
    swapped between the two halves then passes: the source says the flood was in Padang, the claim says Solok."""

    SRC = "Banjir di Padang memicu longsor di Solok."

    def test_the_true_claim_is_kept(self):
        assert kept("Banjir di Padang memicu longsor di Solok.", self.SRC)

    def test_swapped_places_are_refused(self):
        assert not kept("Banjir di Solok memicu longsor di Padang.", self.SRC)

    def test_swapped_places_backward_word_are_refused(self):
        src = "Ribuan warga Bekasi mengungsi karena tanggul di Karawang jebol."
        assert kept("Warga Bekasi mengungsi karena tanggul di Karawang jebol.", src)
        assert not kept("Warga Karawang mengungsi karena tanggul di Bekasi jebol.", src)


class TestSys181AnaphorWithOwnSubject:
    """SYS-181 (sent back). ADR-019 decision 5: "two unrelated sentences can no longer lend each other halves". But a
    source side with its own subject (>= 2 content words) still takes the previous sentence whenever it holds
    "tersebut", and the claim's half may then be matched wholly on that previous sentence. 11.5% of causal sentences
    in the last 30 days' articles (17,337) have that shape. The MK case, in two sentences."""

    MK = ("MK menyatakan tidak berwenang mendiskualifikasi calon. Permohonan pemohon tersebut tidak dapat diterima "
          "karena melewati tenggat.")

    def test_the_mk_shape_across_an_anaphor_is_refused(self):
        assert not kept("MK tidak berwenang mendiskualifikasi calon karena permohonan melewati tenggat.", self.MK)

    def test_the_link_the_second_sentence_states_is_kept(self):
        assert kept("Permohonan pemohon tidak dapat diterima karena melewati tenggat.", self.MK)

    def test_another_subject_with_tersebut_lends_nothing(self):
        src = "Banjir merendam 200 rumah di Desa Sukamaju. Longsor di desa tersebut dipicu tanggul jebol."
        assert not kept("Banjir merendam 200 rumah di Desa Sukamaju karena tanggul jebol.", src)

    def test_a_true_back_reference_is_still_kept(self):
        """ADR-018's allowance: the anaphor names the previous sentence's own subject."""
        src = ("Defisit APBN 2026 diproyeksikan melebar ke 2,9 persen PDB. Peningkatan proyeksi defisit tersebut "
               "disebabkan penerimaan pajak yang lebih rendah.")
        assert kept("Defisit APBN 2026 diproyeksikan melebar karena penerimaan pajak lebih rendah.", src)


class TestSubjectSwap:
    """New ticket (P1). A half needs 60% of its content words on its side, so a 3-word half may swap the one word
    that says WHAT: the subject. An arc that joins two related articles (BBCA and BBRI, BBM and listrik) prints the
    cause of one under the subject of the other; the names guard passes, since each name is stated somewhere."""

    @pytest.mark.parametrize("prose,src", [
        ("Saham BBCA turun karena aksi jual asing.", "Saham BBRI turun karena aksi jual asing."),
        ("Harga BBM naik karena subsidi energi dipangkas.", "Harga listrik naik karena subsidi energi dipangkas."),
        ("Rupiah melemah karena The Fed menaikkan suku bunga.", "Rupiah melemah karena ECB menaikkan suku bunga."),
        ("Harga cabai naik karena cuaca buruk.", "Harga beras naik karena cuaca buruk."),
        ("Ekspor nikel anjlok karena permintaan China melemah.", "Ekspor batu bara anjlok karena permintaan China melemah."),
    ])
    def test_a_swapped_subject_is_refused(self, prose, src):
        assert not kept(prose, src)

    def test_a_prose_reference_keeps_its_own_previous_sentence(self):
        """"Kondisi tersebut memicu" takes the prose's previous sentence as the cause; it must be the source's."""
        assert not kept("Harga cabai naik tajam. Kondisi tersebut memicu inflasi pangan.",
                        "Harga beras naik tajam. Kondisi tersebut memicu inflasi pangan.")

    def test_a_paraphrase_with_the_same_subject_stays_kept(self):
        assert kept("Harga tiket pesawat naik tajam karena harga avtur melonjak.",
                    "Harga tiket pesawat domestik naik tajam karena harga avtur melonjak sepanjang Oktober.")


class TestHedgeDropped:
    """New ticket (P2). A source that suspects or asks ("diduga dipicu", "apakah ... dipicu", "kemungkinan karena")
    backs a claim that states the link as fact. 4.6% of causal sentences in the last 30 days hold such a hedge."""

    @pytest.mark.parametrize("src", [
        "Kebakaran gudang itu diduga dipicu korsleting listrik.",
        "Polisi masih menyelidiki apakah kebakaran gudang itu dipicu korsleting listrik.",
        "Kebakaran gudang itu kemungkinan dipicu korsleting listrik.",
    ])
    def test_a_hedged_link_does_not_back_a_flat_claim(self, src):
        assert not kept("Kebakaran gudang itu dipicu korsleting listrik.", src)

    def test_the_hedge_kept_in_the_claim_is_backed(self):
        src = "Kebakaran gudang itu diduga dipicu korsleting listrik."
        assert kept("Kebakaran gudang itu diduga dipicu korsleting listrik.", src)


# ── SYS-185 send-back: negation beyond tidak/tak/bukan/belum ───────────────────────────────────────

class TestSys185LexicalAndFrameNegation:
    """SYS-185 (sent back): "a negated cause or effect is backed by the quote that states the opposite". The four
    negators are checked; the same opposite in other words is not. Corpus, last 30 days: 1.6% of causal sentences
    hold batal/gagal/urung/tanpa, 0.3% a denial frame ("Fahmy secara tegas menepis anggapan bahwa hal itu murni imbas
    dari moratorium")."""

    @pytest.mark.parametrize("src,prose", [
        ("Harga BBM batal naik karena subsidi energi ditambah.", "Harga BBM naik karena subsidi energi ditambah."),
        ("Ekspor nikel gagal melonjak karena harga global anjlok.", "Ekspor nikel melonjak karena harga global anjlok."),
        ("Perkelahian antarwarga urung terjadi karena polisi segera datang.",
         "Perkelahian antarwarga terjadi karena polisi segera datang."),
    ])
    def test_a_lexical_negator_dropped_from_the_effect_is_refused(self, src, prose):
        assert not kept(prose, src)

    @pytest.mark.parametrize("src", [
        "Kemenkeu menyatakan tidak benar harga BBM naik karena utang Pertamina membengkak.",
        "Kemenkeu membantah harga BBM naik karena utang Pertamina membengkak.",
        "Kemenkeu menepis anggapan bahwa harga BBM naik karena utang Pertamina membengkak.",
    ])
    def test_a_denied_link_is_refused(self, src):
        assert not kept("Harga BBM naik karena utang Pertamina membengkak.", src)

    def test_the_four_negators_still_work(self):
        src = "Harga BBM tidak naik karena subsidi energi ditambah."
        assert not kept("Harga BBM naik karena subsidi energi ditambah.", src)
        assert kept("Harga BBM tidak naik karena subsidi energi ditambah.", src)

    def test_bukan_hanya_karena_keeps_the_named_cause(self):
        """"not only because A, but also B": A is still a stated cause."""
        src = "Rupiah melemah bukan hanya karena data inflasi AS, tetapi juga karena arus keluar modal."
        assert kept("Rupiah melemah karena data inflasi AS.", src)


# ── SYS-183 send-back: a fronted cause that is a list ──────────────────────────────────────────────

class TestSys183FrontedList:
    """SYS-183 (sent back). `_fronted` ends the cause at the first comma after 2 content words, so in a source
    "Karena A, B, dan C, Y" the rest of the list becomes the effect: A is read as causing B and C."""

    SRC = "Karena kenaikan suku bunga, pelemahan rupiah, dan arus modal keluar, IHSG anjlok 3 persen."

    def test_the_main_clause_effect_is_kept(self):
        assert kept("IHSG anjlok 3 persen karena kenaikan suku bunga.", self.SRC)

    def test_one_list_item_is_not_the_cause_of_the_others(self):
        assert not kept("Kenaikan suku bunga memicu pelemahan rupiah dan arus modal keluar.", self.SRC)

    def test_the_dev_fronted_shape_still_works(self):
        src = "Karena hujan deras sejak pagi, jalan tol Jagorawi ditutup."
        assert kept("Jalan tol Jagorawi ditutup karena hujan deras.", src)
        assert not kept("Hujan deras turun karena jalan tol Jagorawi ditutup.", src)


# ── held-out checks that pass (SYS-182, SYS-183, SYS-184) ──────────────────────────────────────────

class TestHeldOutPasses:
    """QA's held-out inputs on the parts that hold. Expected: all pass."""

    def test_sys182_quote_dropping_two_full_stops_spans_three_source_sentences(self):
        src = "Harga avtur melonjak. Maskapai mengeluh. Akibatnya, harga tiket pesawat domestik naik tajam."
        quote = "Harga avtur melonjak maskapai mengeluh akibatnya harga tiket pesawat domestik naik tajam"
        assert cc.links(quote, src)[1] == "long"

    def test_sys182_ellipsis_cannot_hide_a_bukan(self):
        src = "Harga tiket naik bukan karena harga avtur melonjak."
        assert not kept("Harga tiket naik karena harga avtur melonjak.", "Harga tiket naik ... karena harga avtur melonjak.",
                        src)

    @pytest.mark.parametrize("word", ["dikarenakan", "gara-gara", "diakibatkan", "lantaran"])
    def test_sys184_backward_synonyms_keep_direction(self, word):
        src = f"Harga tiket pesawat naik {word} harga avtur melonjak."
        assert kept(f"Harga tiket pesawat naik {word} harga avtur melonjak.", src)
        assert not kept(f"Harga avtur melonjak {word} harga tiket pesawat naik.", src)

    @pytest.mark.parametrize("word", ["mengakibatkan", "berimbas pada", "memicu"])
    def test_sys184_forward_synonyms_keep_direction(self, word):
        src = f"Lonjakan harga avtur {word} kenaikan harga tiket pesawat."
        assert kept(f"Lonjakan harga avtur {word} kenaikan harga tiket pesawat.", src)
        assert not kept(f"Kenaikan harga tiket pesawat {word} lonjakan harga avtur.", src)

    def test_sys183_akibat_fronted_reversed_refused(self):
        src = "Akibat banjir setinggi satu meter, jalan provinsi di Padang ditutup."
        assert kept("Jalan provinsi di Padang ditutup akibat banjir setinggi satu meter.", src)
        assert not kept("Banjir setinggi satu meter terjadi akibat jalan provinsi di Padang ditutup.", src)


# ── new: causal verbs outside the table ───────────────────────────────────────────────────────────

class TestCausalVerbsOutsideTheTable:
    """New ticket (P1). The arcs print causal claims with verbs `_KINDS` does not hold, and those need no quote at
    all. arcs-v5 (Versi B) prints "Analis menyebut pelemahan dipengaruhi pernyataan pejabat The Fed", "Realisasi
    naik 2,7%, terutama didorong PIP dan KIP Kuliah", "Rupiah sempat menguat seiring penurunan ekspektasi kenaikan
    suku bunga Fed". An invented one is printed the same way."""

    SRC = "Rupiah melemah 0,11 persen ke Rp17.895 per dolar AS pada Senin."

    @pytest.mark.parametrize("prose", [
        "Rupiah melemah, didorong aksi jual investor asing.",
        "Pelemahan rupiah dipengaruhi aksi jual investor asing.",
        "Rupiah melemah seiring aksi jual investor asing.",
        "Aksi jual investor asing membuat rupiah melemah.",
        "Aksi jual investor asing mendorong pelemahan rupiah.",
    ])
    def test_an_unquoted_causal_claim_is_refused(self, prose):
        assert cc.unbacked_causes([("latar", prose)], [], {0: self.SRC}) != []


# ── SYS-186 send-back: the live MSCI end point, rephrased ──────────────────────────────────────────

MSCI = ("Jelang Review MSCI November 2026, Pembekuan Saham Indonesia Diprediksi Hingga 2027\nKebijakan pembekuan saham "
        "Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. Freeze MSCI berpotensi "
        "berlanjut hingga semester II-2027. MSCI menyatakan kebijakan pembekuan berlanjut hingga akhir Juni 2027.")


class TestSys186Rephrased:
    """SYS-186 (sent back). The live false fact is refused only as written. The same false end, in the words the
    model uses elsewhere, is printed."""

    @pytest.mark.parametrize("prose", [
        "Pembekuan berlanjut hingga evaluasi indeks pada November 2026.",     # "pada" blocks the gap
        "Pembekuan berlanjut hingga review indeks MSCI November 2026.",       # three gap words
        "Pembekuan berlanjut hingga review MSCI pada November 2026.",
    ])
    def test_the_msci_end_point_rephrased_is_refused(self, prose):
        assert sc.unbacked_end_times(prose, MSCI) != []

    def test_a_part_of_the_year_is_not_backed_by_the_same_part_of_a_month(self):
        """"akhir 2027" is December 2027; the source's "akhir Juni 2027" is June."""
        assert sc.unbacked_end_times("Pembekuan berlanjut hingga akhir 2027.", MSCI) != []

    def test_per_as_a_start_does_not_back_an_end(self):
        """"berlaku per November 2026" is "from November 2026" (24 corpus sentences, last 30 days)."""
        assert sc.unbacked_end_times("Pembekuan berlanjut hingga November 2026.",
                                     "Pembekuan berlaku per November 2026.") != []

    @pytest.mark.parametrize("prose", ["Pembekuan berlanjut hingga akhir Juni 2027.", "Pembekuan berlanjut hingga 2027.",
                                       "Pembekuan berlanjut hingga semester II 2027."])
    def test_the_stated_ends_stay_kept(self, prose):
        assert sc.unbacked_end_times(prose, MSCI) == []

    def test_a_period_to_date_per_stays_an_end(self):
        assert sc.unbacked_end_times("Defisit APBN hingga 30 September 2026 mencapai Rp319 triliun.",
                                     "Defisit APBN per 30 September 2026 mencapai Rp319 triliun.") == []


class TestEndPointWithoutHingga:
    """New ticket (P2). An end point written without "hingga/sampai" is read by nothing: "berakhir pada review
    November 2026" prints the MSCI false fact; prose "s.d." is an end only on the source side."""

    @pytest.mark.parametrize("prose", ["Pembekuan berakhir pada review November 2026.",
                                       "Pembekuan berlaku s.d. November 2026.",
                                       "Pembekuan baru dicabut pada November 2026."])
    def test_an_end_point_the_source_does_not_state_is_refused(self, prose):
        assert sc.unbacked_end_times(prose, MSCI) != []


class TestEndPointSubject:
    """New ticket (P3). The dev's residual: the time must match, the subject need not. Every arc's sources state
    period-to-date figures ("Defisit APBN hingga September 2026"), and a less precise prose end is backed by a more
    precise one, so any "hingga 2026" about anything is backed."""

    def test_an_end_stated_for_another_subject_does_not_back(self):
        src = ("Defisit APBN hingga September 2026 mencapai Rp319 triliun. Pembekuan saham berlanjut setelah "
               "evaluasi November 2026.")
        assert sc.unbacked_end_times("Pembekuan saham berlanjut hingga 2026.", src) != []


class TestBehavioursOnlyQaGuards:
    """Expected: all pass on HEAD. Each is a behaviour a QA mutant broke with tests/unit still green (DBT ticket):
    the suites do not hold these lines."""

    def test_a_source_side_stops_at_tetapi(self):
        """qa18_side_runs_past_tetapi."""
        assert not kept("Ekspor naik karena harga batu bara melonjak.",
                        "Ekspor naik, tetapi impor turun karena harga batu bara melonjak.")

    def test_semester_is_not_kuartal(self):
        """qa18_semester_is_kuartal."""
        assert sc.unbacked_end_times("Pembekuan berlanjut hingga kuartal II 2027.",
                                     "Freeze berlanjut hingga semester II-2027.") != []

    def test_a_month_end_of_another_year_does_not_back(self):
        """qa18_month_year_ignored."""
        assert sc.unbacked_end_times("Pembekuan berlanjut hingga Juni 2026.",
                                     "Pembekuan berlanjut hingga akhir Juni 2027.") != []


# ── SYS-177 send-back: the latar's future-verb cue ─────────────────────────────────────────────────

KAMIS_LINE = "Rapat lanjutan dijadwalkan Kamis (15/10)."
NONE = "Rapat lanjutan belum dijadwalkan."
LATAR = FRAME + "Pada 23/9 Seskab melaporkan 209 hektare lahan masih terbakar."
D26 = date(2026, 10, 26)
PAST = NONE + " Asap meluas sejak Kamis (22/10)."


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
    data[field] = LATAR + " " + value if field == "latar" else value
    return _answer(**data)


class TestSys177LatarCue:
    """SYS-177 (sent back). On 26/10 a source states the past day 22/10, inside "akhir Oktober". A latar schedule is
    caught only with akan/bakal/dijadwalkan/ditargetkan/direncanakan/rencananya/menyusul in the 4 words before it.
    Other future verbs, a longer verb phrase, and a fronted time print the invented schedule."""

    @pytest.mark.parametrize("latar", [
        "Pemerintah berencana menerbitkan aturan barunya akhir Oktober.",
        "Aturan barunya diperkirakan terbit akhir Oktober.",
        "Aturan barunya diproyeksikan terbit akhir Oktober.",
        "Aturan barunya diharapkan terbit akhir Oktober.",
        "Aturan barunya segera terbit akhir Oktober.",
        "Aturan barunya mulai berlaku akhir Oktober.",
    ])
    def test_another_future_verb_makes_it_a_schedule(self, latar):
        assert _outcome(_field("latar", latar), _texts(PAST), D26) == "date"

    def test_a_cue_further_than_four_words_still_counts(self):
        latar = "Pemerintah akan menerbitkan peraturan baru soal karhutla akhir Oktober."
        assert _outcome(_field("latar", latar), _texts(PAST), D26) == "date"

    @pytest.mark.parametrize("latar", ["Menurut Menteri, akhir Oktober aturan barunya akan terbit.",
                                       "Aturan barunya akhir Oktober akan terbit."])
    def test_a_cue_after_a_fronted_time_counts(self, latar):
        assert _outcome(_field("latar", latar), _texts(PAST), D26) == "date"

    def test_the_replay_past_narration_stays_backed(self):
        """QA 10-16 late: the 6 replay running spans are past narration; one has 'akan' after, about something else."""
        early = [TIMELINE[0], TIMELINE[1]._replace(day=date(2026, 10, 2))]
        latar = ("Persoalan karhutla sudah di meja Presiden sejak September. Sebelumnya, pada awal Oktober, Presiden "
                 "menggelar rapat terbatas soal karhutla yang akan memanggil para ahli.")
        answer = _answer(latar=latar, agenda="")
        assert sa.parse(answer, _texts(), early, date(2026, 10, 8))


# ── held-out checks that pass (SYS-174, SYS-178, SYS-179) ──────────────────────────────────────────

class TestSchedulesHeldOut:
    """QA's held-out inputs on the schedule tickets that hold. Expected: all pass."""

    @pytest.mark.parametrize("day,phrase", [(date(2026, 12, 31), "akhir tahun ini"), (date(2026, 10, 31), "pekan ini"),
                                            (date(2026, 10, 31), "akhir Oktober")])
    def test_sys174_a_span_ending_today_is_no_backing_for_an_agenda(self, day, phrase):
        assert _outcome(_field("agenda", f"Aturan karhutla dijadwalkan terbit {phrase}."), _texts(), day) == "date"

    @pytest.mark.parametrize("value", ["Aturan karhutla rampung akhir tahun nanti.", "Aturan karhutla rampung akhir minggu.",
                                       "Aturan karhutla rampung pada akhir tahun.", "Aturan karhutla rampung jelang akhir tahun."])
    def test_sys178_bare_forms_in_other_words(self, value):
        assert _outcome(_field("agenda", value)) == "date"

    def test_sys178_a_past_weekend_does_not_back_a_future_one(self):
        assert _outcome(_field("agenda", "Aturan karhutla akan rampung akhir pekan."),
                        _texts("Aturan itu dibahas akhir pekan lalu.")) == "date"

    @pytest.mark.parametrize("prose,stated", [("akhir tahun depan", "tahun depan"), ("awal tahun mendatang", "tahun mendatang"),
                                              ("akhir minggu depan", "minggu depan"), ("akhir bulan depan", "awal bulan depan")])
    def test_sys179_a_narrower_part_is_not_backed(self, prose, stated):
        assert _outcome(_field("agenda", f"Aturan karhutla akan rampung {prose}."),
                        _texts(f"Aturan akan rampung {stated}.")) == "date"


# ── new: a whole future month or period in the agenda ──────────────────────────────────────────────

class TestFutureMonthOrPeriod:
    """New ticket (P2). A month PART is judged ("akhir Desember" refused), the whole month is not: "dijadwalkan
    terbit Desember" is printed with nothing stating it. So are "November 2026", "semester II 2026", "kuartal IV
    2026", "akhir 2026" and "penghujung tahun ini", wherever the year is stated as part of any date (every source
    writes "(12/10/2026)"). The arcs write this shape: "ditargetkan berlaku semester II 2027", "akan diluncurkan pada
    2027", "ditargetkan rampung akhir November 2026" (v5/v6)."""

    @pytest.mark.parametrize("phrase", ["Desember", "pada Desember", "bulan Desember", "November 2026", "November mendatang",
                                        "semester II 2026", "kuartal IV 2026", "akhir 2026", "akhir tahun 2026",
                                        "penghujung tahun ini"])
    @pytest.mark.parametrize("field", ["agenda", "hari_ini"])
    def test_an_invented_future_month_or_period_is_refused(self, field, phrase):
        value = f"Aturan karhutla dijadwalkan terbit {phrase}."
        if field == "hari_ini":
            value = "Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara. " + value
        assert _outcome(_field(field, value)) == "date"

    def test_the_part_is_judged_already(self):
        assert _outcome(_field("agenda", "Aturan karhutla dijadwalkan terbit akhir Desember.")) == "date"

    def test_a_stated_month_backs_it(self):
        assert _outcome(_field("agenda", "Aturan karhutla dijadwalkan terbit Desember."),
                        _texts("Aturan karhutla dijadwalkan terbit Desember.")) == "kept"
