"""
Regression tests for SQLAlchemy data source classes.

Coverage:
  DS-01..DS-04  save_sitemaps() ID management (B2)
  DS-05..DS-07  load_all_sitemaps() unprocessed filter
  DS-08..DS-09  load_last_time_crawling() type coercion (B1/B6)

Requires live PostgreSQL matching DB_CONFIG.
"""
import os
from datetime import datetime, timezone, timedelta

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
def db_client():
    """SQLAlchemyClient connected to the test DB."""
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    try:
        client = SQLAlchemyClient()
        return client
    except Exception as exc:
        pytest.skip(f"Cannot create SQLAlchemyClient: {exc}")


def make_sitemap_model(headline="Test", link="http://example.com", sources="KOMPAS",
                       category="economy", ts=None, keywords=None):
    from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
    return NewsSitemapModel(
        headline=headline,
        link=link,
        sources=sources,
        category=category,
        posted_at=ts or datetime(2024, 1, 1),  # NewsSitemapModel uses posted_at
        keywords=keywords or ["test"],
    )


def make_details_model(sitemap_id, text=None, reporter=None):
    from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import NewsDetailsModel
    return NewsDetailsModel(
        sitemap_id=sitemap_id,
        extracted_text=text or ["paragraph one", "paragraph two"],
        reporter=reporter or ["Reporter Name"],
        meta_data={},
    )


# ---------------------------------------------------------------------------
# save_sitemaps() — ID management (B2)
# ---------------------------------------------------------------------------

class TestSaveSitemaps:
    def test_DS01_insert_3_sitemaps_sequential_ids(self, db_client, raw_conn):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        ds = SQLAlchemySitemapDataSource(db_client)

        models = [
            make_sitemap_model(headline=f"Article {i}", link=f"http://ex.com/{i}")
            for i in range(3)
        ]
        ds.save_sitemaps(models)

        with raw_conn.cursor() as cur:
            cur.execute("SELECT sitemap_id FROM sitemaps ORDER BY sitemap_id DESC LIMIT 3")
            rows = cur.fetchall()
        ids = sorted(r[0] for r in rows)
        assert ids == list(range(ids[0], ids[0] + 3)), f"IDs not sequential: {ids}"

    def test_DS02_save_sitemaps_inserts_record(self, db_client, raw_conn):
        """save_sitemaps() must persist the new sitemap (B1 regression guard).

        Verify the specific row was inserted by its unique link rather than doing
        MAX(sitemap_id) arithmetic -- BIGSERIAL leaves gaps (rolled-back nested inserts
        consume sequence values), so MAX is not guaranteed to be exactly before+1.
        """
        import uuid
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        ds = SQLAlchemySitemapDataSource(db_client)
        unique_link = f"http://ex.com/{uuid.uuid4()}"

        with raw_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sitemaps")
            count_before = cur.fetchone()[0]

        ds.save_sitemaps([make_sitemap_model(headline="One More", link=unique_link)])

        with raw_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sitemaps WHERE link = %s", (unique_link,))
            inserted = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM sitemaps")
            count_after = cur.fetchone()[0]

        assert inserted == 1, "save_sitemaps() failed to persist the new row"
        assert count_after == count_before + 1, (
            f"expected exactly one new row, count {count_before} -> {count_after}"
        )

    def test_DS03_bigserial_sequence_in_sync(self, raw_conn):
        """BIGSERIAL sequence must be >= MAX(sitemap_id) (B2 regression guard)."""
        with raw_conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(sitemap_id), 0) FROM sitemaps")
            max_id = cur.fetchone()[0]
            cur.execute("SELECT last_value FROM sitemaps_sitemap_id_seq")
            seq_value = cur.fetchone()[0]

        if max_id > 0:
            assert seq_value >= max_id, (
                f"B2 regression: BIGSERIAL sequence last_value={seq_value} < MAX(sitemap_id)={max_id}."
            )


# ---------------------------------------------------------------------------
# load_all_sitemaps() — unprocessed article filter
# ---------------------------------------------------------------------------

class TestLoadAllSitemaps:
    def _raw_insert_sitemap(self, conn, headline, link, source):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sitemaps (headline, link, sources, posted_at) VALUES (%s, %s, %s, %s) RETURNING sitemap_id",
                (headline, link, source, 20240101),
            )
            return cur.fetchone()[0]

    def _raw_insert_article(self, conn, sitemap_id):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO articles (sitemap_id, extracted_text) VALUES (%s, %s)",
                (sitemap_id, '["paragraph"]'),
            )

    def test_DS05_sitemaps_without_articles_returned(self, db_client, raw_conn):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        sid = self._raw_insert_sitemap(raw_conn, "No Article", "http://noarticle.com", "KOMPAS")
        raw_conn.commit()

        ds = SQLAlchemySitemapDataSource(db_client)
        result = ds.load_all_sitemaps("KOMPAS", n_limit=100)
        # load_all_sitemaps returns List[NewsSitemapModel]
        links = [m.link for m in result]
        assert any("noarticle.com" in link for link in links)

    def test_DS06_sitemaps_with_articles_excluded(self, db_client, raw_conn):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        sid = self._raw_insert_sitemap(raw_conn, "Has Article", "http://hasarticle.com", "KOMPAS")
        self._raw_insert_article(raw_conn, sid)
        raw_conn.commit()

        ds = SQLAlchemySitemapDataSource(db_client)
        result = ds.load_all_sitemaps("KOMPAS", n_limit=100)
        links = [m.link for m in result]
        assert not any("hasarticle.com" in link for link in links)

    def test_DS07_mixed_only_unprocessed_returned(self, db_client, raw_conn):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        sid_with = self._raw_insert_sitemap(raw_conn, "With", "http://with.com", "KOMPAS")
        self._raw_insert_article(raw_conn, sid_with)
        self._raw_insert_sitemap(raw_conn, "Without", "http://without.com", "KOMPAS")
        raw_conn.commit()

        ds = SQLAlchemySitemapDataSource(db_client)
        result = ds.load_all_sitemaps("KOMPAS", n_limit=100)
        links = [m.link for m in result]
        assert any("without.com" in link for link in links)
        assert not any("with.com" in link for link in links)


