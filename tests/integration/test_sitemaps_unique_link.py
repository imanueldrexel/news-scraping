"""
SYS-29 (#84): one `sitemaps` row per link, enforced by the database and honoured
by save_sitemaps against a real PostgreSQL.

The unit tests in tests/unit/test_sitemap_link_dedup.py prove the Python-side key
is the link alone; this module proves (a) scripts/migrate_sitemaps_unique_link.sql
is applied to the test DB (sitemaps_link_uq exists), (b) a second row for a stored
link is refused at the SQL level regardless of posted_at, and (c) the real
save_sitemaps + real lookup round-trip the SYS-11 shape (same URL, posted_at moved
+1 day) into ONE row with the same sitemap_id.
"""
import uuid
from datetime import datetime

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")

DB_CONFIG = {
    'host': 'localhost',
    'port': 5431,
    'user': 'postgres',
    'password': 'postgres',
    'dbname': 'newsaggregator_test',  # NEVER the production DB
}


@pytest.fixture(scope="module")
def raw_conn():
    try:
        c = psycopg2.connect(**DB_CONFIG)
        c.autocommit = False
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    c.close()


@pytest.fixture(autouse=True)
def rollback_after_each(raw_conn):
    yield
    raw_conn.rollback()


@pytest.fixture(scope="module")
def datasource():
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
        SQLAlchemySitemapDataSource,
    )
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    return SQLAlchemySitemapDataSource(SQLAlchemyClient())


def _model(link, posted_at, source="CNBC"):
    from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
    return NewsSitemapModel(headline="h", link=link, sources=source, category="market",
                            posted_at=posted_at, keywords=None)


def _unique_link():
    return f"https://sys29.test/{uuid.uuid4().hex}?page=all"


class TestUniqueIndexExists:
    def test_sitemaps_link_uq_is_a_unique_index_on_link(self, raw_conn):
        cur = raw_conn.cursor()
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'sitemaps' AND indexname = 'sitemaps_link_uq'")
        row = cur.fetchone()
        assert row is not None, (
            "sitemaps_link_uq missing -- run `python scripts/migrate.py` against newsaggregator_test "
            "(scripts/migrate_sitemaps_unique_link.sql)"
        )
        assert "UNIQUE" in row[0] and "(link)" in row[0], row[0]

    def test_raw_second_row_for_a_stored_link_is_refused_even_with_another_posted_at(self, raw_conn):
        link = _unique_link()
        cur = raw_conn.cursor()
        cur.execute("INSERT INTO sitemaps (headline, link, sources, posted_at) VALUES ('a', %s, 'CNBC', 20260506)",
                    (link,))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO sitemaps (headline, link, sources, posted_at) VALUES ('a', %s, 'CNBC', 20260507)",
                        (link,))

    def test_link_is_not_nullable_so_every_row_is_covered_by_the_index(self, raw_conn):
        """A unique index would let NULLs through (Postgres treats them as
        distinct); the column being NOT NULL is what makes "one row per link"
        hold for every row, so pin that too."""
        cur = raw_conn.cursor()
        cur.execute("SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'sitemaps' AND column_name = 'link'")
        assert cur.fetchone()[0] == "NO"


class TestSaveSitemapsRoundTrip:
    def test_sys11_shape_produces_one_row_and_the_same_id(self, datasource, raw_conn):
        """Stored under the old derivation (D-1), re-listed under the new one (D)."""
        link = _unique_link()

        first = datasource.save_sitemaps([_model(link, datetime(2026, 5, 6))])
        second = datasource.save_sitemaps([_model(link, datetime(2026, 5, 7))])

        assert first.new_count == 1
        assert second.new_count == 0
        assert first[0].sitemap_id == second[0].sitemap_id

        cur = raw_conn.cursor()
        cur.execute("SELECT sitemap_id, posted_at FROM sitemaps WHERE link = %s", (link,))
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0] == (first[0].sitemap_id, 20260506), "first-seen posted_at must be kept, not refreshed"

    def test_stored_link_dated_before_every_entry_in_the_batch_is_still_recognised(self, datasource, raw_conn):
        """The case a date-window pre-fetch would miss: the stored row is older
        than the whole batch. Must still come back with its id, not error."""
        old_link, new_link = _unique_link(), _unique_link()
        cur = raw_conn.cursor()
        cur.execute("INSERT INTO sitemaps (headline, link, sources, posted_at) VALUES ('a', %s, 'CNBC', 20260101) "
                    "RETURNING sitemap_id", (old_link,))
        stored_id = cur.fetchone()[0]
        raw_conn.commit()

        result = datasource.save_sitemaps([_model(old_link, datetime(2026, 9, 18)),
                                           _model(new_link, datetime(2026, 9, 18))])

        by_link = {s.link: s.sitemap_id for s in result}
        assert by_link[old_link] == stored_id
        assert by_link[new_link] not in (None, stored_id)
        assert result.new_count == 1

    def test_find_existing_by_link_matches_what_is_stored(self, datasource, raw_conn):
        link, missing = _unique_link(), _unique_link()
        cur = raw_conn.cursor()
        cur.execute("INSERT INTO sitemaps (headline, link, sources, posted_at) VALUES ('a', %s, 'CNBC', 20260101) "
                    "RETURNING sitemap_id", (link,))
        stored_id = cur.fetchone()[0]
        raw_conn.commit()

        assert datasource.find_existing_by_link([link, missing]) == {link: stored_id}
