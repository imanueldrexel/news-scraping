"""QA 2026-10-13: QA's own tests for the dev's fixes of QA's second-pass list and the open P2/P3s.

Written from each ticket's Symptom / Fix / Done-when with inputs the dev's tests do not use
(held-out refusals, adverbs, numeric forms, AST shapes). Run:

    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_2026_10_13/test_qa_audit.py -q -p no:cacheprovider

A failing test here is a finding, recorded in .10x/reviews/2026-10-13-qa-report.md.
"""
import ast
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from newscrawler.core.summarizer import Reply  # noqa: E402
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO, posted_at_datetime  # noqa: E402
from newscrawler.web import followup, keywords  # noqa: E402
from newscrawler.web.filters import Filters  # noqa: E402
from tests.unit.test_query_processor_ranking import TODAY, _hit, _qp, _usage  # noqa: E402


# ── SYS-143 (#326): refusals and list items are not queries ──────────────────────────────────────

class TestSys143HeldOutRefusals:
    """ADR-010 decision 3: the rewrite 'must not be a refusal or a list'. The dev's cases start with
    maaf / saya tidak dapat / sebagai AI / sorry; these are other refusal shapes a model writes."""

    @pytest.mark.parametrize("reply", [
        "Mohon maaf, pertanyaan ini tidak dapat ditulis ulang.",
        '"Maaf, saya tidak bisa membantu."',
        "Pertanyaan: Maaf, konteksnya kurang jelas.",
        "Saya tidak mampu menulis ulang pertanyaan itu.",
        "Sebagai asisten, saya hanya bisa menulis ulang pertanyaan.",
        "I'm sorry, but I can't help with that.",
    ])
    def test_the_named_shapes_are_refused(self, reply):
        assert followup.check(reply) is None

    @pytest.mark.parametrize("reply", [
        "Tidak dapat menulis ulang pertanyaan tersebut.",
        "Saya tidak memahami pertanyaan lanjutan ini.",
        "I am unable to rewrite this question.",
        "As an AI, I cannot rewrite this.",
    ])
    def test_held_out_refusal_shapes(self, reply):
        assert followup.check(reply) is None

    @pytest.mark.parametrize("reply", [
        "1. Apa itu Danantara? 2. Siapa pemimpinnya?",
        "• Berapa harga emas Antam hari ini?",
        "- Berapa harga emas Antam hari ini?",
    ])
    def test_list_items_are_refused(self, reply):
        assert followup.check(reply) is None

    @pytest.mark.parametrize("reply", [
        "Mengapa BI tidak dapat menurunkan suku bunga tahun ini?",
        "Saya ingin tahu harga emas Antam hari ini",
        "Sebagai BUMN, apa peran Danantara bagi Garuda Indonesia?",
        "1.000 pekerja Sritex di-PHK, apa kata Kemnaker?",
        "-5% IHSG hari ini, apa penyebabnya?",
        "Maafkan saya, kapan RUPS Garuda digelar?",
    ])
    def test_real_questions_pass(self, reply):
        assert followup.check(reply) == reply

    def test_a_question_that_opens_with_sebagai_model_bisnis_passes(self):
        """'sebagai model' is a refusal opener only when it is the model speaking."""
        q = "Sebagai model bisnis baru, bagaimana prospek GoTo tahun depan?"
        assert followup.check(q) == q


# ── SYS-144 (#327): -nya adverbs with no referent ────────────────────────────────────────────────

class TestSys144HeldOutAdverbs:
    """The ticket's class is 'adverbs ending in -nya with no referent'. The dev's list holds 22; these
    are common ones that are not on it."""

    @pytest.mark.parametrize("question", [
        "Apa sebaiknya dilakukan investor saham Garuda Indonesia?",
        "Apa sebetulnya yang terjadi pada Sritex?",
        "Bagaimana nantinya nasib karyawan Sritex?",
        "Sayangnya, apakah IHSG akan turun lagi?",
        "Kapan secepatnya Danantara membeli saham Garuda?",
        "Apakah Pertamina sepenuhnya menanggung subsidi BBM?",
    ])
    def test_a_held_out_adverb_is_not_a_back_reference(self, question):
        assert not followup.refers_back(question)

    @pytest.mark.parametrize("question", [
        "Sebenarnya apa yang terjadi pada Garuda?",       # capitalised at the start
        "Apa SELANJUTNYA untuk Sritex?",                    # upper case
    ])
    def test_listed_adverbs_in_any_case(self, question):
        assert not followup.refers_back(question)

    @pytest.mark.parametrize("question", [
        "Berapa target pertumbuhannya?", "Siapa tersangkanya?", "Bagaimana buyback-nya?",
        "Apa kata mereka?", "Kapan sidang tersebut?", "Apakah Sritex akhirnya membayar utangnya?",
    ])
    def test_real_references_still_are(self, question):
        assert followup.refers_back(question)


