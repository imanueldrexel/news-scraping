"""SYS-83 (#240): the 5-minute edition -- one editor call picks 6-8 top stories
under the owner's quotas and writes the 60-second block; anything the rules
refuse is asked again once, then a deterministic portal-count pick takes over;
duplicates collapse; the word budget trims Sekilas only; the full digest is
unchanged and the edition is a second file."""
import json
import os
from datetime import date
from unittest.mock import MagicMock

import pytest

import newscrawler.core.newsletter_edition as ne
import newscrawler.core.newsletter_generator as ng
from newscrawler.core.story_summary import StorySummary
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError
from tests.unit.newsletter_fakes import FakeNewsroom

D = date(2026, 10, 4)


def _cluster(name, portals, summarized=True):
    story = StorySummary(f"Judul {name}", f"Inti {name} senilai Rp2.574.000.", [f"Poin {name}."], "",
                         f"Sekilas {name}.", [0], []) if summarized else None
    return {"story": story, "sources": [f"S{k}" for k in range(portals)], "headline": f"Portal {name}",
            "links": [{"source": "KONTAN", "link": f"http://x/{name}", "headline": name}],
            "source_text": f"{name} Rp 2.574.000 pada 2026", "articles": []}


def _sections(spec):
    """spec: [(topic, [(name, portals), ...]), ...] in SECTION_ORDER."""
    return [{"topic": topic, "clusters": [_cluster(n, p) if not isinstance(p, tuple) else _cluster(n, *p)
                                          for n, p in clusters]}
            for topic, clusters in spec]


# ids: m1=1 m2=2 m3=3 | p1=4 p2=5 | c1=6 | g1=7 g2=8 | l1=9 l2=10 | i1=11   (m4 is a 4th: no candidate)
DAY = [("markets", [("m1", 11), ("m2", 6), ("m3", 4), ("m4", 9)]),
       ("macro_policy", [("p1", 8), ("p2", 3)]),
       ("corporate", [("c1", 5)]),
       ("politics_government", [("g1", 7), ("g2", 2)]),
       ("law_crime", [("l1", 4), ("l2", 3)]),
       ("international", [("i1", 2)])]


@pytest.fixture
def cands():
    return ne.candidates(_sections(DAY))


def _editor(utama=(1, 4, 7, 2, 9, 6), sixty=None, duplikat=()):
    # (no digits in the default sentences: the number guard would rightly refuse an id written into one)
    sixty = sixty if sixty is not None else [{"id": i, "kalimat": "Kalimat tentang berita ini."} for i in utama[:3]]
    return json.dumps({"duplikat": [list(g) for g in duplikat], "utama": list(utama), "ringkas_60_detik": sixty})


class TestCandidates:
    def test_at_most_three_per_section_numbered_in_order(self, cands):
        assert [(c.id, c.cluster["headline"]) for c in cands][:4] == \
            [(1, "Portal m1"), (2, "Portal m2"), (3, "Portal m3"), (4, "Portal p1")]
        assert len(cands) == 11 and "Portal m4" not in [c.cluster["headline"] for c in cands]

    def test_the_prompt_lists_summarized_candidates_with_section_portals_and_inti(self, cands):
        cands[0].cluster["story"] = None
        prompt = ne.build_prompt(cands, D)
        assert "10 kandidat berita Minggu, 4 Oktober 2026" in prompt
        assert "4 | Kebijakan & Makroekonomi | 8 | Judul p1 | Inti p1 senilai Rp2.574.000." in prompt
        assert "| Judul m1 |" not in prompt


