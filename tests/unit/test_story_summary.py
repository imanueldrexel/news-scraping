"""SYS-82 (#239): the structured per-story summary and its guards; SYS-80 (#236): an
article the model marks `tidak_terkait` leaves the headline, the links and the
portal count.

The guards are the point: the copy rules (word limits, numbers copied from the
articles) hold only because `parse` refuses an answer that breaks them.
"""
import json
from datetime import date
from unittest.mock import MagicMock

import pytest

import newscrawler.core.newsletter_generator as ng
import newscrawler.core.story_summary as ss
from newscrawler.core.summarizer import QuotaExhausted
from tests.unit.newsletter_fakes import FakeNewsroom, shown_articles, story_answer

# The shown articles' guard texts (story_summary.guard_text: headline and opening, no outlet name).
SOURCES = ["Harga Emas Antam Stagnan pada Minggu (4/10/2026), Rp 2.574.000 per Gram\n"
           "Harga buyback tetap Rp 2.380.000 per gram, selisih Rp 194.000. Kenaikan 0,46% pekan lalu.",
           "Laporan 4 Oktober 2026 soal emas Antam\nRealisasi 13.300.000 ton."]
SOURCE = "\n\n".join(SOURCES)


def _answer(**override):
    data = {"judul": "Harga emas Antam bertahan di Rp2.574.000 per gram",
            "inti": "Harga emas batangan Antam tidak berubah pada Minggu (4/10) di Rp2.574.000 per gram.",
            "poin": ["Harga buyback juga tetap di Rp2.380.000 per gram, selisih Rp194.000 dari harga jual."],
            "mengapa_penting": "", "sekilas": "Emas Antam stagnan di Rp2.574.000 per gram.",
            "terkait": [0], "tidak_terkait": [1]}
    data.update(override)
    return json.dumps(data)


def _reason(answer, n=2, source=SOURCES):
    with pytest.raises(ss.Rejected) as e:
        ss.parse(answer, n, source)
    return e.value.reason