# ── SYS-145 (#328): a kept follow-up that refers back uses the thread (ADR-014) ──────────────────

PREV_ANTAM = ["Berapa harga emas Antam hari ini?"]


class TestSys145KeptThread:
    def test_the_fed_pair(self):
        q = "Bagaimana dampaknya ke rupiah?"
        r = followup.resolve(q, ["Apa keputusan The Fed terbaru?"], q)
        assert r.how == followup.KEPT_THREAD and "Fed" in r.text and r.cue_text == q

    def test_a_rewrite_that_differs_is_llm_even_when_it_refers_back(self):
        r = followup.resolve("Bagaimana dampaknya ke rupiah?", ["Apa keputusan The Fed terbaru?"],
                             "Bagaimana dampak keputusan The Fed ke rupiah?")
        assert r.how == followup.LLM

    def test_kept_with_case_and_space_differences_is_still_kept(self):
        q = "Bagaimana dampaknya ke rupiah?"
        r = followup.resolve(q, ["Apa keputusan The Fed terbaru?"], "  bagaimana  dampaknya ke Rupiah? ")
        assert r.how == followup.KEPT_THREAD

    @pytest.mark.parametrize("question", [
        # ADR-014's accepted risk: a topic switch whose -nya points at its OWN new subject.
        "Siapa CEO Garuda Indonesia dan berapa gajinya?",
        "Apa itu Danantara dan siapa pemimpinnya?",
        "Bagaimana kinerja saham BBCA dan dividennya tahun ini?",
        "Apa kata Sri Mulyani soal APBN dan apa yang ia rencanakan?",
    ])
    def test_a_kept_switch_whose_reference_is_inside_the_question_stays_kept(self, question):
        r = followup.resolve(question, PREV_ANTAM, question)
        assert r.how == followup.KEPT, r

    @pytest.mark.parametrize("question", [
        "Apa sebaiknya dilakukan investor saham Garuda Indonesia?",
        "Bagaimana nantinya nasib karyawan Sritex?",
    ])
    def test_a_kept_switch_with_a_held_out_adverb_stays_kept(self, question):
        """SYS-145 moved refers_back onto the LLM path: an adverb missing from SYS-144's list now
        pulls a model-approved topic switch back to the old thread."""
        r = followup.resolve(question, PREV_ANTAM, question)
        assert r.how == followup.KEPT, r


class _Rewriter:
    name = "deepseek-v4-flash"
    priced = True

    def __init__(self, text):
        self.text = text

    def complete(self, prompt):
        return Reply(self.text, 150, 20)


class TestSys143145Composed:
    OJK = [{"question": "Apa kata OJK soal kredit perbankan?", "answer": "-"}]

    def _qp(self, reply):
        qp = _qp(semantic=[_hit(1, semantic=0.9)], fts=[_hit(2, keyword=1.0)])
        qp.rewriter = _Rewriter(reply)
        qp.usage = _usage(0.0)
        return qp

    def test_a_quoted_refusal_falls_back_and_is_counted(self):
        qp = self._qp('"Mohon maaf, saya tidak dapat menulis ulang."')
        _, counts = qp.candidates("Berapa target pertumbuhannya tahun depan?", Filters(), TODAY, self.OJK)
        assert counts["rewrite"] == followup.FALLBACK_THREAD
        assert "maaf" not in qp.faiss_ds.search_l2.call_args.args[0].lower()
        qp.usage.increment_api_call_count.assert_called_once()

    def test_kept_thread_reads_the_cue_from_the_follow_up_only(self):
        thread = [{"question": "Kenapa rupiah melemah pekan ini?", "answer": "-"}]
        q = "Bagaimana dampaknya ke saham perbankan?"
        qp = self._qp(q)
        _, counts = qp.candidates(q, Filters(), TODAY, thread)
        assert counts["rewrite"] == followup.KEPT_THREAD
        assert counts["window"] is None and counts["recent"] is None   # "pekan ini" belongs to the thread


# ── SYS-138 (#317): the week window leads only on-subject hits (ADR-013) ─────────────────────────

def _dated(sid, days_old, semantic, **extra):
    d = TODAY - timedelta(days=days_old)
    return _hit(sid, semantic=semantic, posted_at=d.strftime("%Y%m%d"), posted_date=d, **extra)