class TestParseEditor:
    def test_a_valid_answer(self, cands):
        choice = ne.parse_editor(_editor(), cands)
        assert choice.utama == [1, 4, 7, 2, 9, 6]
        assert [i for i, _ in choice.sixty] == [1, 4, 7]

    @pytest.mark.parametrize("answer,reason", [
        ("bukan json", "json"),
        (_editor(utama=(1, 4, 7, 2, 9, 99)), "json"),                       # an id that is not a candidate
        (_editor(utama=(1, 4, 7, 2, 9)), "rules"),                          # 5 top stories
        (_editor(utama=(1, 2, 4, 5, 6, 7, 9, 10, 8)), "rules"),             # 9 top stories
        (_editor(utama=(1, 2, 3, 4, 7, 9)), "rules"),                       # 3 from Pasar
        (_editor(utama=(1, 2, 4, 5, 6, 7)), "rules"),                       # 1 non-finance, 2 were available
        (_editor(utama=(1, 4, 7, 2, 9, 6), duplikat=[(1, 2)]), "rules"),    # one event twice
        (_editor(utama=(1, 4, 7, 2, 9, 9)), "rules"),                       # an id twice
        (_editor(sixty=[{"id": 1, "kalimat": "a."}, {"id": 4, "kalimat": "b."}]), "rules"),       # 2 sentences
        (_editor(sixty=[{"id": i, "kalimat": "a."} for i in (1, 4, 7, 2, 9, 6)]), "rules"),       # 6 sentences
        (_editor(sixty=[{"id": 1, "kalimat": "a."}, {"id": 1, "kalimat": "b."}, {"id": 4, "kalimat": "c."}]),
         "rules"),                                                           # two about one story
        (_editor(sixty=[{"id": 1, "kalimat": "a."}, {"id": 4, "kalimat": "b."}, {"id": 3, "kalimat": "c."}]),
         "rules"),                                                           # about a non-top story
        (_editor(sixty=[{"id": 1, "kalimat": " ".join(["kata"] * 19)}, {"id": 4, "kalimat": "b."},
                        {"id": 7, "kalimat": "c."}]), "length"),
        (_editor(sixty=[{"id": 1, "kalimat": "Laba Rp9.999."}, {"id": 4, "kalimat": "b."},
                        {"id": 7, "kalimat": "c."}]), "number"),
        (_editor(sixty=[{"id": 1}, {"id": 4, "kalimat": "b."}, {"id": 7, "kalimat": "c."}]), "json"),
    ])
    def test_each_rule(self, cands, answer, reason):
        with pytest.raises(ne.Rejected) as e:
            ne.parse_editor(answer, cands)
        assert e.value.reason == reason

    def test_a_number_from_that_storys_articles_passes(self, cands):
        sixty = [{"id": 1, "kalimat": "Emas Rp2.574.000 pada 2026."}, {"id": 4, "kalimat": "b."},
                 {"id": 7, "kalimat": "c."}]
        assert ne.parse_editor(_editor(sixty=sixty), cands).sixty[0][1] == "Emas Rp2.574.000 pada 2026."

    def test_overlapping_duplicate_groups_are_one_event(self, cands):
        choice = ne.parse_editor(_editor(duplikat=[(3, 5), (5, 8)]), cands)
        assert choice.groups == [{3, 5, 8}]

    def test_a_small_day_needs_fewer_top_stories(self):
        cands = ne.candidates(_sections([("markets", [("m1", 5), ("m2", 4)]), ("law_crime", [("l1", 3), ("l2", 3)])]))
        choice = ne.parse_editor(_editor(utama=(1, 3, 2, 4)), cands)          # capacity is 4: 2 per section
        assert choice.utama == [1, 3, 2, 4]

    def test_no_non_finance_quota_when_none_reached_three_portals(self):
        cands = ne.candidates(_sections([("markets", [("m1", 9), ("m2", 8)]), ("macro_policy", [("p1", 7), ("p2", 6)]),
                                         ("corporate", [("c1", 5), ("c2", 4)]), ("law_crime", [("l1", 2)])]))
        assert ne.parse_editor(_editor(utama=(1, 2, 3, 4, 5, 6)), cands).utama == [1, 2, 3, 4, 5, 6]


class _Editor:
    name = "editor"

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def summarize(self, prompt):
        self.prompts.append(prompt)
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestChoose:
    def test_valid_on_the_first_try(self, cands):
        choice, fallback, reasons = ne.choose(_Editor(_editor()), cands, D)
        assert (choice.utama, fallback, reasons) == ([1, 4, 7, 2, 9, 6], False, [])

    def test_a_refusal_is_asked_again_with_its_reason(self, cands):
        e = _Editor(_editor(utama=(1, 2, 3, 4, 7, 9)), _editor())
        choice, fallback, reasons = ne.choose(e, cands, D)
        assert (fallback, reasons) == (False, ["rules"])
        assert "Jawaban sebelumnya ditolak: lebih dari 2 berita utama dari rubrik Pasar" in e.prompts[1]

    def test_two_refusals_fall_back(self, cands):
        choice, fallback, reasons = ne.choose(_Editor("x", "y"), cands, D)
        assert (fallback, reasons) == (True, ["json", "json"])
        assert choice.utama == ne.deterministic(cands).utama

    def test_a_quota_falls_back_without_a_retry(self, cands):
        e = _Editor(QuotaExhausted("429"))
        assert ne.choose(e, cands, D)[1:] == (True, ["quota"]) and len(e.prompts) == 1

    def test_a_failed_call_is_retried(self, cands):
        choice, fallback, reasons = ne.choose(_Editor(SummarizerError("timeout"), _editor()), cands, D)
        assert (fallback, reasons) == (False, ["error"])

    def test_no_provider_is_the_fallback_without_a_call(self, cands):
        assert ne.choose(None, cands, D)[1:] == (True, ["no_provider"])