class TestParse:
    def test_a_valid_answer(self):
        story = ss.parse(_answer(), 2, SOURCES)
        assert story.judul == "Harga emas Antam bertahan di Rp2.574.000 per gram"
        assert (story.terkait, story.tidak_terkait, len(story.poin)) == ([0], [1], 1)

    @pytest.mark.parametrize("wrap", ["Tentu! {} Semoga membantu.", "```json\n{}\n```"])
    def test_the_usual_wrappers(self, wrap):
        assert ss.parse(wrap.format(_answer()), 2, SOURCES).terkait == [0]

    def test_optional_fields_may_be_left_out_or_null(self):
        data = json.loads(_answer())
        del data["poin"], data["tidak_terkait"]
        data["mengapa_penting"] = None
        data["terkait"] = [0, 1]
        story = ss.parse(json.dumps(data), 2, SOURCES)
        assert (story.poin, story.mengapa_penting, story.tidak_terkait) == ([], "", [])

    @pytest.mark.parametrize("answer", [
        "", None, "tidak bisa", "[1, 2]", '{"judul": "x"',
        _answer(judul=""), _answer(inti=3), _answer(poin="satu kalimat"), _answer(poin=[1]),
        _answer(terkait=[]), _answer(terkait=[0, 2], tidak_terkait=[1]),          # an index that does not exist
        _answer(terkait=[], tidak_terkait=[0, 1]),             # DBT-56: every article unrelated -- no story to tell
        _answer(terkait=[0, 0], tidak_terkait=[1]),                                # an index twice
        _answer(terkait=[0, 1], tidak_terkait=[1]),                                # in both lists
        _answer(terkait=[0], tidak_terkait=[]),                                    # one article in neither
        _answer(terkait=[True], tidak_terkait=[1]),                                # a bool is not an index
        _answer(terkait=["0"], tidak_terkait=[1]),
    ])
    def test_a_malformed_answer_is_a_json_refusal(self, answer):
        assert _reason(answer) == "json"

    def test_the_judul_is_asked_for_10_words_and_refused_above_12(self):
        """CTO/owner decision 2026-10-05: ask 10, accept 12."""
        assert f"judul: maks {ss.JUDUL_ASKED} kata" in ss.PROMPT and ss.JUDUL_ASKED == 10
        assert ss.parse(_answer(judul=" ".join(["kata"] * 12)), 2, SOURCES).judul.count("kata") == 12
        assert _reason(_answer(judul=" ".join(["kata"] * 13))) == "length"

    @pytest.mark.parametrize("field,limit", [("judul", 12), ("inti", 25), ("mengapa_penting", 20), ("sekilas", 15)])
    def test_each_field_over_its_word_limit(self, field, limit):
        at_limit = " ".join(["kata"] * limit)
        assert getattr(ss.parse(_answer(**{field: at_limit}), 2, SOURCES), field) == at_limit
        assert _reason(_answer(**{field: at_limit + " lagi"})) == "length"

    def test_a_point_over_its_word_limit(self):
        assert _reason(_answer(poin=[" ".join(["kata"] * 21)])) == "length"

    def test_more_than_two_points(self):
        assert _reason(_answer(poin=["satu.", "dua.", "tiga."])) == "length"

    def test_every_broken_limit_is_named_at_once(self):
        with pytest.raises(ss.Rejected) as e:
            ss.parse(_answer(judul=" ".join(["kata"] * 13), poin=["a.", " ".join(["b"] * 21)]), 2, SOURCES)
        assert "judul 13 kata, maks 12" in e.value.detail and "poin ke-2 21 kata, maks 20" in e.value.detail
        assert 'persingkat: "b b b' in e.value.detail             # the retry sees what to shorten

    def test_on_the_retry_a_long_point_is_dropped_whole_never_cut(self):
        long = " ".join(["kata"] * 23)
        story = ss.parse(_answer(poin=[long, "Poin pendek."]), 2, SOURCES, drop_long_poin=True)
        assert (story.poin, story.dropped_poin) == (["Poin pendek."], 1)
        story = ss.parse(_answer(poin=["satu.", "dua.", "tiga."]), 2, SOURCES, drop_long_poin=True)
        assert (story.poin, story.dropped_poin) == (["satu.", "dua."], 1)

    def test_on_the_retry_every_other_field_still_must_fit(self):
        with pytest.raises(ss.Rejected):
            ss.parse(_answer(judul=" ".join(["kata"] * 13)), 2, SOURCES, drop_long_poin=True)
        assert ss.parse(_answer(), 2, SOURCES).dropped_poin == 0

    def test_a_number_not_in_the_articles(self):
        assert _reason(_answer(inti="Harga emas naik ke Rp2.600.000 per gram.")) == "number"

    @pytest.mark.parametrize("field", ["judul", "poin", "mengapa_penting", "sekilas"])
    def test_every_field_is_checked_for_numbers(self, field):
        value = ["Laba naik 99 persen."] if field == "poin" else "Laba naik 99 persen."
        assert _reason(_answer(**{field: value})) == "number"

    def test_separators_do_not_matter_but_a_rewritten_number_does(self):
        assert ss.unsupported_number("Rp2.574.000 dan 0,46%", SOURCE) is None
        assert ss.unsupported_number("13,3 juta ton", SOURCE) == "13,3"     # the prompt says: copy verbatim

    def test_a_short_date_passes_when_the_articles_name_that_date(self):
        assert ss.unsupported_number("Minggu (4/10)", SOURCE) is None             # 4/10/2026 and "4 Oktober"
        assert ss.unsupported_number("Minggu (4/10)", "Laporan 4 Okt 2026") is None
        assert ss.unsupported_number("Jumat (2/10)", SOURCE) == "2/10"
        assert ss.unsupported_number("skor 3/13", "skor 3/13 di babak kedua") is None   # copied as it stands
        assert ss.unsupported_number("Rabu (5/13)", "5 Desember") == "5/13"            # no month 13

    def test_words(self):
        assert ss.words("  satu  dua\ntiga ") == 3


