"""Shared unit-test setup."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_run_lock(tmp_path, monkeypatch):
    """OPS-26: FAISS saves refuse while a scheduled crawl holds the run lock. Point
    the lock at a per-test path so the suite neither sees nor takes the real one
    (a unit run during the 07:00/19:00 crawl would otherwise fail its FAISS tests)."""
    from newscrawler.tools import run_lock
    monkeypatch.setattr(run_lock, "LOCK_PATH", str(tmp_path / "scheduled_crawl.lock"))


@pytest.fixture(autouse=True)
def _no_real_backoff_sleep(monkeypatch):
    """SYS-66/SYS-70: the page loader sleeps between retries and to pace a host.
    Unit tests never wait for real; a test that needs the delays patches
    requests_page_loader._sleep with a recorder of its own."""
    from newscrawler.core.page_loader import requests_page_loader
    from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
    monkeypatch.setattr(requests_page_loader, "_sleep", lambda seconds: None)
    # SYS-64: the FAISS rename retry's backoff, likewise.
    monkeypatch.setattr(index_generation, "_sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def _no_real_database_or_telegram(monkeypatch, tmp_path):
    """DBT-53 (#226): a unit test may not reach a database or Telegram. The default
    POSTGRES_DB_* point at production, so a test that exercises a script whose guard
    is broken (a mutant, a refactor) used to run it for real: the OPS-38 mutation run
    rewrote the 2026-10-04 digest row at 17:44. Every connection now fails loudly;
    the integration suite (which forces newsaggregator_test) is where Postgres is used.
    A test that needs a connection patches psycopg2.connect itself, after this."""
    import psycopg2

    def refuse(*args, **kwargs):
        raise AssertionError("unit tests may not reach a database: patch the client or move the test to "
                             "tests/integration (DBT-53)")
    monkeypatch.setattr(psycopg2, "connect", refuse)

    import newscrawler.core.constants as constants
    monkeypatch.setattr(constants, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(constants, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setenv("TELEGRAM_OUTBOX", str(tmp_path / "telegram_outbox.jsonl"))
    import sys
    notifier = sys.modules.get("notify_telegram")
    if notifier is not None:
        monkeypatch.setattr(notifier, "TELEGRAM_BOT_TOKEN", "", raising=False)
        monkeypatch.setattr(notifier, "TELEGRAM_CHAT_ID", "", raising=False)
        monkeypatch.setattr(notifier, "OUTBOX_PATH", str(tmp_path / "telegram_outbox.jsonl"), raising=False)