class TestDeterministic:
    def test_by_portal_count_under_the_quotas(self, cands):
        choice = ne.deterministic(cands)
        # 2 non-finance reserved (g1 7, l1 4), then finance by portals; Pasar capped at 2 (m3 is out)
        assert choice.utama == [1, 4, 7, 2, 6, 9]
        assert [i for i, _ in choice.sixty] == [1, 4, 7, 2]
        assert choice.sixty[0][1] == "Sekilas m1."

    def test_finance_first_when_no_non_finance_reached_three_portals(self):
        cands = ne.candidates(_sections([("markets", [("m1", 9), ("m2", 2)]), ("macro_policy", [("p1", 2)]),
                                         ("corporate", [("c1", 2)]), ("politics_government", [("g1", 2), ("g2", 2)]),
                                         ("law_crime", [("l1", 2)])]))
        utama = ne.deterministic(cands).utama
        # every finance story is taken before any non-finance one; ties keep their rank order
        assert utama == [1, 2, 3, 4, 5, 6] and 7 not in utama

    def test_one_story_per_duplicate_group(self, cands):
        assert 2 not in ne.deterministic(cands, groups=[{1, 2}]).utama


class TestRenderAndBudget:
    def test_the_edition(self, cands):
        choice = ne.Choice([1, 4, 7, 2, 9, 6], [(1, "Satu."), (4, "Dua."), (7, "Tiga.")])
        md, words, sekilas = ne.render(cands, choice, D, 1798, 24, 90)
        assert md.index("## Hari Ini dalam 60 Detik") < md.index("## Berita Utama") < md.index("## Sekilas")
        assert "- Satu.\n- Dua.\n- Tiga." in md
        assert md.count("### ") == 6
        assert "### [Judul m1](http://x/m1)\n\nInti m1 senilai Rp2.574.000.\n\n- Poin m1." in md
        assert "**Diberitakan 11 portal** · [Baca di Kontan →](http://x/m1)" in md
        assert [s.line for s in sekilas] == ["- **Pasar ·** Sekilas m3.", "- **Makro ·** Sekilas p2.",
                                             "- **Politik ·** Sekilas g2.", "- **Hukum ·** Sekilas l2.",
                                             "- **Internasional ·** Sekilas i1."]
        assert [s.id for s in sekilas] == [3, 5, 8, 10, 11]
        assert "Disarikan dari 1.798 artikel di 24 portal." in md and "Edisi lengkap memuat 90 berita." in md
        assert words == ne.reader_words(md)

    def test_a_duplicate_of_a_top_story_is_not_in_sekilas_and_a_group_shows_once(self, cands):
        choice = ne.Choice([1, 4, 7, 2, 9, 6], [(1, "Satu."), (4, "Dua."), (7, "Tiga.")], [{1, 3}, {8, 11}])
        lines = [s.line for s in ne.render(cands, choice, D, 10, 3, 11)[2]]
        assert not any("m3" in l for l in lines)
        assert any("g2" in l for l in lines) and not any("i1" in l for l in lines)

    def test_a_story_without_a_summary_is_a_headline_in_sekilas_and_the_edition_says_so(self):
        cands = ne.candidates(_sections([("markets", [("m1", 5), ("m2", (4, False))])]))
        md, _, sekilas = ne.render(cands, ne.Choice([1], [(1, "Satu.")]), D, 10, 3, 2)
        assert sekilas == [ne.SekilasLine("- **Pasar ·** Portal m2", True, 2)]
        assert "> Sebagian ringkasan tidak tersedia hari ini. 1 berita hanya ditampilkan judulnya." in md

    def test_the_word_budget_drops_sekilas_from_the_bottom_never_a_top_story(self, cands, monkeypatch):
        choice = ne.Choice([1, 4, 7, 2, 9, 6], [(1, "Satu."), (4, "Dua."), (7, "Tiga.")])
        full_md, full_words, full = ne.render(cands, choice, D, 10, 3, 11)
        monkeypatch.setattr(ne, "WORD_BUDGET", full_words - 4)
        md, words, kept = ne.render(cands, choice, D, 10, 3, 11)
        assert words <= ne.WORD_BUDGET and kept == full[:len(kept)] and len(kept) < len(full)
        assert md.count("### ") == 6

    def test_over_budget_with_no_sekilas_left_keeps_the_top_stories(self, cands, monkeypatch):
        monkeypatch.setattr(ne, "WORD_BUDGET", 10)
        md, words, kept = ne.render(cands, ne.Choice([1, 4, 7, 2, 9, 6], [(1, "a.")]), D, 10, 3, 11)
        assert kept == [] and md.count("### ") == 6 and "## Sekilas" not in md

    def test_reader_words_skip_link_targets_and_separators(self):
        assert ne.reader_words("### [Judul satu](http://a.b/c-d-e)\n**Diberitakan 3 portal** · [Baca →](http://x)") == 6