# ---------------------------------------------------------------------------
# Bug B: last_crawl_attempt cooldown — load_all_sitemaps must skip recently-attempted
#        sitemaps and mark_sitemaps_attempted must stamp the timestamp.
# ---------------------------------------------------------------------------

class TestCrawlAttemptCooldown:
    def _insert(self, conn, headline, link, last_attempt_sql):
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO sitemaps (headline, link, sources, posted_at, last_crawl_attempt) "
                f"VALUES (%s, %s, 'COOLDOWNTEST', 20240101, {last_attempt_sql}) RETURNING sitemap_id",
                (headline, link),
            )
            return cur.fetchone()[0]

    def test_DS10_never_attempted_is_returned(self, db_client, raw_conn):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        self._insert(raw_conn, "Never", "http://never.com", "NULL")
        raw_conn.commit()
        ds = SQLAlchemySitemapDataSource(db_client)
        links = [m.link for m in ds.load_all_sitemaps("COOLDOWNTEST", n_limit=100)]
        assert any("never.com" in l for l in links)

    def test_DS11_recently_attempted_is_excluded(self, db_client, raw_conn):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        self._insert(raw_conn, "Recent", "http://recent.com", "NOW()")
        raw_conn.commit()
        ds = SQLAlchemySitemapDataSource(db_client)
        links = [m.link for m in ds.load_all_sitemaps("COOLDOWNTEST", n_limit=100)]
        assert not any("recent.com" in l for l in links), "recently-attempted must be excluded"

    def test_DS12_old_attempt_past_cooldown_is_returned(self, db_client, raw_conn):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        # 30 days ago is well past the default 7-day cooldown
        self._insert(raw_conn, "Old", "http://old.com", "NOW() - INTERVAL '30 days'")
        raw_conn.commit()
        ds = SQLAlchemySitemapDataSource(db_client)
        links = [m.link for m in ds.load_all_sitemaps("COOLDOWNTEST", n_limit=100)]
        assert any("old.com" in l for l in links), "attempt older than cooldown must be eligible again"

    def test_DS13_mark_sitemaps_attempted_sets_timestamp(self, db_client, raw_conn):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        sid = self._insert(raw_conn, "ToMark", "http://tomark.com", "NULL")
        raw_conn.commit()
        ds = SQLAlchemySitemapDataSource(db_client)
        ds.mark_sitemaps_attempted([sid])
        with raw_conn.cursor() as cur:
            cur.execute("SELECT last_crawl_attempt FROM sitemaps WHERE sitemap_id = %s", (sid,))
            val = cur.fetchone()[0]
        assert val is not None, "mark_sitemaps_attempted must set last_crawl_attempt"

    def test_DS14_mark_empty_list_is_noop(self, db_client):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        ds = SQLAlchemySitemapDataSource(db_client)
        ds.mark_sitemaps_attempted([])  # must not raise


# ---------------------------------------------------------------------------
# load_last_time_crawling() — type coercion (B1/B6)
# ---------------------------------------------------------------------------

class TestLoadLastTimeCrawling:
    def test_DS08_posted_at_as_timestamp_works(self, db_client, raw_conn):
        """If posted_at is stored as TIMESTAMP, .replace(tzinfo=...) succeeds."""
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        # Insert sitemap via ORM (which stores posted_at as TIMESTAMP)
        from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
        model = make_sitemap_model(sources="KOMPAS", category="economy")

        ds = SQLAlchemySitemapDataSource(db_client)
        ds.save_sitemaps([model])

        try:
            result = ds.load_last_time_crawling()
            # Should not raise
            assert isinstance(result, dict)
        except AttributeError as e:
            pytest.fail(
                f"B6 CONFIRMED: load_last_time_crawling() crashed because posted_at "
                f"is not a datetime: {e}"
            )

    def test_DS09_load_last_time_crawling_returns_datetime_for_integer_posted_at(self, raw_conn, db_client):
        """load_last_time_crawling() must parse INTEGER posted_at to datetime (B6 regression guard)."""
        with raw_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sitemaps (headline, link, sources, category, posted_at)
                VALUES ('IntTest', 'http://inttest.com', 'INTTEST', 'tech', 20240101)
            """)
        raw_conn.commit()

        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        ds = SQLAlchemySitemapDataSource(db_client)
        result = ds.load_last_time_crawling()

        assert "INTTEST" in result, "Source not found in crawling times"
        val = list(result["INTTEST"].values())[0]
        assert isinstance(val, datetime), (
            f"Expected datetime, got {type(val).__name__}: {val!r}"
        )
