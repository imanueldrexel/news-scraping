"""
SYS-07 against a live PostgreSQL: an older, never-seen sitemap entry must be inserted
even when the source already holds newer rows (the old date gate dropped it), and
re-saving the same batch must not create duplicates.

Cleans up its own rows (source 'SYS07TEST'). Requires newsaggregator_test.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

WIB = timezone(timedelta(hours=7))
SOURCE = "SYS07TEST"


@pytest.fixture
def ds_and_client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import NewsDataSource
    client = SQLAlchemyClient()
    try:
        with client.get_session() as s:
            assert s.execute(text("SELECT current_database()")).scalar() == "newsaggregator_test"
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    ds = NewsDataSource(client)
    yield ds, client
    with client.get_session() as s:
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _model(link, posted_at):
    from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
    return NewsSitemapModel(headline=link, link=link, sources=SOURCE, category="news",
                            posted_at=posted_at, keywords=None)


def _count(client, link=None):
    with client.get_session() as s:
        if link:
            return s.execute(text("SELECT count(*) FROM sitemaps WHERE sources=:s AND link=:l"),
                             {"s": SOURCE, "l": link}).scalar()
        return s.execute(text("SELECT count(*) FROM sitemaps WHERE sources=:s"), {"s": SOURCE}).scalar()


class TestOlderEntriesAreBackfilled:
    def test_BF01_older_never_seen_entry_inserted_after_newer_exists(self, ds_and_client):
        ds, client = ds_and_client
        run = uuid.uuid4().hex[:8]
        newer = _model(f"http://sys07.test/{run}/newer", datetime(2026, 9, 16, 0, 0, tzinfo=WIB))
        older = _model(f"http://sys07.test/{run}/older", datetime(2026, 9, 10, 0, 0, tzinfo=WIB))

        ds.save_sitemap([newer])                       # run 1: source max posted_at is now 20260916
        ds.save_sitemap([older])                       # run 2: an entry from a missed earlier day
        assert _count(client, older.link) == 1, "older never-seen entry was dropped"

    def test_BF02_same_batch_twice_creates_no_duplicates(self, ds_and_client):
        ds, client = ds_and_client
        run = uuid.uuid4().hex[:8]
        batch = [_model(f"http://sys07.test/{run}/{i}", datetime(2026, 9, 10 + i, 0, 0, tzinfo=WIB))
                 for i in range(5)]
        ds.save_sitemap(list(batch))
        ds.save_sitemap(list(batch))
        assert _count(client) == 5

    def test_BF03_date_only_consecutive_runs_keep_accumulating(self, ds_and_client):
        """EMITENNEWS scenario: midnight-WIB dates, a future-dated stub, then new days."""
        ds, client = ds_and_client
        run = uuid.uuid4().hex[:8]
        day = lambda d: datetime(2026, 9, d, 0, 0, tzinfo=WIB)
        ds.save_sitemap([_model(f"http://sys07.test/{run}/stub", day(20)),   # future-dated stub
                         _model(f"http://sys07.test/{run}/a", day(16))])
        ds.save_sitemap([_model(f"http://sys07.test/{run}/stub", day(20)),   # re-listed
                         _model(f"http://sys07.test/{run}/a", day(16)),
                         _model(f"http://sys07.test/{run}/b", day(17))])     # new article next day
        assert _count(client) == 3