class TestNumbersByValue:
    """SYS-87 (#247): separators may differ, the decimal position may not."""

    @pytest.mark.parametrize("summary,articles", [
        ("anggaran Rp1,5 triliun", "anggaran Rp15 triliun"),        # a tenfold error
        ("naik 25 persen", "naik 2,5 persen"),
        ("Rp1,5 triliun", "Rp1.500 triliun"),                       # Indonesian prose: 1.500 is fifteen hundred
        ("harga 13,3 juta", "harga 133 juta"),
    ])
    def test_a_shifted_decimal_is_another_number(self, summary, articles):
        assert ss.unsupported_number(summary, articles) is not None

    @pytest.mark.parametrize("summary,articles", [
        ("Rp2.574.000", "Rp 2.574.000"), ("Rp2.574.000", "2,574,000"), ("2,574,000", "Rp2.574.000"),
        ("naik 1,5 persen", "naik 1.5 persen"), ("Rp1,20 triliun", "Rp1,2 triliun"), ("0,46%", "0,46 persen"),
        ("1,500 ton", "1500 ton"), ("Rp1.234.567,89", "1,234,567.89"), ("pukul 05.55", "pukul 05.55 WIB"),
    ])
    def test_the_same_value_in_another_notation_passes(self, summary, articles):
        assert ss.unsupported_number(summary, articles) is None

    def test_values(self):
        assert ss.values("2.574.000") == {"2574000"} and ss.values("1,5") == {"1,5"}
        assert ss.values("1.500") == {"1500"} and ss.values("1,500") == {"1500", "1,5"}
        assert ss.values("007") == {"7"} and ss.values("0,125") == {"0,125"}

    def test_the_outlet_name_is_not_article_text(self):
        """Liputan6's 6 is not a number its article states."""
        article = {"source": "LIPUTAN6", "headline": "Banjir rendam rumah warga", "l1_text": "Banjir merendam rumah."}
        assert "Liputan6" in ss.article_text(article)                    # the model reads the outlet ...
        assert "Liputan6" not in ss.guard_text(article)                  # ... the guard does not count it
        answer = _answer(judul="Banjir rendam 6 rumah", inti="Banjir merendam rumah.", poin=[],
                         sekilas="Banjir rendam rumah.", terkait=[0], tidak_terkait=[])
        with pytest.raises(ss.Rejected) as e:
            ss.parse(answer, 1, [ss.guard_text(article)])
        assert e.value.reason == "number" and '"6"' in e.value.detail


