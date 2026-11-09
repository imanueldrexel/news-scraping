"""
OPS-15 (#81): scripts/reset_fetch_failures.py against a live PostgreSQL -- the
reset path SYS-09's fetch_failures cap shipped without. A retired sitemap
(fetch_failures >= SITEMAP_MAX_FETCH_FAILURES) must come back into
load_all_sitemaps' queue; rows outside the filter, and rows that never failed,
must be untouched.
"""
import importlib.util
import os
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES  # noqa: E402

SOURCE_A = "OPS15A"
SOURCE_B = "OPS15B"
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "reset_fetch_failures.py",
)


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("reset_fetch_failures_live", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    with c.get_session() as s:
        s.execute(text("DELETE FROM sitemaps WHERE sources IN (:a, :b)"), {"a": SOURCE_A, "b": SOURCE_B})
        s.commit()


def _seed(client, failures, error=None, source=SOURCE_A, attempted_days_ago=1):
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, posted_at, fetch_failures, last_fetch_error, "
                 "last_crawl_attempt) VALUES ('t', :l, :s, 20260901, :f, :e, NOW() - make_interval(days => :d)) "
                 "RETURNING sitemap_id"),
            {"l": f"https://ops15.test/{uuid.uuid4().hex}", "s": source, "f": failures, "e": error,
             "d": attempted_days_ago},
        ).scalar()
        s.commit()
    return sid


def _row(client, sid):
    with client.get_session() as s:
        return s.execute(text("SELECT fetch_failures, last_fetch_error, last_crawl_attempt FROM sitemaps "
                              "WHERE sitemap_id = :id"), {"id": sid}).fetchone()


def _eligible(client, source):
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
        SQLAlchemySitemapDataSource,
    )
    return {r.sitemap_id for r in SQLAlchemySitemapDataSource(client).load_all_sitemaps(website=source, n_limit=1000)}


class TestResetFetchFailures:
    def test_website_filter_resets_only_that_source_and_only_failed_rows(self, script, client):
        retired_a = _seed(client, SITEMAP_MAX_FETCH_FAILURES, "HTTP 403", source=SOURCE_A)
        flaky_a = _seed(client, 1, "ReadTimeout after 5 retries", source=SOURCE_A)
        clean_a = _seed(client, 0, None, source=SOURCE_A)
        retired_b = _seed(client, SITEMAP_MAX_FETCH_FAILURES, "HTTP 403", source=SOURCE_B)

        assert script.main(["--website", SOURCE_A]) == 0

        assert _row(client, retired_a)[:2] == (0, None)
        assert _row(client, flaky_a)[:2] == (0, None)
        assert _row(client, clean_a)[:2] == (0, None)
        assert _row(client, retired_b)[:2] == (SITEMAP_MAX_FETCH_FAILURES, "HTTP 403"), "other source untouched"

    def test_all_retired_leaves_rows_below_the_cap_alone(self, script, client):
        retired = _seed(client, SITEMAP_MAX_FETCH_FAILURES, "HTTP 404")
        flaky = _seed(client, SITEMAP_MAX_FETCH_FAILURES - 1, "HTTP 404")

        assert script.main(["--all-retired", "--website", SOURCE_A]) == 0

        assert _row(client, retired).fetch_failures == 0
        assert _row(client, flaky).fetch_failures == SITEMAP_MAX_FETCH_FAILURES - 1

    def test_like_filter_targets_one_failure_mode(self, script, client):
        blocked = _seed(client, SITEMAP_MAX_FETCH_FAILURES, "HTTP 403")
        gone = _seed(client, SITEMAP_MAX_FETCH_FAILURES, "HTTP 404")

        assert script.main(["--like", "HTTP 403%", "--website", SOURCE_A]) == 0

        assert _row(client, blocked).fetch_failures == 0
        assert _row(client, gone).fetch_failures == SITEMAP_MAX_FETCH_FAILURES

    def test_a_reset_row_re_enters_the_queue_once_its_cooldown_allows(self, script, client):
        retired = _seed(client, SITEMAP_MAX_FETCH_FAILURES, "HTTP 403", attempted_days_ago=30)
        assert retired not in _eligible(client, SOURCE_A), "precondition: retired rows are excluded"

        script.main(["--website", SOURCE_A])

        assert retired in _eligible(client, SOURCE_A)

    def test_clear_cooldown_makes_a_recently_failed_row_eligible_immediately(self, script, client):
        retired = _seed(client, SITEMAP_MAX_FETCH_FAILURES, "HTTP 403", attempted_days_ago=0)

        script.main(["--website", SOURCE_A])
        assert retired not in _eligible(client, SOURCE_A), "without --clear-cooldown the cooldown still applies"

        _seed_again = _seed(client, SITEMAP_MAX_FETCH_FAILURES, "HTTP 403", attempted_days_ago=0)
        script.main(["--website", SOURCE_A, "--clear-cooldown"])
        assert _row(client, _seed_again).last_crawl_attempt is None
        assert _seed_again in _eligible(client, SOURCE_A)

    def test_dry_run_changes_nothing(self, script, client, capsys):
        retired = _seed(client, SITEMAP_MAX_FETCH_FAILURES, "HTTP 403")

        assert script.main(["--website", SOURCE_A, "--dry-run"]) == 0

        assert _row(client, retired).fetch_failures == SITEMAP_MAX_FETCH_FAILURES
        assert f"{SOURCE_A}: 1" in capsys.readouterr().out

    def test_refuses_to_run_without_any_filter(self, script):
        with pytest.raises(SystemExit):
            script.main([])
