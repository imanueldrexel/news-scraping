"""
OPS-05 (4): get_stats() used to run all seven numbers as correlated sub-selects in
one statement, wrapped in a single try/except returning {} -- one missing/broken
table (e.g. newsletter_digests, undetected for ~4 months) blanked every other
number too. Each metric must now be queried independently.
"""
from unittest.mock import MagicMock

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (
    SQLAlchemyNewsletterDataSource,
)


def _ds_with_session_side_effect(scalar_side_effect):
    client = MagicMock()
    session = MagicMock()
    session.execute.return_value.scalar.side_effect = scalar_side_effect
    client.get_session.return_value.__enter__.return_value = session
    client.get_session.return_value.__exit__.return_value = False
    return SQLAlchemyNewsletterDataSource(client)


class TestGetStatsIsolation:
    def test_all_queries_succeeding_returns_every_metric(self):
        ds = _ds_with_session_side_effect([10, 20, 3, "20260101", "20260916", 0, "2026-09-16 10:00:00"])
        stats = ds.get_stats()
        assert stats == {
            "total_articles": 10, "total_chunks": 20, "total_entities": 3,
            "min_date": "20260101", "max_date": "20260916",
            "digests_generated": 0, "last_crawl": "2026-09-16 10:00:00",
        }

    def test_one_missing_table_only_blanks_its_own_metric(self):
        """The actual production bug: newsletter_digests missing must not blank
        total_articles/total_chunks/total_entities/min_date/max_date/last_crawl.
        A plain list side_effect (not a generator) is required here: Mock's list
        form raises the exception for that one call and continues to the next list
        item on the following call, matching what a genuinely independent per-metric
        query does -- a generator that raises is exhausted afterward and would
        (wrongly, for this test) make every later metric fail too."""
        ds = _ds_with_session_side_effect([
            10, 20, 3, "20260101", "20260916",
            Exception('relation "newsletter_digests" does not exist'),
            "2026-09-16 10:00:00",
        ])
        stats = ds.get_stats()

        assert stats["total_articles"] == 10
        assert stats["total_chunks"] == 20
        assert stats["total_entities"] == 3
        assert stats["min_date"] == "20260101"
        assert stats["max_date"] == "20260916"
        assert stats["digests_generated"] is None, "only the broken metric should be None"
        assert stats["last_crawl"] == "2026-09-16 10:00:00", "a later metric must still succeed"

    def test_all_seven_keys_always_present_even_when_everything_fails(self):
        ds = _ds_with_session_side_effect(Exception("db down"))
        stats = ds.get_stats()
        assert set(stats.keys()) == {
            "total_articles", "total_chunks", "total_entities",
            "min_date", "max_date", "digests_generated", "last_crawl",
        }
        assert all(v is None for v in stats.values())

    def test_none_date_values_are_not_stringified(self):
        ds = _ds_with_session_side_effect([0, 0, 0, None, None, 0, None])
        stats = ds.get_stats()
        assert stats["min_date"] is None
        assert stats["max_date"] is None
        assert stats["last_crawl"] is None