class TestOnlyTheRelatedArticlesAreTheSource:
    """SYS-80 (#236): a summary is written from its `terkait` articles only."""

    def test_a_number_only_an_unrelated_article_states_is_refused(self):
        # 13.300.000 is only in article [1], which the answer marks tidak_terkait
        assert _reason(_answer(inti="Realisasi emas Antam 13.300.000 ton.")) == "number"
        data = json.loads(_answer(inti="Realisasi emas Antam 13.300.000 ton."))
        data.update(terkait=[0, 1], tidak_terkait=[])
        assert ss.parse(json.dumps(data), 2, SOURCES).inti.startswith("Realisasi")

    # 2026-10-04, read from the DB (posted_at 20261004): Investor.id's Haji Isam piece and Warta Ekonomi's
    # "10 Saham" list, which names neither Haji Isam nor PACK.
    HAJI_ISAM = ["Haji Isam Punya Gerbong Saham di Bursa, Siapa Lokomotifnya?\nPengusaha Andi Syamsuddin Arsyad "
                 "alias Haji Isam punya gerbong saham di Bursa Efek Indonesia (BEI) dengan kinerja beragam sepanjang "
                 "tahun berjalan atau year to date (YTD). Harga saham PACK naik 133,88% YTD ke Rp 428.",
                 "10 Saham Paling Babak Belur Sepekan, FORU Paling Parah\nSejumlah saham di Bursa Efek Indonesia (BEI) "
                 "mengalami koreksi tajam. Saham FORU anjlok 54,72%, dari Rp360 menjadi Rp163."]
    MIXED = json.dumps({"judul": "Saham Haji Isam beragam, PACK naik 133,88% YTD",
                        "inti": "Saham terafiliasi Haji Isam berkinerja beragam, PACK naik paling mencolok 133,88% YTD.",
                        "poin": ["Saham FORU anjlok 54,72% sepekan, dari Rp360 menjadi Rp163 per saham."],
                        "mengapa_penting": "", "sekilas": "Saham Haji Isam beragam, PACK naik 133,88%.",
                        "terkait": [0, 1], "tidak_terkait": []})

    def test_an_article_that_does_not_name_the_subject_is_refused(self):
        with pytest.raises(ss.Rejected) as e:
            ss.parse(self.MIXED, 2, self.HAJI_ISAM)
        assert e.value.reason == "subject"
        assert "artikel [1] tidak menyebut haji, isam, pack, ytd" in e.value.detail
        assert "artikel [0]" not in e.value.detail and "tidak_terkait" in e.value.detail

    def test_the_repaired_answer_passes(self):
        """The retry's answer: the list moved to tidak_terkait, its FORU fact gone."""
        data = json.loads(self.MIXED)
        data.update(poin=[], terkait=[0], tidak_terkait=[1])
        assert ss.parse(json.dumps(data), 2, self.HAJI_ISAM).terkait == [0]

    def test_moving_the_article_without_dropping_its_fact_is_a_number_refusal(self):
        data = json.loads(self.MIXED)
        data.update(terkait=[0], tidak_terkait=[1])
        assert _reason(json.dumps(data), source=self.HAJI_ISAM) == "number"

    def test_a_number_and_a_subject_problem_are_named_together(self):
        data = json.loads(self.MIXED)
        data["inti"] += " Nilainya Rp999."
        with pytest.raises(ss.Rejected) as e:
            ss.parse(json.dumps(data), 2, self.HAJI_ISAM)
        assert e.value.reason == "number" and "artikel [1] tidak menyebut" in e.value.detail

    def test_articles_naming_the_subject_in_other_words_pass(self):
        """Any one anchor is enough, in any case, inside a hyphenated word too."""
        texts = ["BI tahan BI-Rate di 4,75 persen", "Bank Indonesia menahan suku bunga acuan (BI-Rate)"]
        answer = json.dumps({"judul": "Bank Indonesia tahan BI-Rate 4,75 persen",
                             "inti": "Bank Indonesia menahan BI-Rate di 4,75 persen.", "sekilas": "BI tahan bunga.",
                             "terkait": [0, 1]})
        assert ss.parse(answer, 2, texts).terkait == [0, 1]

    def test_a_summary_without_a_name_is_not_held_to_one(self):
        texts = ["harga emas naik tipis", "emas naik pagi ini"]
        answer = json.dumps({"judul": "Harga emas naik tipis", "inti": "Harga emas naik tipis pagi ini.",
                             "sekilas": "Emas naik.", "terkait": [0, 1]})
        assert ss.off_subject("Harga emas naik tipis. Harga emas naik tipis pagi ini.", dict(enumerate(texts))) == \
            ([], [])
        assert ss.parse(answer, 2, texts).terkait == [0, 1]

    def test_one_text_per_shown_article(self):
        with pytest.raises(ValueError):
            ss.parse(_answer(), 2, SOURCES[:1])


class TestPromptAndArticles:
    def _arts(self):
        return [{"source": s, "headline": f"judul {s}", "l1_text": "x" * 1000, "link": f"http://x/{i}"}
                for i, s in enumerate(["DETIK", "KONTAN", "KONTAN", "TVONENEWS", "BISNIS", "KOMPAS", "CNBC", "TEMPO"])]

    def test_one_article_per_outlet_first_by_authority(self):
        picked = ss.pick_articles(self._arts())
        assert [a["source"] for a in picked] == ["BISNIS", "KONTAN", "CNBC", "KOMPAS", "TEMPO", "DETIK"]

    def test_a_second_article_of_an_outlet_fills_a_slot_only_after_every_outlet(self):
        arts = [a for a in self._arts() if a["source"] in ("KONTAN", "DETIK")]
        assert [a["source"] for a in ss.pick_articles(arts)] == ["KONTAN", "DETIK", "KONTAN"]

    def test_the_prompt_numbers_the_articles_and_cuts_their_text(self):
        shown = ss.pick_articles(self._arts())
        prompt = ss.build_prompt(shown)
        assert prompt.count("\n[") >= len(shown) and "[0] Bisnis.com — judul BISNIS" in prompt
        assert "x" * ss.ARTICLE_CHARS in prompt and "x" * (ss.ARTICLE_CHARS + 1) not in prompt
        assert "Di bawah ada 6 artikel" in prompt
        assert [i for i, _, _ in shown_articles(prompt)] == list(range(6))

    def test_the_guard_corpus_is_the_articles_not_the_prompt(self):
        """The prompt's own example and limits ('maks 10 kata', Rp2.574.000) must not count as input."""
        corpus = ss.source_text(ss.pick_articles(self._arts()))
        assert "2.574.000" not in corpus and "maks" not in corpus and "[0]" not in corpus


