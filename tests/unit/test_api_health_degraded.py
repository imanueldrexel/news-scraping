"""OPS-06 (#54): a failed stats query must not read as a healthy zero.

`get_stats` never raised -- it swallowed to `{}` -- so every `.get(key, 0)` in the
health handler resolved to its default and the endpoint answered
`{"status": "ok", "articles_indexed": 0, "chunks_indexed": 0, ...}` with HTTP 200
while `newsletter_digests` was missing on production for ~4 months. A monitor
keyed on `status` saw green; a human saw "0 articles" and had to guess whether the
corpus was empty or the query broke. The `degraded` branch was unreachable for
exactly the failure it was written for.
"""
import pytest

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (
    SQLAlchemyNewsletterDataSource,
)

ERRORS = SQLAlchemyNewsletterDataSource.ERRORS_KEY


class _Session:
    def __init__(self, failing):
        self.failing = failing

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, statement, *a, **kw):
        sql = str(statement)
        for table in self.failing:
            if table in sql:
                raise RuntimeError('relation "%s" does not exist' % table)
        return _Scalar()

    def commit(self):
        pass


class _Scalar:
    def scalar(self):
        return 7


class _Client:
    def __init__(self, failing=()):
        self.failing = failing

    def get_session(self):
        return _Session(self.failing)


class TestGetStatsReportsFailures:
    def test_all_succeeding_reports_no_errors(self):
        stats = SQLAlchemyNewsletterDataSource(_Client()).get_stats()
        assert stats[ERRORS] == {}
        assert stats["total_articles"] == 7

    def test_one_missing_table_is_named_and_the_rest_survive(self):
        """OPS-05's isolation kept: one broken metric must not blank the others."""
        stats = SQLAlchemyNewsletterDataSource(_Client(("newsletter_digests",))).get_stats()
        assert list(stats[ERRORS]) == ["digests_generated"]
        assert "does not exist" in stats[ERRORS]["digests_generated"]
        assert stats["digests_generated"] is None, "a failed query is unknown, not zero"
        assert stats["total_articles"] == 7, "the other metrics still came through"

    def test_a_total_outage_names_every_metric(self):
        failing = ("articles", "chunks", "entities", "sitemaps", "newsletter_digests", "crawl_log")
        stats = SQLAlchemyNewsletterDataSource(_Client(failing)).get_stats()
        assert len(stats[ERRORS]) == len(SQLAlchemyNewsletterDataSource._STATS_QUERIES)


class TestHealthPayload:
    def _payload(self, monkeypatch, failing=()):
        import newscrawler.web.app as app
        monkeypatch.setattr(app, "_get_stats_ds", lambda: SQLAlchemyNewsletterDataSource(_Client(failing)))
        monkeypatch.setattr(app, "_faiss_doc_counts", lambda: {"l1": 0, "l2": 0})
        return app._health_payload()

    def test_ok_when_every_metric_answered(self, monkeypatch):
        p = self._payload(monkeypatch)
        assert p["status"] == "ok" and "errors" not in p
        assert p["articles_indexed"] == 7

    def test_degraded_and_named_when_a_metric_failed(self, monkeypatch):
        p = self._payload(monkeypatch, ("newsletter_digests",))
        assert p["status"] == "degraded"
        assert "digests_generated" in p["errors"]
        # and the number is absent rather than a misleading 0
        assert p["digests_generated"] is None

    def test_a_zero_count_is_still_ok(self, monkeypatch):
        """The distinction the fix exists for: an empty corpus is healthy."""
        import newscrawler.web.app as app

        class _Zero(_Scalar):
            def scalar(self):
                return 0

        class _ZeroSession(_Session):
            def execute(self, statement, *a, **kw):
                return _Zero()

        class _ZeroClient:
            def get_session(self):
                return _ZeroSession(())

        monkeypatch.setattr(app, "_get_stats_ds", lambda: SQLAlchemyNewsletterDataSource(_ZeroClient()))
        monkeypatch.setattr(app, "_faiss_doc_counts", lambda: {"l1": 0, "l2": 0})
        p = app._health_payload()
        assert p["status"] == "ok" and p["articles_indexed"] == 0

    def test_an_unexpected_exception_is_still_degraded(self, monkeypatch):
        import newscrawler.web.app as app

        def _boom():
            raise RuntimeError("connection refused")

        monkeypatch.setattr(app, "_get_stats_ds", _boom)
        p = app._health_payload()
        assert p["status"] == "degraded" and "connection refused" in p["error"]


class TestHealthEndpointStatusCode:
    """The HTTP code must move too -- a monitor keyed on it has to see the failure."""

    def _client(self, monkeypatch, failing=()):
        from fastapi.testclient import TestClient
        import newscrawler.web.app as app
        monkeypatch.setattr(app, "_get_stats_ds", lambda: SQLAlchemyNewsletterDataSource(_Client(failing)))
        monkeypatch.setattr(app, "_faiss_doc_counts", lambda: {"l1": 0, "l2": 0})
        return TestClient(app.app)

    def test_200_when_healthy(self, monkeypatch):
        r = self._client(monkeypatch).get("/api/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"

    def test_503_when_degraded(self, monkeypatch):
        r = self._client(monkeypatch, ("newsletter_digests",)).get("/api/health")
        assert r.status_code == 503, "a failed stats query still answered 200"
        assert r.json()["status"] == "degraded"
