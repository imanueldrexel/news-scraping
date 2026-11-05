"""QA's failing tests for SYS-198 (#428): qa-defects #436-#439, copied unchanged from the issues.

Only the module layout differs: the four issues' imports and helpers sit at the top, each test as written.
"""
import glob
import importlib
import logging
import os
import sys
from datetime import date
from types import SimpleNamespace

from newscrawler.core import nli_check, nli_shadow
from newscrawler.core.story_arc import StoryArc
from newscrawler.core.thread_finder import TimelineItem

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


# ---- #436: preview/replay tools must not write nli_shadow ----
class Session:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, *a, **k):
        self.log.append(str(stmt).strip().split()[0].upper())

    def commit(self):
        self.log.append("COMMIT")


def test_preview_datasource_writes_nothing_to_nli_shadow():
    preview = importlib.import_module("preview_newsletter")
    log = []
    ds = preview.ReadOnlyNewsletterDataSource.__new__(preview.ReadOnlyNewsletterDataSource)
    ds.client = SimpleNamespace(get_session=lambda: Session(log))
    row = {"edition_date": date(2026, 11, 3), "story_id": 1, "field": "x", "sentence": "s", "error_tags": None,
           "premise_ids": [1], "best_premise": None, "p_entail": None, "p_neutral": None, "p_contradict": None,
           "model_revision": None}
    ds.save_nli_shadow(date(2026, 11, 3), [row])
    assert not any(s in ("DELETE", "INSERT", "COMMIT") for s in log), log


# ---- #437: the alur quotes are scored, whatever the story's size ----
class Exact:
    revision = "exact@1"

    def score(self, pairs):
        return [((0.99, 0.005, 0.005) if h.rstrip(".").lower() in p.lower() else (0.05, 0.5, 0.45)) for p, h in pairs]


def test_a_sentence_supported_by_an_alur_item_is_scored_against_it():
    def body(i):
        return " ".join(f"Kalimat {k} berita {i} tentang rapat anggaran daerah." for k in range(6))
    shown = [{"sitemap_id": i, "source": f"S{i}", "headline": f"Judul berita {i}", "l1_text": body(i),
              "link": f"http://x/{i}"} for i in range(1, 7)]
    item = TimelineItem(99, date(2026, 10, 20), "TEMPO", "Gudang Bulog terbakar",
                        "Gudang Bulog di Karawang terbakar pada 20 Oktober.", 0.8, 3)
    arc = StoryArc(judul="Bulog", hari_ini="", latar="Gudang Bulog di Karawang terbakar pada 20 Oktober.", agenda="",
                   sekilas="", terkait=list(range(6)), tidak_terkait=[], alur=[6], alur_items=[item])
    cand = SimpleNamespace(id=7, cluster={"articles": shown})
    edition = SimpleNamespace(trace={"candidates": [cand], "arcs": [{"id": 7, "arc": arc, "timeline": []}]})
    rows = nli_shadow.build_rows(edition, date(2026, 11, 3), Exact(), budget_s=60)
    latar = next(r for r in rows if r["field"] == "latar")
    assert 99 in latar["premise_ids"]
    assert latar["p_entail"] > 0.9, latar["best_premise"]


# ---- #438: a missing model is one load attempt and one WARNING ----
def test_a_missing_model_is_one_warning_and_one_load_attempt(monkeypatch, caplog):
    loads = []

    def boom(self):
        loads.append(1)
        raise OSError("model 'nope/missing' not found")
    monkeypatch.setattr(nli_check.HfScorer, "_load", boom)
    arc = StoryArc(judul="Satu", hari_ini="Satu dua tiga. Empat lima enam. Tujuh delapan sembilan.", latar="",
                   agenda="", sekilas="", terkait=[0], tidak_terkait=[], alur=[], alur_items=[])
    art = {"sitemap_id": 1, "source": "A", "headline": "Satu", "l1_text": "Satu dua tiga.", "link": "http://x/1"}
    cand = SimpleNamespace(id=7, cluster={"articles": [art]})
    edition = SimpleNamespace(trace={"candidates": [cand], "arcs": [{"id": 7, "arc": arc, "timeline": []}]})
    caplog.set_level(logging.WARNING)
    rows = nli_shadow.build_rows(edition, date(2026, 11, 3), nli_check.HfScorer("nope/missing"), budget_s=60)
    assert rows and all(r["p_entail"] is None for r in rows)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and len(loads) == 1, (len(warnings), len(loads), len(rows))


# ---- #439: the Done-when integration test exists ----
def test_an_integration_test_replays_an_edition_with_nli_on_and_off():
    found = []
    for path in glob.glob(os.path.join(ROOT, "tests/integration/**/*.py"), recursive=True):
        src = open(path, encoding="utf-8").read()
        if "NLI_SHADOW" in src and ("_write_edition" in src or ".generate(" in src) and "nli_shadow" in src:
            found.append(path)
    assert found, "no integration test runs the edition with NLI_SHADOW on/off and checks bytes + rows"