class _Script:
    name = "s"

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def summarize(self, prompt):
        self.prompts.append(prompt)
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


ARTS = [{"source": "KONTAN", "headline": "Harga Emas Antam Stagnan Rp 2.574.000", "l1_text": "isi", "link": "http://k"},
        {"source": "DETIK", "headline": "Harga Emas Antam Stagnan", "l1_text": "isi", "link": "http://d"}]
GOOD = json.dumps({"judul": "Harga emas Antam stagnan", "inti": "Emas Antam stagnan di Rp2.574.000.", "poin": [],
                   "mengapa_penting": "", "sekilas": "Emas Antam stagnan.", "terkait": [0, 1], "tidak_terkait": []})


class TestSummarizeStory:
    def test_accepted_on_the_first_try(self):
        rejections = []
        assert ss.summarize_story(_Script(GOOD), ARTS, rejections).judul == "Harga emas Antam stagnan"
        assert rejections == []

    def test_a_refusal_is_retried_once_with_its_reason(self):
        s, rejections = _Script("bukan json", GOOD), []
        assert ss.summarize_story(s, ARTS, rejections) is not None
        assert rejections == ["json"]
        assert s.prompts[1].startswith(s.prompts[0])
        assert "Jawaban sebelumnya ditolak: jawaban bukan JSON" in s.prompts[1]

    def test_two_refusals_are_none_with_both_reasons(self):
        bad_number = GOOD.replace("Rp2.574.000", "Rp9.999.999")
        rejections = []
        assert ss.summarize_story(_Script("x", bad_number), ARTS, rejections) is None
        assert rejections == ["json", "number"]

    def test_a_quota_on_the_retry_keeps_the_first_refusal_counted(self):
        rejections = []
        with pytest.raises(QuotaExhausted):
            ss.summarize_story(_Script("x", QuotaExhausted("429")), ARTS, rejections)
        assert rejections == ["json"]


# ── SYS-80: the generator draws the headline, links and portal count from `terkait` ──

def _a(i, source, headline, cluster=0, topic="markets"):
    return {"sitemap_id": i, "headline": headline, "source": source, "category": "news", "link": f"http://x/{i}",
            "posted_at": 20261004, "topic": topic, "l1_text": f"isi {i}", "_cluster": cluster}


HAJI_ISAM = [_a(1, "INVESTORID", "Haji Isam Punya Gerbong Saham di Bursa, Siapa Lokomotifnya?"),
             _a(2, "CNBC", "Perusahaan Mau IPO Makin Sepi di Pasar Modal RI, Ini Penyebabnya"),
             _a(3, "WARTAEKONOMI", "10 Saham Paling Babak Belur Sepekan, FORU Paling Parah"),
             _a(4, "KUMPARAN", "Minat IPO Turun Sepanjang 2026")]


def _generate(monkeypatch, tmp_path, summarizer, arts):
    ds = MagicMock()
    gen = ng.NewsletterGenerator(ds, summarizer=summarizer, embed_documents=lambda t: [[0.0]] * len(t))
    monkeypatch.setattr(ng, "NEWSLETTER_MIN_CLUSTER_SIZE", 2)
    monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path))
    monkeypatch.setattr(gen, "_cluster", lambda vectors: [int(v[0]) for v in vectors])
    monkeypatch.setattr(gen, "_merge_across_sections", lambda entries, vectors: entries)
    monkeypatch.setattr(gen, "_encode", lambda texts: [[a["_cluster"]] for a in arts])
    ds.get_articles_for_date.return_value = arts
    path = gen.generate(date(2026, 10, 4))
    return path, open(path, encoding="utf-8").read()


