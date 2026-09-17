"""
Integration test configuration.
CRITICAL: Forces all DB connections to the TEST database, never to production.
"""
import os

import pytest

# Force-override regardless of what is in the shell environment or .env.
# This ensures integration tests never touch the production newsaggregator DB.
os.environ["POSTGRES_DB_NAME"]      = "newsaggregator_test"
os.environ["POSTGRES_TEST_DB_NAME"] = "newsaggregator_test"
os.environ["POSTGRES_DB_PASS"]      = "postgres"
os.environ["POSTGRES_DB_PORT"]      = "5431"
os.environ["POSTGRES_DB_HOST"]      = "localhost"
os.environ["POSTGRES_DB_USER"]      = "postgres"

try:
    import psycopg2
except ImportError:
    psycopg2 = None


@pytest.fixture(scope="session", autouse=True)
def _clean_test_db_at_session_start():
    """Start every `pytest tests/integration` run from an empty test DB.

    Several fixtures across this suite commit rows through a raw connection instead
    of rolling back (predates a shared cleanup convention), so debris from a prior
    run -- or a run that crashed before its own per-test teardown ran -- otherwise
    accumulates forever and breaks assertions that depend on exact counts or on
    fixed-value fixture rows (e.g. TestCrawlAttemptCooldown's 'http://recent.com').
    DBT-06 (#29): this is what makes "green twice in a row from any starting state
    of the test DB" achievable instead of order-dependent.
    """
    if psycopg2 is None:
        yield
        return
    try:
        conn = psycopg2.connect(
            host=os.environ["POSTGRES_DB_HOST"],
            port=int(os.environ["POSTGRES_DB_PORT"]),
            user=os.environ["POSTGRES_DB_USER"],
            password=os.environ["POSTGRES_DB_PASS"],
            dbname=os.environ["POSTGRES_DB_NAME"],
        )
    except Exception:
        yield
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            db_name = cur.fetchone()[0]
            if db_name != "newsaggregator_test":
                raise RuntimeError(
                    f"refusing to truncate {db_name!r} -- integration tests must "
                    "run against newsaggregator_test only"
                )
            cur.execute(
                "TRUNCATE chunks, entity_mentions, entity_aliases, entities, "
                "articles, api_usage_log, crawl_log, sitemaps "
                "RESTART IDENTITY CASCADE"
            )
        conn.commit()
    finally:
        conn.close()
    yield
