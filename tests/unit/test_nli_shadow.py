"""SYS-198 (#428, ADR-024): the NLI shadow pass. A stub scorer stands in for the model; nothing here loads one."""
from datetime import date
from types import SimpleNamespace

import pytest

from newscrawler.core import nli_check, nli_shadow
from newscrawler.core.story_arc import StoryArc
from newscrawler.core.thread_finder import TimelineItem

TODAY = date(2026, 10, 25)


class Stub:
    """Entailment = the share of the hypothesis' words found in the premise; records every pair it is asked."""
    revision = "stub@1"

    def __init__(self):
        self.pairs = []

    def score(self, pairs):
        self.pairs += list(pairs)
        out = []
        for premise, hypothesis in pairs:
            h = set(hypothesis.lower().split())
            e = len(h & set(premise.lower().split())) / max(len(h), 1)
            out.append((e, 1 - e, 0.0))
        return out


def article(i, headline, opening):
    return {"sitemap_id": i, "source": "KOMPAS", "headline": headline, "l1_text": opening, "link": f"http://x/{i}"}


def edition(arc, articles, cid=1):
    cand = SimpleNamespace(id=cid, cluster={"articles": articles})
    return SimpleNamespace(trace={"candidates": [cand], "arcs": [{"id": cid, "arc": arc, "timeline": []}]},
                           markdown="# edisi\n")


def arc(**kw):
    base = dict(judul="Harga naik", hari_ini="Harga beras naik karena pasokan seret. Pemerintah diduga lambat.",
                latar="", agenda="", sekilas="Harga beras naik.", terkait=[0], tidak_terkait=[], alur=[],
                alur_items=[])
    base.update(kw)
    return StoryArc(**base)


ARTICLES = [article(11, "Harga beras naik", "Harga beras naik karena pasokan seret. Menteri membantah.")]


class TestPremiseUnits:
    def test_sentences_and_adjacent_pairs_without_repeats(self):
        units = nli_check.premise_units(["Satu dua. Tiga empat. Lima enam.", "Satu dua."])
        assert units == ["Satu dua.", "Satu dua. Tiga empat.", "Tiga empat.", "Tiga empat. Lima enam.", "Lima enam."]

    def test_capped(self):
        text = " ".join(f"Kalimat nomor {i}." for i in range(200))
        assert len(nli_check.premise_units([text])) == nli_check.MAX_PREMISES


class TestBestVerdict:
    def test_picks_the_most_entailed_premise(self):
        v = nli_check.best_verdict(Stub(), ["Hujan deras turun. Harga beras naik karena pasokan."],
                                   "harga beras naik karena pasokan.")
        assert v.p_entail == 1.0 and "pasokan" in v.premise and v.revision == "stub@1"

    @pytest.mark.parametrize("scorer,premises,hyp", [(None, ["a b"], "a"), (Stub(), [], "a"), (Stub(), ["a b"], "  ")])
    def test_no_verdict_without_the_inputs(self, scorer, premises, hyp):
        assert nli_check.best_verdict(scorer, premises, hyp) is None

    def test_a_failing_scorer_is_no_verdict(self):
        class Boom:
            revision = "x"

            def score(self, pairs):
                raise RuntimeError("oom")
        assert nli_check.best_verdict(Boom(), ["Satu dua."], "satu") is None

    def test_a_scorer_that_miscounts_is_no_verdict(self):
        class Short:
            revision = "x"

            def score(self, pairs):
                return []
        assert nli_check.best_verdict(Short(), ["Satu dua."], "satu") is None


class TestGateTags:
    @pytest.mark.parametrize("sentence,tag", [
        ("Harga naik karena pasokan seret.", "cause"),
        ("Pemerintah diduga lambat.", "hedge"),
        ("Menteri membantah kabar itu.", "denial"),
        ("Kebijakan berlaku hingga November 2026.", "end"),
    ])
    def test_a_family_it_matches(self, sentence, tag):
        assert tag in nli_shadow.gate_tags(sentence).split(",")

    def test_the_residual_has_no_tag(self):
        assert nli_shadow.gate_tags("Harga beras di Jakarta Rp15.000 per kilogram.") is None


