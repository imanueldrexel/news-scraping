"""SYS-67 (#215), the acceptance check the unit tests cannot give: on a real day's
clusters, does the real summarizer put every angle of one incident in one story, keep
unrelated cases apart, and leave an incident at most NEWSLETTER_MAX_CLUSTERS_PER_STORY
of the section's slots?

It calls the configured summarizer (a few calls, a fraction of a cent) and a model is
not deterministic, so it only runs when asked:

    $env:RUN_LIVE_LLM = "1"; venv\Scripts\python.exe -m pytest tests/integration/test_story_grouping_live.py -q

The fixtures are real pools saved by scripts/experiments/probe_story_grouping.py with
the incidents annotated by hand (`expect`). The 2026-09-28 pool is the ticket's own
example: Lapas Cibinong filled 5 of 8 Hukum slots."""
import glob
import json
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_LLM") != "1", reason="live model call: set RUN_LIVE_LLM=1")

FIXTURES = sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                         "fixtures", "story_grouping_*.json")))
ANNOTATED = [p for p in FIXTURES if json.load(open(p, encoding="utf-8"))["expect"]["together"]]


@pytest.mark.parametrize("path", ANNOTATED, ids=[os.path.basename(p) for p in ANNOTATED])
def test_one_incident_is_one_story_and_unrelated_cases_stay_apart(path):
    from newscrawler.core.story_grouping import group_clusters
    from newscrawler.core.summarizer import build_summarizer
    import newscrawler.core.newsletter_generator as ng
    fixture = json.load(open(path, encoding="utf-8"))
    summarizer = build_summarizer()
    if summarizer is None:
        pytest.skip("no summarizer configured")
    clusters = [{"articles": [{"headline": h} for h in c["headlines"]]} for c in fixture["clusters"]]
    answers = [sorted(sorted(g) for g in group_clusters(summarizer, clusters)) for _ in range(3)]
    assert answers[0] == answers[1] == answers[2], f"the grouping is not stable: {answers}"
    group_of = {i: n for n, g in enumerate(answers[0]) for i in g}
    for together in fixture["expect"]["together"]:
        assert len({group_of[i] for i in together}) == 1, f"one incident split into several stories: {answers[0]}"
    for a, b in fixture["expect"]["apart"]:
        assert group_of[a] != group_of[b], f"clusters {a} and {b} are different cases but were grouped"
    shown = ng.pick_shown(clusters, answers[0], ng.NEWSLETTER_MAX_CLUSTERS_PER_STORY,
                          ng.NEWSLETTER_MAX_CLUSTERS_PER_TOPIC)
    for together in fixture["expect"]["together"]:
        taken = sum(1 for c in shown if clusters.index(c) in together)
        assert taken <= ng.NEWSLETTER_MAX_CLUSTERS_PER_STORY
