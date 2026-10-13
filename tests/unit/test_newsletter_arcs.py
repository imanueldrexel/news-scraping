"""SYS-149 (#339): the story arcs in the 5-minute edition, behind NEWSLETTER_ARCS.

Off, the edition is today's. On: the editor picks 3-4 top stories under
POLICY_ARCS, each is told as pure prose (no labels) from its timeline in NEWS_L1,
a refused arc falls back to its summary as prose, the budget trims Sekilas first
and then moves the 4th story to Sekilas, and the row carries the arcs' counts
and the stories SYS-151 will read."""
from datetime import date

import pytest

import newscrawler.core.newsletter_edition as ne
from newscrawler.core.summarizer import QuotaExhausted
from tests.unit.newsletter_fakes import FakeNewsroom
from tests.unit.test_newsletter_summaries import _day, _gen

DAY = date(2026, 9, 29)
ROW = {"headline": "Lini masa: rapat pertama digelar", "source": "CNBC", "posted_at": 20260920,
       "l1_text": "Rapat pertama digelar pekan lalu."}


def _plan(monkeypatch, summarizer, n=8, hits=(), rows=None):
    gen, ds = _gen(monkeypatch, summarizer)
    arts = _day(n)
    ds.get_articles_for_date.return_value = arts
    monkeypatch.setattr(gen, "_encode", lambda texts: [[a["_cluster"] + 1.0] for a in arts])
    searched = []
    gen._search_l1 = lambda vector, k: searched.append((vector, k)) or list(hits)
    ds.get_timeline_rows.side_effect = lambda ids: {i: (rows or {})[i] for i in ids if i in (rows or {})}
    return gen, gen.plan(DAY), searched


def _top_stories(markdown):
    return markdown.split(f"## {ne.copy.TOP_STORIES}")[1].split(f"## {ne.copy.AT_A_GLANCE}")[0]


class TestOff:
    def test_off_is_todays_edition(self, monkeypatch):
        gen, plan, searched = _plan(monkeypatch, FakeNewsroom())
        import newscrawler.core.newsletter_generator as ng
        monkeypatch.setattr(ng, "NEWSLETTER_ARCS", False)   # build_edition() follows the switch
        default, off = gen.build_edition(plan), gen.build_edition(plan, arcs=False)
        assert default.markdown == off.markdown and "arcs" not in off.stats() and "stories" not in off.stats()
        assert searched == [] and off.utama == 6