class TestBuildRows:
    def test_one_row_per_sentence_with_premises_and_verdict(self):
        stub = Stub()
        rows = nli_shadow.build_rows(edition(arc(), ARTICLES), TODAY, stub, budget_s=60)
        assert [r["field"] for r in rows] == ["judul", "hari_ini", "hari_ini", "sekilas"]
        assert all(r["premise_ids"] == [11] and r["p_entail"] is not None and r["edition_date"] == TODAY
                   for r in rows)
        cause = next(r for r in rows if "pasokan" in r["sentence"])
        assert "cause" in cause["error_tags"] and cause["model_revision"] == "stub@1"
        hedge = next(r for r in rows if "diduga" in r["sentence"])
        assert "hedge" in hedge["error_tags"]

    def test_the_premises_are_what_the_gate_reads_the_alur_items_included(self):
        item = TimelineItem(77, date(2026, 10, 20), "TEMPO", "Stok beras menipis", "Stok menipis sejak pekan lalu.",
                            0.8, 3)
        stub = Stub()
        rows = nli_shadow.build_rows(edition(arc(alur=[1], alur_items=[item]), ARTICLES), TODAY, stub, 60)
        assert rows[0]["premise_ids"] == [11, 77]
        assert any("Stok menipis" in premise for premise, _ in stub.pairs)

    def test_a_spent_time_budget_leaves_the_rest_without_a_verdict(self):
        ticks = iter([0, 0, 100, 100, 100, 100, 100, 100, 100])
        rows = nli_shadow.build_rows(edition(arc(), ARTICLES), TODAY, Stub(), budget_s=10, clock=lambda: next(ticks))
        assert rows[0]["p_entail"] is not None
        assert all(r["p_entail"] is None and r["model_revision"] is None for r in rows[1:])

    def test_an_edition_without_arcs_has_no_rows(self):
        ed = SimpleNamespace(trace={"candidates": [], "arcs": []}, markdown="x")
        assert nli_shadow.build_rows(ed, TODAY, Stub(), 60) == []


class TestRecord:
    def test_saves_the_rows_and_counts(self):
        saved = []
        stats = nli_shadow.record(edition(arc(), ARTICLES), TODAY, lambda d, rows: saved.append((d, rows)),
                                  Stub(), 60)
        assert stats == {"sentences": 4, "scored": 4} and saved[0][0] == TODAY and len(saved[0][1]) == 4

    def test_a_save_failure_never_reaches_the_edition(self):
        def save(d, rows):
            raise RuntimeError("db down")
        ed = edition(arc(), ARTICLES)
        before = ed.markdown
        assert nli_shadow.record(ed, TODAY, save, Stub(), 60) == {"sentences": 0, "scored": 0}
        assert ed.markdown == before

    def test_no_model_records_nothing(self):
        saved = []
        assert nli_shadow.record(edition(arc(), ARTICLES), TODAY, lambda d, r: saved.append(r), None, 60)["sentences"] == 0
        assert saved == []

    def test_reading_the_arc_does_not_change_it(self):
        a = arc()
        snapshot = (a.judul, a.hari_ini, a.latar, a.agenda, a.sekilas, list(a.terkait))
        nli_shadow.record(edition(a, ARTICLES), TODAY, lambda d, r: None, Stub(), 60)
        assert (a.judul, a.hari_ini, a.latar, a.agenda, a.sekilas, list(a.terkait)) == snapshot


class TestWiring:
    def _generator(self, monkeypatch, on):
        from newscrawler.core import newsletter_generator as g
        calls = []
        monkeypatch.setattr(g, "NLI_SHADOW", on)
        monkeypatch.setattr(g.nli_shadow, "record", lambda *a, **k: calls.append(a))
        gen = g.NewsletterGenerator.__new__(g.NewsletterGenerator)
        gen.ds = SimpleNamespace(save_nli_shadow=lambda *a: None)
        return gen, calls

    def test_off_by_default_records_nothing(self, monkeypatch):
        gen, calls = self._generator(monkeypatch, False)
        gen._nli_shadow(edition(arc(), ARTICLES), TODAY)
        assert calls == []

    def test_on_records_only_an_edition_with_arcs(self, monkeypatch):
        gen, calls = self._generator(monkeypatch, True)
        gen._nli_shadow(SimpleNamespace(trace={}), TODAY)
        gen._nli_shadow(edition(arc(), ARTICLES), TODAY)
        assert len(calls) == 1
