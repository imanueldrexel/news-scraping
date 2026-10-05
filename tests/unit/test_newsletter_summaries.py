"""SYS-68 (#216): a digest says how many of its summaries are real.

2026-09-28's digest was 96 clusters of headline fallbacks and nothing said so.
Since SYS-84 the counts are the operator's (the row, the log, the note) and the
reader sees a notice at the top instead of telemetry in the footer; since SYS-82
a refused answer is counted by reason and is not an outage.
Offline: a fake summarizer, a fake datasource, a stub clusterer."""
import json
import logging
from datetime import date
from unittest.mock import MagicMock

import newscrawler.core.newsletter_generator as ng
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError
from tests.unit.newsletter_fakes import VALID, FakeNewsroom, story_answer


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


def _stats(ds):
    return ds.save_digest.call_args.kwargs["categories"][ng.SUMMARIES_KEY]


class TestSummaryAccounting:
    def test_every_cluster_summarized(self, monkeypatch, tmp_path, caplog):
        s = FakeNewsroom()
        gen, ds = _gen(monkeypatch, s)
        with caplog.at_level(logging.ERROR, logger=ng.logger.name):
            path = _run(gen, ds, monkeypatch, tmp_path, _day(5))
        assert len(s.prompts["story"]) == 5
        text = open(path, encoding="utf-8").read()
        assert "Ringkasan AI" not in text and "fake-model" not in text      # SYS-84: telemetry is not the reader's
        assert "hanya ditampilkan judulnya" not in text
        assert path.note is None
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert _stats(ds) == {"total": 5, "summarized": 5, "provider": "fake-model", "stopped": None,
                              "groups_ok": 0, "groups_failed": 0, "first_try": 5,
                              "rejections": {"json": 0, "length": 0, "number": 0}}

    def test_quota_on_the_first_call_stops_the_calls_and_says_so(self, monkeypatch, tmp_path, caplog):
        """SYS-68's Done-when: exactly one API call, 0/N reported, an ERROR, a note."""
        s = FakeNewsroom(story=[QuotaExhausted("429", "PerDay-FreeTier")])
        gen, ds = _gen(monkeypatch, s)
        with caplog.at_level(logging.ERROR, logger=ng.logger.name):
            path = _run(gen, ds, monkeypatch, tmp_path, _day(6))
        text = open(path, encoding="utf-8").read()
        assert s.calls == 1                                      # no editor call either
        assert "- h1" in text                                    # the headline fallback is still shown
        assert "> Sebagian ringkasan tidak tersedia hari ini. 6 berita hanya ditampilkan judulnya." in text
        assert text.index("hanya ditampilkan judulnya") < text.index("## ")   # at the top, not the foot
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any(e.startswith("digest degraded: Ringkasan AI: 0/6 (fake-model) — kuota harian habis") for e in errors)
        assert any("5-minute edition not built" in e for e in errors)
        assert path.note and "0/6" in path.note and "edition not built" in path.note
        stats = _stats(ds)
        assert (stats["summarized"], stats["total"], stats["stopped"]) == (0, 6, "quota")

    def test_quota_mid_run_keeps_the_summaries_already_written(self, monkeypatch, tmp_path):
        s = FakeNewsroom(story=[VALID, VALID, QuotaExhausted("429")])
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(10))
        text = open(path, encoding="utf-8").read()
        assert len(s.prompts["story"]) == 3 and not s.prompts["editor"]
        assert _stats(ds)["summarized"] == 2
        assert "8 berita hanya ditampilkan judulnya" in text
        assert path.note and "2/10" in path.note                  # 20% < the 80% floor

    def test_isolated_failures_do_not_stop_the_calls(self, monkeypatch, tmp_path):
        s = FakeNewsroom(story=[SummarizerError("timeout"), VALID, SummarizerError("timeout"), VALID, VALID])
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(5))
        assert len(s.prompts["story"]) == 5
        assert "Ringkasan AI: 3/5 (fake-model) — sebagian ringkasan gagal" in path.note
        assert _stats(ds)["stopped"] is None

    def test_consecutive_failures_stop_the_calls(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS", 3)
        s = FakeNewsroom(story=[SummarizerError("down")] * 20)
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(8))
        assert s.calls == 3
        assert "layanan gagal berulang" in path.note

    def test_a_success_resets_the_consecutive_count(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS", 3)
        script = [SummarizerError("x"), SummarizerError("x"), VALID,
                  SummarizerError("x"), SummarizerError("x"), VALID]
        s = FakeNewsroom(story=script)
        gen, ds = _gen(monkeypatch, s)
        _run(gen, ds, monkeypatch, tmp_path, _day(6))
        assert len(s.prompts["story"]) == 6

    def test_no_summarizer_says_so_and_still_writes_the_digest(self, monkeypatch, tmp_path):
        gen, ds = _gen(monkeypatch, None)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(4))
        text = open(path, encoding="utf-8").read()
        assert "Ringkasan AI: 0/4 — tidak ada penyedia LLM yang dikonfigurasi" in path.note
        assert "- h1" in text and "4 berita hanya ditampilkan judulnya" in text

    def test_exactly_at_the_floor_is_not_degraded(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "NEWSLETTER_MIN_SUMMARY_SHARE", 0.8)
        s = FakeNewsroom(story=[VALID] * 4 + [QuotaExhausted("429")])
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(5))
        assert path.note is None                                  # 4/5 = 0.8, and the edition was built

    def test_a_digest_without_clusters_is_not_degraded(self, monkeypatch, tmp_path):
        s = FakeNewsroom()
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, [_art(1, cluster=-1)])
        assert s.calls == 0 and "digest degraded" not in (path.note or "")
        assert path.edition is None                               # nothing to edit, and the note says so
        assert "edition not built" in path.note

    def test_the_stats_row_is_valid_json_beside_the_topics(self, monkeypatch, tmp_path):
        gen, ds = _gen(monkeypatch, FakeNewsroom())
        _run(gen, ds, monkeypatch, tmp_path, _day(3))
        categories = ds.save_digest.call_args.kwargs["categories"]
        json.dumps(categories)
        topics = [k for k in categories if not k.startswith("_")]
        assert set(topics) <= set(ng.SECTION_TITLES)

    def test_the_stats_counts(self):
        assert ng.SummaryStats(total=0).share == 1.0
        assert ng.SummaryStats(total=4, summarized=1).fallback == 3


