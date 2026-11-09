"""
SYS-09 against a live PostgreSQL: a sitemap whose fetch/extraction fails
SITEMAP_MAX_FETCH_FAILURES times in a row must stop being returned by
load_all_sitemaps, while one that has failed fewer times (or never) keeps
retrying on the normal cooldown -- and increment_fetch_failures must actually
persist the count, the error note, and last_crawl_attempt (so a failure also
respects the cooldown instead of being re-selected on the very next run).
"""
from datetime import timedelta, timezone

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES

WIB = timezone(timedelta(hours=7))
SOURCE = "SYS09TEST"


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


def _insert_sitemap(client, link, days_ago_attempted=30):
    with client.get_session() as s:
        row = s.execute(
            text(
                "INSERT INTO sitemaps (headline, link, sources, posted_at, last_crawl_attempt) "
                "VALUES (:h, :l, :s, 20260901, NOW() - make_interval(days => :days)) "
                "RETURNING sitemap_id"
            ),
            {"h": "t", "l": link, "s": SOURCE, "days": days_ago_attempted},
        ).fetchone()
        s.commit()
    return row.sitemap_id


class TestFetchFailuresExcludeAfterThreshold:
    def test_a_sitemap_at_the_threshold_is_excluded_one_below_still_retries(self, ds_and_client):
        ds, client = ds_and_client
        dead_id = _insert_sitemap(client, "http://sys09.test/dead")
        flaky_id = _insert_sitemap(client, "http://sys09.test/flaky")

        for _ in range(SITEMAP_MAX_FETCH_FAILURES):
            ds.increment_fetch_failures([dead_id], "404")
        for _ in range(SITEMAP_MAX_FETCH_FAILURES - 1):
            ds.increment_fetch_failures([flaky_id], "timeout")

        # increment_fetch_failures stamps last_crawl_attempt=NOW() on every call (so a
        # failure respects the cooldown too, see TestIncrementFetchFailuresPersistence)
        # -- push both back past the cooldown window so this test isolates the
        # fetch_failures count itself, not "the last failure was seconds ago".
        with client.get_session() as s:
            s.execute(text("UPDATE sitemaps SET last_crawl_attempt = NOW() - INTERVAL '30 days' "
                            "WHERE sitemap_id = ANY(:ids)"), {"ids": [dead_id, flaky_id]})
            s.commit()

        eligible_ids = {r.sitemap_id for r in ds.sql_alchemy_sitemap.load_all_sitemaps(website=SOURCE, n_limit=1000)}

        assert dead_id not in eligible_ids, f"{SITEMAP_MAX_FETCH_FAILURES} failures must exclude it"
        assert flaky_id in eligible_ids, "one fewer failure must still be eligible"

    def test_never_attempted_sitemap_defaults_to_zero_and_is_eligible(self, ds_and_client):
        ds, client = ds_and_client
        fresh_id = _insert_sitemap(client, "http://sys09.test/fresh")

        eligible_ids = {r.sitemap_id for r in ds.sql_alchemy_sitemap.load_all_sitemaps(website=SOURCE, n_limit=1000)}

        assert fresh_id in eligible_ids


class TestIncrementFetchFailuresPersistence:
    def test_increments_the_counter_and_stores_the_error_and_respects_cooldown(self, ds_and_client):
        ds, client = ds_and_client
        # Fresh row (no prior last_crawl_attempt) so it would otherwise be
        # immediately eligible again -- a failure must still stamp the cooldown.
        with client.get_session() as s:
            row = s.execute(
                text("INSERT INTO sitemaps (headline, link, sources, posted_at) "
                     "VALUES ('t', 'http://sys09.test/fresh2', :s, 20260901) RETURNING sitemap_id"),
                {"s": SOURCE},
            ).fetchone()
            s.commit()
        sitemap_id = row.sitemap_id

        ds.increment_fetch_failures([sitemap_id], "ConnectionError: timed out")
        ds.increment_fetch_failures([sitemap_id], "ConnectionError: timed out")

        with client.get_session() as s:
            row = s.execute(
                text("SELECT fetch_failures, last_fetch_error, last_crawl_attempt FROM sitemaps WHERE sitemap_id = :id"),
                {"id": sitemap_id},
            ).fetchone()
        assert row.fetch_failures == 2
        assert row.last_fetch_error == "ConnectionError: timed out"
        assert row.last_crawl_attempt is not None, "a failure must stamp the cooldown like a success does"

        eligible_ids = {r.sitemap_id for r in ds.sql_alchemy_sitemap.load_all_sitemaps(website=SOURCE, n_limit=1000)}
        assert sitemap_id not in eligible_ids, "still inside the cooldown window right after the failure"


class TestTransientFailureRecordPersistence:
    """SYS-62 (#200): a first transient failure stores its reason and the
    cooldown stamp without a strike; the reason is what makes the next
    transient failure a strike."""

    def test_record_fetch_error_stores_the_reason_and_stamps_without_a_strike(self, ds_and_client):
        ds, client = ds_and_client
        sitemap_id = _insert_sitemap(client, "http://sys62.test/burst")

        ds.record_fetch_error([sitemap_id], "ConnectionError after 5 retries")

        with client.get_session() as s:
            row = s.execute(
                text("SELECT fetch_failures, last_fetch_error, last_crawl_attempt > NOW() - INTERVAL '1 minute' "
                     "AS stamped FROM sitemaps WHERE sitemap_id = :id"),
                {"id": sitemap_id},
            ).fetchone()
        assert row.fetch_failures == 0
        assert row.last_fetch_error == "ConnectionError after 5 retries"
        assert row.stamped, "a failure must stamp the cooldown like a success does"
        eligible_ids = {r.sitemap_id for r in ds.sql_alchemy_sitemap.load_all_sitemaps(website=SOURCE, n_limit=1000)}
        assert sitemap_id not in eligible_ids

    def test_get_last_fetch_errors_maps_each_row(self, ds_and_client):
        ds, client = ds_and_client
        failed = _insert_sitemap(client, "http://sys62.test/failed")
        clean = _insert_sitemap(client, "http://sys62.test/clean")
        ds.record_fetch_error([failed], "HTTP 502")

        assert ds.get_last_fetch_errors([failed, clean, -1]) == {failed: "HTTP 502", clean: None}
        assert ds.get_last_fetch_errors([]) == {}