class TestOn:
    def test_three_to_four_top_stories_told_in_prose(self, monkeypatch):
        s = FakeNewsroom()
        gen, plan, _ = _plan(monkeypatch, s)
        edition = gen.build_edition(plan, arcs=True)
        assert 3 <= edition.utama <= 4 and len(s.prompts["arc"]) == edition.utama
        top = _top_stories(edition.markdown)
        assert not [line for line in top.splitlines() if line.startswith("- ")]       # no bullets
        assert ne.copy.WHY_IT_MATTERS not in top                                       # no labels
        assert "alur cerita ditulis AI dari artikel 30 hari terakhir" in edition.markdown
        assert "pilih 3-4 id" in s.prompts["editor"][0] and "paling sedikit 1 berita" in s.prompts["editor"][0]

    def test_the_arc_reads_its_timeline_and_never_todays_articles(self, monkeypatch):
        s = FakeNewsroom()
        hits = [(1, 20260920, 0.95),            # an article of today's first story: excluded
                (901, 20260920, 0.80)]
        today = dict(ROW, headline="Artikel hari ini sendiri")
        gen, plan, searched = _plan(monkeypatch, s, hits=hits, rows={901: ROW, 1: today})
        gen.build_edition(plan, arcs=True)
        first = s.prompts["arc"][0]
        assert "LINI MASA\n[2] Minggu, 20 Sep · CNBC Indonesia — Lini masa: rapat pertama digelar" in first
        assert "Artikel hari ini sendiri" not in first          # today's own article is never its back-story
        from newscrawler.core.constants import ARC_FETCH_K
        assert searched and len(searched[0][0]) == 1 and searched[0][1] == ARC_FETCH_K

    def test_the_story_is_the_arcs_prose_not_the_summarys_bullets(self, monkeypatch):
        from tests.unit.newsletter_fakes import arc_answer, story_answer
        s = FakeNewsroom(story=[lambda p: story_answer(p, poin=["Poin ringkasan yang tidak dipakai."],
                                                       mengapa_penting="Alasan ringkasan.")] * 20,
                         arc=[lambda p: arc_answer(p, hari_ini="Paragraf hari ini dari arc.",
                                                   latar="Paragraf latar dari arc.")] * 4)
        gen, plan, _ = _plan(monkeypatch, s)
        top = _top_stories(gen.build_edition(plan, arcs=True).markdown)
        assert "Paragraf hari ini dari arc.\n\nParagraf latar dari arc." in top
        assert "Poin ringkasan yang tidak dipakai." not in top and ne.copy.WHY_IT_MATTERS not in top

    def test_a_refused_arc_falls_back_to_its_summary_as_prose(self, monkeypatch):
        gen, plan, _ = _plan(monkeypatch, FakeNewsroom(arc=["x", "y"]))
        edition = gen.build_edition(plan, arcs=True)
        assert edition.arcs["fallback"] == 1 and edition.arcs["refusals"]["json"] == 2
        first = ne.copy.TOP_STORIES
        story = edition.trace["candidates"][edition.trace["choice"].utama[0] - 1].story
        assert f"\n\n{story.inti}\n\n" in edition.markdown.split(first)[1]

    def test_a_quota_stops_the_arcs(self, monkeypatch):
        s = FakeNewsroom(arc=[QuotaExhausted("429")])
        gen, plan, _ = _plan(monkeypatch, s)
        edition = gen.build_edition(plan, arcs=True)
        assert edition.arcs["stopped"] == "quota" and len(s.prompts["arc"]) == 1
        assert edition.arcs["built"] == 0 and edition.arcs["fallback"] == edition.utama

    def test_stats_and_stories(self, monkeypatch):
        gen, plan, _ = _plan(monkeypatch, FakeNewsroom())
        stats = gen.build_edition(plan, arcs=True).stats()
        assert stats["arcs"]["built"] == stats["utama"] and stats["arcs"]["no_history"] == stats["utama"]
        assert set(stats["arcs"]) == {"built", "fallback", "refusals", "alur_items", "no_history", "agenda",
                                      "demoted", "errors", "stopped"}
        assert len(stats["stories"]) == stats["utama"]
        first = stats["stories"][0]
        assert first["arc"] is True and first["alur_ids"] == [] and len(first["terkait_ids"]) == 2

    def test_no_summarizer_is_every_story_in_prose_without_calls(self, monkeypatch):
        gen, plan, _ = _plan(monkeypatch, FakeNewsroom())
        edition = ne.build(None, plan.sections, DAY, len(plan.articles), 1, "no_provider", arcs=gen._arc_inputs(plan))
        assert edition.arcs["stopped"] == "no_provider" and edition.arcs["built"] == 0
        assert "alur cerita" in edition.markdown and edition.stories and not edition.stories[0]["arc"]


class TestBudget:
    def test_sekilas_first_then_the_fourth_story_moves_to_sekilas(self, monkeypatch):
        gen, plan, _ = _plan(monkeypatch, FakeNewsroom(), n=10)
        monkeypatch.setattr(ne, "WORD_BUDGET", 10)
        edition = gen.build_edition(plan, arcs=True)
        assert edition.utama == 3
        assert all(s.guaranteed for s in edition.trace["kept"])          # every droppable line went first
        moved = [s for s in edition.trace["kept"] if s.id not in edition.trace["choice"].utama]
        assert moved and len(edition.stats()["stories"]) == 3

    def test_today_never_moves_a_top_story(self, monkeypatch):
        gen, plan, _ = _plan(monkeypatch, FakeNewsroom(), n=10)
        monkeypatch.setattr(ne, "WORD_BUDGET", 10)
        assert gen.build_edition(plan, arcs=False).utama == 6


@pytest.mark.parametrize("words", ["Kronologi", "Agenda berikutnya", "Berlanjut sejak", "Kilas balik"])
def test_no_in_story_label_exists_in_the_copy(words):
    """Owner decision 7 (2026-10-13): pure prose -- the declined labels are not reader strings."""
    import newscrawler.core.newsletter_copy as copy
    texts = [v for v in vars(copy).values() if isinstance(v, str)]
    assert not [t for t in texts if words in t]


def test_the_switch_is_off_unless_set():
    """NEWSLETTER_ARCS defaults to off: arcs replace today's edition only after the owner's A/B (SYS-150)."""
    import os
    import subprocess
    import sys
    code = "from newscrawler.core import constants as c; print(c.NEWSLETTER_ARCS)"
    env = {k: v for k, v in os.environ.items() if k != "NEWSLETTER_ARCS"}
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    unset = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=root)
    on = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                        env=dict(env, NEWSLETTER_ARCS="1"), cwd=root)
    assert (unset.stdout.strip(), on.stdout.strip()) == ("False", "True")