class TestSys138SubjectGate:
    def test_subject_is_the_names_when_there_are_any(self):
        kq = keywords.KeywordQuery.build(
            [keywords.Term("danantara", True), keywords.Term("dividen", False)],
            {"danantara": 0.0005, "dividen": 0.002})
        assert kq.subject == ["danantara"]

    def test_subject_is_the_anchors_without_names(self):
        kq = keywords.KeywordQuery.build(
            [keywords.Term("dividen", False), keywords.Term("bank", False)], {"dividen": 0.002, "bank": 0.003})
        assert set(kq.subject) == {"dividen", "bank"}

    def test_an_off_subject_week_hit_ranks_in_the_unwindowed_list_not_dropped(self):
        week = _dated(1, 2, 0.70)
        older = _dated(2, 20, 0.60)
        qp = _qp(semantic=[week, older], subject=lambda kq, texts: [False] * len(texts))
        ids = [h["sitemap_id"] for h in qp.retrieve("Apa kabar Danantara pekan ini?", Filters(), TODAY)]
        assert sorted(ids) == [1, 2]

    def test_an_on_subject_week_hit_leads_a_closer_older_one(self):
        qp = _qp(semantic=[_dated(1, 20, 0.85), _dated(2, 3, 0.62)])
        ids = [h["sitemap_id"] for h in qp.retrieve("Apa kabar Danantara pekan ini?", Filters(), TODAY)]
        assert ids[:2] == [2, 1]

    def test_a_failed_subject_test_still_lets_keyword_hits_lead(self):
        def boom(kq, texts):
            raise RuntimeError("db down")
        week_kw = _dated(3, 2, 0.0, keyword=1.0)
        week_sem = _dated(1, 2, 0.70)
        older = _dated(2, 20, 0.90)
        qp = _qp(semantic=[week_sem, older], fts=[week_kw], subject=boom,
                 similarity=lambda q, texts, ids=None: [0.6] * len(texts))
        ids = [h["sitemap_id"] for h in qp.retrieve("Apa kabar Danantara pekan ini?", Filters(), TODAY)]
        assert ids[0] == 3 and 1 in ids and 2 in ids

    def test_only_leaders_count_toward_a_full_week(self):
        """Five passing this-week hits, all off-subject: the week is thin and older ones are fetched."""
        week = [_dated(i, i, 0.70) for i in range(1, 6)]
        qp = _qp(semantic=week + [_dated(9, 20, 0.90)], subject=lambda kq, texts: [False] * len(texts))
        _, counts = qp.candidates("Apa kabar Danantara pekan ini?", Filters(), TODAY)
        assert counts["window"] == "7d+0"


# ── DBT-60 (#258): a stored yyyymmdd is never read as Unix seconds ───────────────────────────────

class TestDbt60NumericForms:
    @pytest.mark.parametrize("value", [20260918, "20260918", " 20260918\n", 20260918.0])
    def test_the_tickets_forms(self, value):
        assert SitemapDTO(headline="h", link="l", sources="s", timestamp=value).timestamp == datetime(2026, 9, 18)

    @pytest.mark.parametrize("value", [
        pytest.param("20260918.0", id="str-float"),        # str(float) of a stored date
        pytest.param(Decimal("20260918"), id="Decimal"),   # psycopg2 returns NUMERIC as Decimal
        pytest.param("np.int64", id="numpy-int64"),        # pandas.read_sql of sitemaps.posted_at
        pytest.param("+20260918", id="signed-str"),
    ])
    def test_other_numeric_forms_are_the_date_or_refused_never_1970(self, value):
        if value == "np.int64":
            import numpy as np
            value = np.int64(20260918)
        try:
            ts = SitemapDTO(headline="h", link="l", sources="s", timestamp=value).timestamp
        except Exception:
            return                                          # refused is fine
        assert ts.replace(tzinfo=None) == datetime(2026, 9, 18), ts

    @pytest.mark.parametrize("value", ["1695000000.0", Decimal("1695000000")])
    def test_unix_seconds_are_never_accepted(self, value):
        with pytest.raises(Exception):
            SitemapDTO(headline="h", link="l", sources="s", timestamp=value)

    @pytest.mark.parametrize("value", ["2026-09-18", "2026-09-18T07:00:00", datetime(2026, 9, 18, 7)])
    def test_iso_and_datetimes_pass_through(self, value):
        assert SitemapDTO(headline="h", link="l", sources="s", timestamp=value).timestamp.date().isoformat() == "2026-09-18"

    def test_none_stays_none(self):
        assert posted_at_datetime(None) is None


# ── DBT-68 (#329): the shadow check ──────────────────────────────────────────────────────────────