class TestRefusedAnswers:
    """SYS-82 (#239): a refused answer is asked again once; two refusals fall
    back to the headline list. Refusals are counted by reason and are not an outage."""

    def test_a_repaired_answer_counts_its_refusal_but_not_as_first_try(self, monkeypatch, tmp_path):
        s = FakeNewsroom(story=["bukan json", VALID, VALID])
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(2))
        stats = _stats(ds)
        assert (stats["summarized"], stats["first_try"]) == (2, 1)
        assert stats["rejections"] == {"json": 1, "length": 0, "number": 0}
        assert "ditolak json 1" in ng.SummaryStats(**stats).describe()
        assert "Jawaban sebelumnya ditolak" in s.prompts["story"][1]
        assert path.note is None

    def test_two_refusals_fall_back_to_the_headlines_and_are_counted(self, monkeypatch, tmp_path):
        too_long = lambda p: story_answer(p, judul=" ".join(["kata"] * 11))
        invented = lambda p: story_answer(p, inti="Laba naik 99 persen.")
        s = FakeNewsroom(story=[too_long, invented])
        gen, ds = _gen(monkeypatch, s)
        path = _run(gen, ds, monkeypatch, tmp_path, _day(1))
        stats = _stats(ds)
        assert (stats["summarized"], stats["total"]) == (0, 1)
        assert stats["rejections"] == {"json": 0, "length": 1, "number": 1}
        text = open(path, encoding="utf-8").read()
        assert "### h1" in text and "- h1" in text and "99 persen" not in text

    def test_refusals_are_not_an_outage(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS", 1)
        s = FakeNewsroom(story=["x", "x", "x", "x", VALID])
        gen, ds = _gen(monkeypatch, s)
        _run(gen, ds, monkeypatch, tmp_path, _day(3))
        assert len(s.prompts["story"]) == 5                      # 2 + 2 refusals, then the third story
        assert _stats(ds)["stopped"] is None
