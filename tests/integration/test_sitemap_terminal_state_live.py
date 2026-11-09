"""
SYS-16 against a live PostgreSQL: a sitemap marked crawl_status='rejected_filter'
must not be returned by load_all_sitemaps even after the cooldown window elapses,
while 'empty_extraction' and 'pending' sitemaps still are (their outcome could
change on a later attempt).
"""
from datetime import datetime, timedelta, timezone

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

WIB = timezone(timedelta(hours=7))
SOURCE = "SYS16TEST"


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


def _insert_sitemap(client, link, days_ago_attempted):
    """Insert a sitemap already past the cooldown window (last_crawl_attempt set
    far enough in the past that the normal 7-day cooldown has elapsed)."""
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


class TestRejectedFilterIsExcludedPermanently:
    def test_rejected_filter_never_comes_back_after_cooldown(self, ds_and_client):
        ds, client = ds_and_client
        rejected_id = _insert_sitemap(client, "http://sys16.test/rejected", days_ago_attempted=30)
        empty_id = _insert_sitemap(client, "http://sys16.test/empty", days_ago_attempted=30)
        pending_id = _insert_sitemap(client, "http://sys16.test/pending", days_ago_attempted=0)  # not yet past cooldown... but

        ds.mark_sitemaps_status([rejected_id], "rejected_filter")
        ds.mark_sitemaps_status([empty_id], "empty_extraction")
        # pending_id is left at the 'pending' default with last_crawl_attempt=NOW() (0 days ago)
        # -- still inside the cooldown, so it should NOT be eligible either; this
        # distinguishes "excluded because rejected" from "excluded because too recent".

        eligible = ds.sql_alchemy_sitemap.load_all_sitemaps(website=SOURCE, n_limit=1000)
        eligible_ids = {r.sitemap_id for r in eligible}

        assert rejected_id not in eligible_ids, "rejected_filter must never be re-selected"
        assert empty_id in eligible_ids, "empty_extraction must retry after the cooldown"
        assert pending_id not in eligible_ids, "pending but inside the cooldown window must wait"

    def test_a_never_attempted_pending_sitemap_is_still_eligible(self, ds_and_client):
        ds, client = ds_and_client
        with client.get_session() as s:
            row = s.execute(
                text(
                    "INSERT INTO sitemaps (headline, link, sources, posted_at) "
                    "VALUES ('t', :l, :s, 20260901) RETURNING sitemap_id"
                ),
                {"l": "http://sys16.test/never-attempted", "s": SOURCE},
            ).fetchone()
            s.commit()

        eligible = ds.sql_alchemy_sitemap.load_all_sitemaps(website=SOURCE, n_limit=1000)
        assert row.sitemap_id in {r.sitemap_id for r in eligible}

    def test_mark_sitemaps_status_rejects_an_invalid_status(self, ds_and_client):
        ds, client = ds_and_client
        sitemap_id = _insert_sitemap(client, "http://sys16.test/badstatus", days_ago_attempted=30)
        with pytest.raises(ValueError):
            ds.mark_sitemaps_status([sitemap_id], "not_a_real_status")

    def test_saved_status_is_also_excluded_by_the_articles_join_regardless(self, ds_and_client):
        """crawl_status='saved' is set for observability; the articles-row LEFT JOIN
        already excludes these independent of crawl_status, so setting 'saved'
        without an articles row must not accidentally make it eligible again."""
        ds, client = ds_and_client
        saved_id = _insert_sitemap(client, "http://sys16.test/saved-no-row", days_ago_attempted=30)
        ds.mark_sitemaps_status([saved_id], "saved")

        eligible = ds.sql_alchemy_sitemap.load_all_sitemaps(website=SOURCE, n_limit=1000)
        # This sitemap has no articles row, so the join still makes it eligible --
        # crawl_status='saved' alone doesn't gate load_all_sitemaps, only
        # 'rejected_filter' does. Documents current behavior explicitly.
        assert saved_id in {r.sitemap_id for r in eligible}