class TestDbt68ShadowCheck:
    def _check(self, source):
        sys.path.insert(0, os.path.join(ROOT, "tests", "unit"))
        from test_repo_hygiene import _shadowed_names
        return _shadowed_names(source)

    def test_a_repeated_top_level_test_function(self):
        assert self._check("def test_a(): pass\n\ndef test_a(): pass\n") == ["test_a x2"]

    def test_a_class_and_a_function_of_one_name(self):
        assert self._check("class TestA: pass\n\ndef TestA(): pass\n") == ["TestA x2"]

    def test_an_async_method_shadowing_a_sync_one(self):
        assert self._check("class T:\n    def test_x(self): pass\n    async def test_x(self): pass\n") == ["T.test_x x2"]

    def test_the_scan_covers_unit_and_integration_and_the_legacy_top_level(self):
        import subprocess
        out = subprocess.run(["git", "ls-files", "tests/*test_*.py"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.split()
        dirs = {os.path.dirname(p) for p in out}
        assert {"tests", "tests/unit", "tests/integration"} <= dirs, dirs


# ── DBT-67 (#325): no store-repair script imports another script ─────────────────────────────────

def _imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


class TestDbt67:
    SCRIPTS = os.path.join(ROOT, "scripts")

    def _names(self):
        return {f[:-3] for f in os.listdir(self.SCRIPTS) if f.endswith(".py")}

    def test_no_script_imports_a_store_repair_script(self):
        """The toolkit's members are not imported by any other script either: a private helper
        imported from a repair script is the coupling DBT-67 removes."""
        toolkit = {"repair_boilerplate_bodies", "rechunk_stale_chunks", "settle_out_of_scope_links",
                   "drop_oversized_queued_chunks", "backfill_orphan_chunks", "recount_entity_mentions",
                   "repair_store_consistency", "requeue_cascaded_articles", "repair_faiss_posted_at"}
        offenders = {}
        for f in sorted(os.listdir(self.SCRIPTS)):
            if f.endswith(".py"):
                hit = {m.split(".")[-1] for m in _imports(os.path.join(self.SCRIPTS, f))} & toolkit
                if hit:
                    offenders[f] = sorted(hit)
        assert offenders == {}

    def test_store_repair_module_defines_every_step(self):
        from newscrawler.tools import store_repair as sr
        for step in ("crawl_running", "parse_until", "too_close", "faiss_dirs", "NoEmbeddings", "vector_ids_for",
                     "delete_vectors", "require_free_disk", "backup", "rechunk_articles", "rechunk",
                     "recount_entity_counts", "BACKUP_DIR", "MIN_FREE_GB_FOR_BACKUP"):
            assert hasattr(sr, step), step


# ── SYS-91 (#257): the repair script's selection ─────────────────────────────────────────────────

class TestSys91Selection:
    @pytest.fixture
    def mod(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import repair_faiss_posted_at
        return repair_faiss_posted_at

    def test_an_int_metadata_value_equal_to_the_sitemap_is_not_a_mismatch(self, mod):
        assert mod.select_targets([("d1", {"sitemap_id": 7, "posted_at": 20260918, "source": "CNBC"})],
                                  {7: 20260918}) == []

    def test_a_string_sitemap_id_is_matched(self, mod):
        out = mod.select_targets([("d1", {"sitemap_id": "7", "posted_at": "19700823", "source": "CNBC"})],
                                 {7: 20260918})
        assert out == [("d1", 7, "19700823", "20260918", "19xx", "CNBC")]

    def test_a_document_without_a_sitemap_row_is_left_alone(self, mod):
        assert mod.select_targets([("d1", {"sitemap_id": 8, "posted_at": "19700823"})], {7: 20260918}) == []

    def test_a_document_without_a_sitemap_id_is_left_alone(self, mod):
        assert mod.select_targets([("d1", {"posted_at": "19700823"})], {7: 20260918}) == []

    def test_only_19xx_unless_widened(self, mod):
        ms = mod.select_targets([("a", {"sitemap_id": 1, "posted_at": "19700823"}),
                                 ("b", {"sitemap_id": 2, "posted_at": ""}),
                                 ("c", {"sitemap_id": 3, "posted_at": "20260917"})],
                                {1: 20260918, 2: 20260917, 3: 20260918})
        assert [t[0] for t in mod.to_write(ms)] == ["a"]
        assert [t[0] for t in mod.to_write(ms, only_1970=False)] == ["a", "b", "c"]

    def test_a_19_prefixed_value_that_is_not_a_1970_date_is_still_19xx(self, mod):
        assert mod.kind("19991231") == "19xx" and mod.kind("") == "empty" and mod.kind("20260101") == "other"
