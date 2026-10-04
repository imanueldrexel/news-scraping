"""SYS-39: the scheduled extraction's `pending_count` is the number the Telegram line reports
as "pending A -> B", so it must be what `get_articles_pending_extraction` will still select:
not extracted, and under the SYS-19 attempt cap. Against newsaggregator_test."""
import importlib.util
import os
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "EXTCOUNT"
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "scripts", "run_scheduled_extraction.py")


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
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources=:s)"),
                  {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _article(client, extracted, attempts):
    with client.get_session() as s:
        sid = s.execute(text("INSERT INTO sitemaps (headline, link, sources, posted_at) "
                             "VALUES ('t', :l, :s, 20260930) RETURNING sitemap_id"),
                        {"l": f"https://extcount.test/{uuid.uuid4().hex}", "s": SOURCE}).scalar()
        s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, knowledge_extracted, knowledge_extract_attempts) "
                       "VALUES (:id, 'x', :e, :a)"), {"id": sid, "e": extracted, "a": attempts})
        s.commit()


def _count(client):
    spec = importlib.util.spec_from_file_location("run_scheduled_extraction_live", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with client.get_session() as s:
        return mod.pending_count(s)


def test_pending_is_not_extracted_and_under_the_attempt_cap(client):
    from newscrawler.core.constants import KNOWLEDGE_EXTRACT_MAX_ATTEMPTS as CAP
    before = _count(client)
    _article(client, 0, 0)                 # fresh
    _article(client, 0, CAP - 1)           # failed before, one try left
    _article(client, 0, CAP)               # retired by SYS-19
    _article(client, 1, 0)                 # already extracted
    assert _count(client) - before == 2


def test_it_agrees_with_what_the_extractor_will_select(client):
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
        SQLAlchemyKnowledgeDataSource,
    )
    _article(client, 0, 0)
    _article(client, 0, 99)
    selectable = len(SQLAlchemyKnowledgeDataSource(client).get_articles_pending_extraction(10_000_000))
    assert _count(client) == selectable
