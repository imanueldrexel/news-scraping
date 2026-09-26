"""Shared unit-test setup."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_run_lock(tmp_path, monkeypatch):
    """OPS-26: FAISS saves refuse while a scheduled crawl holds the run lock. Point
    the lock at a per-test path so the suite neither sees nor takes the real one
    (a unit run during the 07:00/19:00 crawl would otherwise fail its FAISS tests)."""
    from newscrawler.tools import run_lock
    monkeypatch.setattr(run_lock, "LOCK_PATH", str(tmp_path / "scheduled_crawl.lock"))
