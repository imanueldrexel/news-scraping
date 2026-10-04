"""SYS-68 (#216): a digest says how many of its summaries are real.

2026-09-28's digest was 96 clusters of headline fallbacks and nothing said so.
Offline: a fake summarizer, a fake datasource, a stub clusterer."""
import json
import logging
from datetime import date
from unittest.mock import MagicMock

import pytest

import newscrawler.core.newsletter_generator as ng
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError


class FakeSummarizer:
    name = "fake-model"

    def __init__(self, script):
        """script: one item per call -- a string (the answer) or an exception."""
        self.script = list(script)
        self.calls = 0

    def summarize(self, prompt):
        self.calls += 1
        item = self.script.pop(0) if self.script else "- ok"
        if isinstance(item, Exception):
            raise item
        return item


def _art(i, topic="markets", cluster=0):
    return {"sitemap_id": i, "headline": f"h{i}", "source": "KOMPAS", "category": "news",
            "link": f"http://x/{i}", "posted_at": 20260929, "topic": topic,
            "l1_text": f"text {i}", "_cluster": cluster}


def _day(n_clusters):
    """n clusters of two articles each, spread over topics so the per-topic cap never bites."""
    topics = ng.SECTION_ORDER
    arts = []
    for c in range(n_clusters):
        topic = topics[c % len(topics)]
        arts += [_art(10 * c + 1, topic, c), _art(10 * c + 2, topic, c)]
    return arts


def _gen(monkeypatch, summarizer, ds=None):
    ds = ds or MagicMock()
    ds.save_digest.return_value = 1
    gen = ng.NewsletterGenerator(ds, summarizer=summarizer,
                                 embed_documents=lambda t: [[0.0, 1.0]] * len(t))
    monkeypatch.setattr(ng, "NEWSLETTER_MAX_CLUSTERS_PER_TOPIC", 100)
    monkeypatch.setattr(ng, "NEWSLETTER_MIN_CLUSTER_SIZE", 2)
    monkeypatch.setattr(gen, "_cluster", lambda vectors: [int(v[0]) for v in vectors])
    monkeypatch.setattr(gen, "_merge_across_sections", lambda entries, vectors: entries)  # stub vectors are labels, not geometry: SYS-65's merge has its own tests (test_newsletter_cross_section.py)
    return gen, ds


def _run(gen, ds, monkeypatch, tmp_path, arts):
    monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path))
    ds.get_articles_for_date.return_value = arts
    # the stub vectors carry each article's cluster label
    monkeypatch.setattr(gen, "_encode", lambda texts: [[a["_cluster"]] for a in arts])
    return gen.generate(date(2026, 9, 29))


class TestSummaryAccounting:
    def test_every_cluster_summarized(self, monkeypatch, tmp_path, caplog):
        s = FakeSummarizer([])
        gen, ds = _gen(monkeypatch, s)
        with caplog.at_level(logging.ERROR, logger=ng.logger.name):
            path = _run(gen, ds, monkeypatch, tmp_path, _day(5))
        assert s.calls == 5
        assert "Ringkasan AI: 5/5 (fake-model)" in open(path, encoding="utf-8").read()
        assert path.note is None
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
        stats = ds.save_digest.call_args.kwargs["categories"][ng.SUMMARIES_KEY]
        assert stats == {"total": 5, "summarized": 5, "provider": "fake-model", "stopped": None,
                         "groups_ok": 0, "groups_failed": 0}

    def test_quota_on_the_first_call_stops_the_calls_and_says_so(self, monkeypatch, tmp_path, caplog):
        """SYS-68's Done-when: exactly one API call, footer 0/N, one ERROR, a note."""
        s = FakeSummarizer([QuotaExhausted("429", "PerDay-FreeTier")])
        gen, ds = _gen(monkeypatch, s)
        with caplog.at_level(logging.ERROR, logger=ng.logger.name):
            path = _run(gen, ds, monkeypatch, tmp_path, _day(6))
        text = open(path, encoding="utf-8").read()
        assert s.calls == 1
        assert "Ringkasan AI: 0/6 (fake-model) — kuota harian habis; sisanya hanya daftar judul" in text
        assert "- h1" in text                                   # the headline fallback is still shown
        assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1
        assert path.note and "0/6" in path.note
        stats = ds.save_digest.call_args.kwargs["categories"][ng.SUMMARIES_KEY]
        assert (stats["summarized"], stats["total"], stats["stopped"]) == (0, 6, "quota")

    def test_quota_mid_run_keeps_the_summaries_already_written(self, monkeypatch, tmp_path):
        s = FakeSummarizer(["- one", "- two", QuotaExhausted("429")])
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(10))
        text = open(path, encoding="utf-8").read()
        assert s.calls == 3
        assert "- one" in text and "- two" in text
        assert "Ringkasan AI: 2/10" in text
        assert path.note                                         # 20% < the 80% floor

    def test_isolated_failures_do_not_stop_the_calls(self, monkeypatch, tmp_path):
        s = FakeSummarizer([SummarizerError("timeout"), "- b", SummarizerError("timeout"), "- d", "- e"])
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(5))
        assert s.calls == 5
        assert "Ringkasan AI: 3/5 (fake-model) — sebagian ringkasan gagal" in open(path, encoding="utf-8").read()
        assert ds.save_digest.call_args.kwargs["categories"][ng.SUMMARIES_KEY]["stopped"] is None

    def test_consecutive_failures_stop_the_calls(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS", 3)
        s = FakeSummarizer([SummarizerError("down")] * 20)
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(8))
        assert s.calls == 3
        assert "layanan gagal berulang" in open(path, encoding="utf-8").read()
        assert path.note

    def test_a_success_resets_the_consecutive_count(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS", 3)
        script = [SummarizerError("x"), SummarizerError("x"), "- ok",
                  SummarizerError("x"), SummarizerError("x"), "- ok"]
        s = FakeSummarizer(script)
        gen, ds = _gen(monkeypatch, s)
        _run(gen, ds, monkeypatch, tmp_path, _day(6))
        assert s.calls == 6

    def test_no_summarizer_says_so_and_still_writes_the_digest(self, monkeypatch, tmp_path):
        gen, ds = _gen(monkeypatch, None)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(4))
        text = open(path, encoding="utf-8").read()
        assert "Ringkasan AI: 0/4 — tidak ada penyedia LLM yang dikonfigurasi" in text
        assert "- h1" in text
        assert path.note

    def test_exactly_at_the_floor_is_not_degraded(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "NEWSLETTER_MIN_SUMMARY_SHARE", 0.8)
        s = FakeSummarizer(["- a"] * 4 + [QuotaExhausted("429")])
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(5))
        assert path.note is None                                  # 4/5 = 0.8

    def test_a_digest_without_clusters_is_not_degraded(self, monkeypatch, tmp_path):
        s = FakeSummarizer([])
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, [_art(1, cluster=-1)])
        assert s.calls == 0 and path.note is None

    def test_the_stats_row_is_valid_json_beside_the_topics(self, monkeypatch, tmp_path):
        gen, ds = _gen(monkeypatch, FakeSummarizer([]))
        _run(gen, ds, monkeypatch, tmp_path, _day(3))
        categories = ds.save_digest.call_args.kwargs["categories"]
        json.dumps(categories)
        topics = [k for k in categories if not k.startswith("_")]
        assert set(topics) <= set(ng.SECTION_TITLES)

    def test_the_stats_footer_counts(self):
        assert ng.SummaryStats(total=0).share == 1.0
        assert ng.SummaryStats(total=4, summarized=1).fallback == 3
