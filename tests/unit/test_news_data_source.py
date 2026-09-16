"""
SYS-07: NewsDataSource.save_sitemap must not pre-filter by date. Every scraped entry
goes to save_sitemaps(), whose (link, posted_at) dedup is the real check. The old gate
dropped never-seen entries older than the stored max posted_at (a missed run could
never be backfilled) and, for date-only sitemaps, everything after the first run.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import NewsDataSource

WIB = timezone(timedelta(hours=7))


def _ds():
    ds = NewsDataSource.__new__(NewsDataSource)  # skip __init__: no DB, no S3
    ds.sql_alchemy_sitemap = MagicMock()
    ds.sql_alchemy_sitemap.save_sitemaps.side_effect = lambda rows: rows
    return ds


def _row(link, posted_at, source="X", category="news"):
    return NewsSitemapModel(headline=link, link=link, sources=source, category=category,
                            posted_at=posted_at, keywords=None)


class TestSaveSitemapNoDateGate:
    def test_NG01_older_and_same_day_entries_are_passed_through(self):
        """The audit repro: 4 never-seen links, the old gate kept only 2."""
        ds = _ds()
        rows = [
            _row("newer",        datetime(2026, 9, 15, 10, tzinfo=WIB)),
            _row("older",        datetime(2026, 8, 30, 10, tzinfo=WIB)),
            _row("same-day-0h",  datetime(2026, 9, 1, 0, 0, tzinfo=WIB)),
            _row("same-day-9h",  datetime(2026, 9, 1, 9, 0, tzinfo=WIB)),
        ]
        out = ds.save_sitemap(rows)
        assert [r.link for r in out] == ["newer", "older", "same-day-0h", "same-day-9h"]
        ds.sql_alchemy_sitemap.save_sitemaps.assert_called_once()

    def test_NG02_date_only_timestamps_are_not_dropped(self):
        """EMITENNEWS-style midnight dates on consecutive runs."""
        ds = _ds()
        rows = [_row(f"day{d}", datetime(2026, 9, d, 0, 0, tzinfo=WIB)) for d in (14, 15, 16)]
        assert len(ds.save_sitemap(rows)) == 3

    def test_NG03_empty_batch_returns_empty_list_without_db_call(self):
        ds = _ds()
        assert ds.save_sitemap([]) == []
        ds.sql_alchemy_sitemap.save_sitemaps.assert_not_called()

    def test_NG04_no_dependency_on_last_time_crawling(self):
        """The datasource no longer needs last_time_crawling at all."""
        ds = _ds()
        del ds.sql_alchemy_sitemap.last_time_crawling  # attribute access would raise
        rows = [_row("a", datetime(2026, 9, 16, tzinfo=WIB))]
        assert len(ds.save_sitemap(rows)) == 1
