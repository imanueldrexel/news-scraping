"""SYS-45 (#140): the probe-verdict cleanup selects exactly the rows it says it
does -- scope by allow-set + fetch stamp (or all), soft only, entity-referenced
rows kept -- and deletes through cleanup_offtopic_articles.delete_articles
(the one deletion path). Offline."""
from datetime import datetime, timezone
from types import SimpleNamespace

from scripts.cleanup_soft_by_probe import ALLOW_SINCE, in_scope, select


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
