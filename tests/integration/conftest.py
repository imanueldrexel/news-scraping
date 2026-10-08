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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REAL_OUTBOX = os.path.join(REPO_ROOT, "logs", "telegram_outbox.jsonl")


def _outbox_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


@pytest.fixture(autouse=True)
def _isolated_run_lock(tmp_path, monkeypatch):
    """DBT-61 (#281): the scripts under test write test indexes in temp directories, yet they
    checked the production run lock and refused (exit 2) whenever the 07:00/19:00 crawl held it:
    8 false failures per run in that window. The lock is a per-test path, as in tests/unit;
    tests/unit/test_run_lock.py covers the real refusal."""
    from newscrawler.tools import run_lock
    monkeypatch.setattr(run_lock, "LOCK_PATH", str(tmp_path / "scheduled_crawl.lock"))


@pytest.fixture(autouse=True)
def _isolated_telegram_outbox(tmp_path, monkeypatch):
    """OPS-46 (#259): with no bot token, a script under test (the SYS-73 repair notifies) queued
    its alert into the real logs/telegram_outbox.jsonl, and the next real send delivered it to the
    owner: 10 per run. The outbox is a per-test path, as in tests/unit (OPS-32), and a test that
    still adds a line to the real one fails. (A scheduled job queues there only when its own send
    fails, so a concurrent real run is not expected to trip this.)"""
    outbox = str(tmp_path / "telegram_outbox.jsonl")
    monkeypatch.setenv("TELEGRAM_OUTBOX", outbox)
    import newscrawler.core.constants as constants
    monkeypatch.setattr(constants, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(constants, "TELEGRAM_CHAT_ID", "")
    import sys
    notifier = sys.modules.get("notify_telegram")
    if notifier is not None:
        monkeypatch.setattr(notifier, "TELEGRAM_BOT_TOKEN", "", raising=False)
        monkeypatch.setattr(notifier, "TELEGRAM_CHAT_ID", "", raising=False)
        monkeypatch.setattr(notifier, "OUTBOX_PATH", outbox, raising=False)
    before = _outbox_lines(REAL_OUTBOX)
    yield
    assert _outbox_lines(REAL_OUTBOX) <= before, (
        f"OPS-46: this test queued a Telegram alert into the real {REAL_OUTBOX}; the next real send "
        "would deliver it to the owner. Remove the line(s) and redirect the notifier.")


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
