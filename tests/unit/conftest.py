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