def _only_ipo(prompt):
    """The model's verdict on the Haji Isam cluster: the IPO slowdown is the event;
    the Haji Isam piece and the '10 Saham' list are about something else."""
    arts = shown_articles(prompt)
    unrelated = [i for i, _, headline in arts if "Haji Isam" in headline or "10 Saham" in headline]
    return story_answer(prompt, judul="Minat IPO di bursa turun", inti="Perusahaan yang IPO makin sepi.",
                        sekilas="Minat IPO turun.", terkait=[i for i, _, _ in arts if i not in unrelated],
                        tidak_terkait=unrelated)


class TestTerkaitDecidesTheStory:
    def test_an_unrelated_article_leaves_the_headline_links_and_portal_count(self, monkeypatch, tmp_path):
        s = FakeNewsroom(story=[_only_ipo])
        path, text = _generate(monkeypatch, tmp_path, s, HAJI_ISAM)
        assert "### Minat IPO di bursa turun" in text
        assert "Haji Isam" not in text and "10 Saham" not in text
        assert "http://x/1)" not in text and "http://x/3)" not in text
        assert "**Diberitakan 2 portal:** CNBC Indonesia · kumparan" in text
        assert "Investor.id" not in text and "Warta Ekonomi" not in text

    def test_the_edition_links_its_title_to_a_related_article(self, monkeypatch, tmp_path):
        path, _ = _generate(monkeypatch, tmp_path, FakeNewsroom(story=[_only_ipo]), HAJI_ISAM)
        edition = open(path.edition, encoding="utf-8").read()
        assert "### [Minat IPO di bursa turun](http://x/2)" in edition
        assert "**Diberitakan 2 portal** · [Baca di CNBC Indonesia →](http://x/2)" in edition

    def test_an_article_the_model_did_not_see_still_counts_as_a_portal(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ss, "MAX_ARTICLES", 2)          # KUMPARAN (authority 0.5) is not shown
        seen = lambda p: story_answer(p, judul="Minat IPO turun", inti="Perusahaan yang IPO makin sepi.",
                                      sekilas="Minat IPO turun.")
        _, text = _generate(monkeypatch, tmp_path, FakeNewsroom(story=[seen]), HAJI_ISAM)
        assert "Diberitakan 4 portal" in text
        assert "http://x/4" not in text                      # never a link: no one checked it

    def test_the_2026_10_04_mix_is_refused_and_repaired(self, monkeypatch, tmp_path):
        """The model marks the "10 Saham" list terkait under a Haji Isam judul (the v5 replay's answer):
        refused as off-subject, and the retry's answer -- the list moved out -- is what the reader gets."""
        texts = TestOnlyTheRelatedArticlesAreTheSource.HAJI_ISAM
        arts = [dict(_a(1, "INVESTORID", texts[0].split("\n")[0]), l1_text=texts[0].split("\n")[1]),
                dict(_a(3, "WARTAEKONOMI", texts[1].split("\n")[0]), l1_text=texts[1].split("\n")[1])]
        mixed = json.loads(TestOnlyTheRelatedArticlesAreTheSource.MIXED)

        def answer(prompt, repaired):
            order = {headline[:8]: i for i, _, headline in shown_articles(prompt)}
            haji, saham = order["Haji Isa"], order["10 Saham"]
            data = dict(mixed, terkait=[haji, saham], tidak_terkait=[])
            if repaired:
                data.update(poin=[], terkait=[haji], tidak_terkait=[saham])
            return json.dumps(data)
        s = FakeNewsroom(story=[lambda p: answer(p, False), lambda p: answer(p, True)])
        _, text = _generate(monkeypatch, tmp_path, s, arts)
        assert "tidak menyebut haji, isam, pack, ytd" in s.prompts["story"][1]
        assert "### Saham Haji Isam beragam" in text
        assert "FORU" not in text and "10 Saham" not in text and "http://x/3)" not in text
        assert "**Diberitakan 1 portal:** Investor.id" in text

    def test_a_fallback_story_keeps_its_cluster_as_clustered(self, monkeypatch, tmp_path):
        _, text = _generate(monkeypatch, tmp_path, FakeNewsroom(story=["x", "x"]), HAJI_ISAM)
        assert "### Haji Isam Punya Gerbong Saham" in text and "Diberitakan 4 portal" in text
