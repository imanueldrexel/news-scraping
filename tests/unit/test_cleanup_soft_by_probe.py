"""SYS-45 (#140): the probe-verdict cleanup selects exactly the rows it says it
does -- scope by allow-set + fetch stamp (or all), soft only, entity-referenced
rows kept -- and deletes through cleanup_offtopic_articles.delete_articles
(the one deletion path). DBT-34 (#150): and it only acts on cached verdicts the
committed probe actually produced. Offline."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from scripts.cleanup_soft_by_probe import (
    ALLOW_SINCE, IDENTITY_FIELDS, identity_mismatch, in_scope, select, verdicts_from_backup,
)


def _row(aid, category="bisnis", stamp=datetime(2026, 9, 21, tzinfo=timezone.utc), referenced=False):
    return SimpleNamespace(articles_id=aid, sitemap_id=100 + aid, sources="X", category=category, headline=f"h{aid}",
                           last_crawl_attempt=stamp, body_head="b", referenced=referenced)


class TestScope:
    def test_allow_since_is_allow_set_category_and_fetched_after_the_sys35_requeue(self):
        assert in_scope(_row(1, "bisnis"), "allow-since")
        assert in_scope(_row(2, "nasional", datetime(2026, 9, 20, 15, 20)), "allow-since")          # naive == UTC
        assert not in_scope(_row(3, "bisnis", datetime(2026, 9, 20, 15, 19, tzinfo=timezone.utc)), "allow-since")
        assert not in_scope(_row(4, "news"), "allow-since")                                          # mixed bucket
        assert not in_scope(_row(5, "hiburan"), "allow-since")
        assert not in_scope(_row(6, "bisnis", None), "allow-since")
        assert ALLOW_SINCE == datetime(2026, 9, 20, 15, 20, tzinfo=timezone.utc)

    def test_all_is_everything(self):
        assert in_scope(_row(1, "news", None), "all") and in_scope(_row(2, "hiburan"), "all")


class TestSelect:
    def test_soft_unreferenced_in_scope_rows_are_the_deletable_set(self):
        rows = [_row(1), _row(2), _row(3, referenced=True), _row(4, "news"), _row(5)]
        verdicts = {1: False, 2: True, 3: False, 4: False}          # 5 has no verdict
        scoped, soft, unknown, referenced, deletable = select(rows, verdicts, "allow-since")
        assert [r.articles_id for r in scoped] == [1, 2, 3, 5]
        assert [r.articles_id for r in soft] == [1, 3]
        assert [r.articles_id for r in unknown] == [5]
        assert [r.articles_id for r in referenced] == [3]
        assert [r.articles_id for r in deletable] == [1]
        _, _, _, _, deletable_all = select(rows, verdicts, "all")
        assert [r.articles_id for r in deletable_all] == [1, 4]


_IDENTITY = {
    "embedding_model": "intfloat/multilingual-e5-large",
    "soft_threshold": 0.39,
    "gold_sha256": "a" * 64,
    "trained_at": "2026-09-22T02:00:00+00:00",
    "artifact_sha256": "b" * 64,
}


class TestProbeIdentityGuard:
    """DBT-34 (#150): this script deletes production articles, their chunks and
    their FAISS vectors on verdicts read from a file. Before this guard nothing
    tied those verdicts to a probe, so a retrain or a SOFT_THRESHOLD move left
    it deleting on the old probe's opinion and saying nothing."""

    def test_same_artifact_proceeds(self):
        assert identity_mismatch(dict(_IDENTITY), dict(_IDENTITY)) == []

    def test_trained_at_alone_is_not_a_mismatch(self):
        # A rebuild of identical weights is not a different decision.
        stale = dict(_IDENTITY, trained_at="2026-01-01T00:00:00+00:00")
        assert identity_mismatch(stale, dict(_IDENTITY)) == []

    def test_a_moved_threshold_is_refused(self):
        moved = dict(_IDENTITY, soft_threshold=0.44)
        problems = identity_mismatch(moved, dict(_IDENTITY))
        assert len(problems) == 1 and "soft_threshold" in problems[0]

    def test_a_retrain_or_swapped_artifact_is_refused(self):
        for field, value in (("embedding_model", "intfloat/multilingual-e5-base"),
                             ("gold_sha256", "c" * 64),
                             ("artifact_sha256", "d" * 64)):
            problems = identity_mismatch(dict(_IDENTITY, **{field: value}), dict(_IDENTITY))
            assert len(problems) == 1 and field in problems[0], (field, problems)

    def test_a_file_without_an_identity_is_refused_not_trusted(self):
        # Every pre-DBT-34 backup is this shape; it must fail closed.
        problems = identity_mismatch(None, dict(_IDENTITY))
        assert len(problems) == 1 and "no probe identity" in problems[0]

    def test_threshold_compares_numerically_not_by_repr(self):
        assert identity_mismatch(dict(_IDENTITY, soft_threshold=0.39), dict(_IDENTITY, soft_threshold=0.3900000001)) == []

    def test_every_identity_field_is_actually_compared(self):
        """A field added to the block but not to the comparison is a guard that
        does not guard -- the shape this whole batch was filed on."""
        for field in IDENTITY_FIELDS:
            other = "zzz" if not isinstance(_IDENTITY[field], float) else _IDENTITY[field] + 0.1
            assert identity_mismatch(dict(_IDENTITY, **{field: other}), dict(_IDENTITY)), field

    def test_reads_both_the_new_and_the_legacy_verdict_file(self, tmp_path):
        new = tmp_path / "sys37_topic_backfill_applied_20260923T000000Z.json"
        new.write_text(json.dumps({"meta": _IDENTITY, "rows": [
            {"articles_id": 1, "is_news": False, "topic": "soft", "topic_confidence": 0.1,
             "prev_topic": "markets", "prev_topic_confidence": 0.7}]}), encoding="utf-8")
        verdicts, meta = verdicts_from_backup(str(new))
        assert verdicts == {1: False} and meta == _IDENTITY
        # the row keeps what it overwrote, so "backup" is a true name
        assert json.loads(new.read_text(encoding="utf-8"))["rows"][0]["prev_topic"] == "markets"

        legacy = tmp_path / "sys37_topic_backfill_20260922T021044Z.json"
        legacy.write_text(json.dumps([{"articles_id": 2, "is_news": True}]), encoding="utf-8")
        verdicts, meta = verdicts_from_backup(str(legacy))
        assert verdicts == {2: True} and meta is None



class TestSys48Band:
    """SYS-48 (#144): the cosine-era scope and the P(soft) band cut."""

    def test_cosine_era_is_what_was_fetched_before_the_probe(self):
        from datetime import datetime, timezone
        assert in_scope(_row(1, "news", datetime(2026, 9, 22, 2, 9, tzinfo=timezone.utc)), "cosine-era")
        assert not in_scope(_row(2, "news", datetime(2026, 9, 22, 2, 10, tzinfo=timezone.utc)), "cosine-era")
        assert not in_scope(_row(3, "news", None), "cosine-era")

    def test_min_p_soft_keeps_only_the_band(self):
        from datetime import datetime, timezone
        early = datetime(2026, 9, 1, tzinfo=timezone.utc)
        rows = [_row(1, "news", early), _row(2, "news", early), _row(3, "news", early)]
        verdicts = {1: False, 2: False, 3: True}
        p = {1: 0.95, 2: 0.85, 3: 0.1}
        _, soft, _, _, deletable = select(rows, verdicts, "cosine-era", p, 0.9)
        assert [r.articles_id for r in deletable] == [1]
        _, _, _, _, all_soft = select(rows, verdicts, "cosine-era")
        assert [r.articles_id for r in all_soft] == [1, 2]

    def test_min_p_soft_without_recompute_is_refused(self):
        import pytest
        from scripts.cleanup_soft_by_probe import main
        with pytest.raises(SystemExit):
            main(["--scope", "cosine-era", "--min-p-soft", "0.9"])
