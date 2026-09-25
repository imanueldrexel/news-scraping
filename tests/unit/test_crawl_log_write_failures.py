"""OPS-07 (#55): a failure to WRITE `crawl_log` must be visible.

`crawl_log` is the pipeline's only non-silent failure record -- `process_event`
catches `BaseException` and logs at INFO, so the runbook's instruction is to read
`crawl_log`. The three writers swallowed their exceptions at DEBUG, below the
INFO level the module sets, so when the table was missing or the DB was briefly
unreachable the run left no row at all and the operator read that as "the
scheduler did not fire". The tolerance is correct; the log level was not.
"""
import logging

import pytest

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
    SQLAlchemyArticleDataSource,
)

_LOGGER = "newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source"


class _BoomSession:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **kw):
        raise RuntimeError('relation "crawl_log" does not exist')

    def commit(self):
        pass


class _BoomClient:
    def get_session(self):
        return _BoomSession()


@pytest.fixture(autouse=True)
def _reset_once_flag():
    SQLAlchemyArticleDataSource._crawl_log_disabled_warned = False
    yield
    SQLAlchemyArticleDataSource._crawl_log_disabled_warned = False


class TestCrawlLogWriteFailuresAreVisible:
    def _ds(self):
        return SQLAlchemyArticleDataSource(_BoomClient())

    def test_log_crawl_start_returns_none_and_warns(self, caplog):
        ds = self._ds()
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            assert ds.log_crawl_start("KOMPAS", "sitemap") is None
        msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("crawl_log INSERT failed" in m and "KOMPAS" in m for m in msgs), msgs
        assert any("crawl_log disabled for this run" in m for m in msgs), msgs

    def test_the_disabled_warning_is_emitted_once_per_run(self, caplog):
        ds = self._ds()
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            for _ in range(3):
                ds.log_crawl_start("KOMPAS", "sitemap")
        disabled = [r for r in caplog.records if "crawl_log disabled for this run" in r.message]
        assert len(disabled) == 1, "the condition is stated once at the top of the log, not per call"

    def test_complete_and_failed_updates_warn_and_do_not_raise(self, caplog):
        ds = self._ds()
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            ds.log_crawl_complete(42, article_count=7)
            ds.log_crawl_failed(42, "boom")
        msgs = [r.message for r in caplog.records]
        assert any("completion update failed" in m and "42" in m for m in msgs), msgs
        assert any("failure update failed" in m and "42" in m for m in msgs), msgs

    def test_nothing_is_logged_when_there_is_no_log_id(self, caplog):
        """The early return on a falsy log_id is unchanged -- it must not warn
        again, the disabled state was already announced by log_crawl_start."""
        ds = self._ds()
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            ds.log_crawl_complete(None, article_count=1)
            ds.log_crawl_failed(None, "boom")
        assert caplog.records == []

    def test_a_write_failure_never_raises(self):
        """The tolerance OPS-07 keeps: a logging failure must not abort a crawl."""
        ds = self._ds()
        ds.log_crawl_start("KOMPAS", "sitemap")
        ds.log_crawl_complete(1)
        ds.log_crawl_failed(1, "x")
