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


def _apply_pending_migrations(conn):
    """scripts/migrate.py's apply_pending on this connection (the test DB, checked by the caller)."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "scripts", "migrate.py")
    spec = importlib.util.spec_from_file_location("migrate_for_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    applied = module.apply_pending(conn)
    if applied:
        print(f"[integration conftest] applied to newsaggregator_test: {', '.join(applied)}")


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
        # DBT-22 (#73): the test DB is disposable, so apply what it is missing instead of
        # only asserting it (test_schema's assertion stays as the backstop). DBT-09's
        # migration was once applied to newsaggregator and not here, and the suite went red.
        _apply_pending_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE chunks, entity_mentions, entity_aliases, entities, "
                "articles, api_usage_log, crawl_log, sitemaps "
                "RESTART IDENTITY CASCADE"
            )
        conn.commit()
    finally:
        conn.close()
    yield