class TestBuildAndBriefing:
    def test_nothing_summarized_is_no_edition(self):
        assert ne.build(None, _sections([("markets", [("m1", (5, False))])]), D, 1, 1) is None

    def test_the_briefing_reads_the_message_back_from_the_file(self, cands):
        md = ne.render(cands, ne.Choice([1, 4, 7, 2, 9, 6], [(1, "Satu."), (4, "Dua."), (7, "Tiga.")]),
                       D, 10, 3, 11)[0]
        assert ne.briefing(md) == (["Satu.", "Dua.", "Tiga."], 6)

    def test_the_edition_path(self):
        assert ne.edition_path(os.path.join("digests", "2026-10-04.md")) == os.path.join("digests",
                                                                                          "2026-10-04-ringkas.md")


# ── In the generator ────────────────────────────────────────────────────────

def _a(i, topic, cluster, source):
    return {"sitemap_id": i, "headline": f"Berita {i}", "source": source, "category": "news", "link": f"http://x/{i}",
            "posted_at": 20261004, "topic": topic, "l1_text": f"isi {i}", "_cluster": cluster}


ARTS = [_a(10 * c + k, topic, c, src)
        for c, topic in enumerate(["markets", "markets", "law_crime", "politics_government"])
        for k, src in enumerate(["KONTAN", "DETIK", "KOMPAS"])]


def _generate(monkeypatch, tmp_path, summarizer):
    ds = MagicMock()
    gen = ng.NewsletterGenerator(ds, summarizer=summarizer, embed_documents=lambda t: [[0.0]] * len(t))
    monkeypatch.setattr(ng, "NEWSLETTER_MIN_CLUSTER_SIZE", 2)
    monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path))
    monkeypatch.setattr(gen, "_cluster", lambda vectors: [int(v[0]) for v in vectors])
    monkeypatch.setattr(gen, "_merge_across_sections", lambda entries, vectors: entries)
    monkeypatch.setattr(gen, "_encode", lambda texts: [[a["_cluster"]] for a in ARTS])
    ds.get_articles_for_date.return_value = ARTS
    return gen.generate(D), ds


class TestInTheGenerator:
    def test_both_files_and_the_row(self, monkeypatch, tmp_path):
        path, ds = _generate(monkeypatch, tmp_path, FakeNewsroom())
        assert path.edition == str(tmp_path / "2026-10-04-ringkas.md") and os.path.exists(path.edition)
        digest = open(path, encoding="utf-8").read()
        assert digest.count("### ") == 4                           # the archive still holds every shown story
        stats = ds.save_digest.call_args.kwargs["categories"][ng.EDITION_KEY]
        assert stats["built"] and stats["utama"] == 4 and stats["editor_fallback"] is True
        assert stats["editor_rejections"] == ["json", "json"] and stats["words"] <= ne.WORD_BUDGET
        assert ds.save_digest.call_args.kwargs["file_path"] == str(path)

    def test_the_editor_is_one_call_after_the_summaries(self, monkeypatch, tmp_path):
        s = FakeNewsroom(editor=[_editor(utama=(1, 3, 2, 4))])
        path, ds = _generate(monkeypatch, tmp_path, s)
        assert len(s.prompts["editor"]) == 1 and len(s.prompts["story"]) == 4
        assert ds.save_digest.call_args.kwargs["categories"][ng.EDITION_KEY]["editor_fallback"] is False

    def test_an_edition_that_fails_costs_nothing_but_itself(self, monkeypatch, tmp_path):
        stale = tmp_path / "2026-10-04-ringkas.md"
        stale.write_text("yesterday's run", encoding="utf-8")
        monkeypatch.setattr(ne, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        path, ds = _generate(monkeypatch, tmp_path, FakeNewsroom())
        assert open(path, encoding="utf-8").read().count("### ") == 4
        assert path.edition is None and not stale.exists()
        assert "5-minute edition not built: RuntimeError: boom" in path.note
        assert ds.save_digest.call_args.kwargs["categories"][ng.EDITION_KEY] == {"built": False,
                                                                                 "reason": "RuntimeError: boom"}

    def test_once_the_calls_stopped_the_editor_is_not_asked(self, monkeypatch, tmp_path):
        s = FakeNewsroom(story=[lambda p: FakeNewsroom().summarize(p), QuotaExhausted("429")])
        path, ds = _generate(monkeypatch, tmp_path, s)
        assert s.prompts["editor"] == []
        assert ds.save_digest.call_args.kwargs["categories"][ng.EDITION_KEY]["editor_rejections"] == ["no_provider"]
