"""SYS-147 (#337): the story arcs' timeline rows through the real SQL on the test DB.

A timeline item is a past article a reader can follow: its headline, outlet and
date come from the database (never FAISS metadata, ADR-005/SYS-91), with its L1
text for the opening; a sitemap without an article row is not one.
"""
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402


@pytest.fixture
def seeded():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    try:
        with client.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    rows = [  # (headline, source, posted_at, has_article, l1)
        ("Prabowo Pimpin Ratas Karhutla &amp; Panggil Ahli", "CNBC", 20260924, True, "Reporter: A | Editor: B\nIsi."),
        ("Hotspot Karhutla Naik", "BERITASATU", 20261009, True, None),
        ("Tanpa Artikel", "KOMPAS", 20261001, False, "Pembuka."),
    ]
    ids = []
    with client.get_session() as s:
        for headline, source, posted, has_article, l1 in rows:
            sid = s.execute(text(
                "INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
                "VALUES (:h, :l, :s, 'news', :p, 'saved') RETURNING sitemap_id"),
                {"h": headline, "l": f"https://arc.test/{uuid.uuid4().hex}", "s": source, "p": posted}).scalar()
            article_id = None
            if has_article:
                article_id = s.execute(text(
                    "INSERT INTO articles (sitemap_id, extracted_text, meta_data, is_embedded) "
                    "VALUES (:sid, 'teks', '{}', true) RETURNING articles_id"), {"sid": sid}).scalar()
            if l1 is not None:
                s.execute(text(
                    "INSERT INTO chunks (sitemap_id, article_id, chunk_level, chunk_index, chunk_total, "
                    "is_first_chunk, is_last_chunk, text_content, chunk_status) "
                    "VALUES (:sid, :aid, 1, 0, 1, true, true, :body, 'embedded')"),
                    {"sid": sid, "aid": article_id, "body": l1})
            ids.append(sid)
        s.commit()
    yield client, ids
    with client.get_session() as s:
        s.execute(text("DELETE FROM chunks WHERE sitemap_id = ANY(:ids)"), {"ids": ids})
        s.execute(text("DELETE FROM articles WHERE sitemap_id = ANY(:ids)"), {"ids": ids})
        s.execute(text("DELETE FROM sitemaps WHERE sitemap_id = ANY(:ids)"), {"ids": ids})
        s.commit()


def test_timeline_rows_come_from_the_database(seeded):
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (
        SQLAlchemyNewsletterDataSource,
    )
    client, (ratas, hotspot, no_article) = seeded
    rows = SQLAlchemyNewsletterDataSource(client).get_timeline_rows([ratas, hotspot, no_article, ratas])
    assert set(rows) == {ratas, hotspot}                        # no article row, no timeline item
    assert rows[ratas] == {"headline": "Prabowo Pimpin Ratas Karhutla & Panggil Ahli",   # SYS-88 unescaped
                           "source": "CNBC", "posted_at": 20260924, "l1_text": "Reporter: A | Editor: B\nIsi."}
    assert rows[hotspot]["l1_text"] == ""                       # an article without an L1 chunk still counts
    assert SQLAlchemyNewsletterDataSource(client).get_timeline_rows([]) == {}


def test_the_finder_over_the_real_rows(seeded):
    """thread_finder with a fake search and the real lookup: dates, outlet and opening from the DB."""
    from datetime import date

    from newscrawler.core.thread_finder import find_thread
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (
        SQLAlchemyNewsletterDataSource,
    )
    client, (ratas, hotspot, no_article) = seeded
    hits = [(ratas, 20260924, 0.82), (hotspot, 20261009, 0.75), (no_article, 20261001, 0.9)]
    items = find_thread([0.1], date(2026, 10, 12), [], lambda v, k: hits,
                        SQLAlchemyNewsletterDataSource(client).get_timeline_rows)
    assert [(i.sitemap_id, i.day, i.source, i.opening) for i in items] == [
        (ratas, date(2026, 9, 24), "CNBC", "Isi."), (hotspot, date(2026, 10, 9), "BERITASATU", "")]
