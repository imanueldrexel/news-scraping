"""
DBT-32 (#141): scripts/requeue_finance_rejects.py's candidate SELECT against a
real table -- a `rejected_filter` finance row that already has an articles row
must not be offered (SYS-16 backfill misclassification, DBT-26's shape), and
the UPDATE must flip status and clear the cooldown on exactly the targets.
"""
import uuid
from datetime import datetime

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "DBT32REQ"


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
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources = :s)"),
                  {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _seed(client, category, crawl_status, with_article=False):
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status, last_crawl_attempt) "
                 "VALUES ('h', :l, :s, :c, 20260920, :st, :t) RETURNING sitemap_id"),
            {"l": f"https://dbt32req.test/{uuid.uuid4().hex}", "s": SOURCE, "c": category, "st": crawl_status,
             "t": datetime(2026, 9, 20, 12, 0)},
        ).scalar()
        if with_article:
            s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, writer, meta_data) "
                           "VALUES (:sid, 'body', '[]', '{}')"), {"sid": sid})
        s.commit()
    return sid


def _state(client, sid):
    with client.get_session() as s:
        return s.execute(text("SELECT crawl_status, last_crawl_attempt FROM sitemaps WHERE sitemap_id = :id"),
                         {"id": sid}).fetchone()


class TestRequeueFinanceRejectsLive:
    def test_rows_with_an_article_are_not_candidates_and_the_update_only_touches_targets(self, client):
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
        from requeue_finance_rejects import _REQUEUE_SQL, find_finance_rejects

        finance_reject = _seed(client, "bisnis", "rejected_filter")
        finance_reject_with_article = _seed(client, "bisnis", "rejected_filter", with_article=True)
        finance_saved = _seed(client, "bisnis", "saved", with_article=True)
        hard_news_reject = _seed(client, "nasional", "rejected_filter")
        soft_reject = _seed(client, "hiburan", "rejected_filter")

        with client.get_session() as s:
            targets, by_key = find_finance_rejects(s, [SOURCE])
        assert targets == [finance_reject]
        assert by_key == {(SOURCE, "bisnis"): 1}

        with client.get_session() as s:
            updated = s.execute(_REQUEUE_SQL, {"ids": targets, "reset_cooldown": True}).rowcount
            s.commit()
        assert updated == 1
        assert _state(client, finance_reject) == ("pending", None)
        assert _state(client, finance_reject_with_article)[0] == "rejected_filter"
        assert _state(client, finance_saved)[0] == "saved"
        assert _state(client, hard_news_reject)[0] == "rejected_filter"
        assert _state(client, soft_reject)[0] == "rejected_filter"

        # A second pass finds nothing.
        with client.get_session() as s:
            assert find_finance_rejects(s, [SOURCE])[0] == []
