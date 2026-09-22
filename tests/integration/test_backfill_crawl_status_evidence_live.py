"""
DBT-26 (#85): backfill_sitemap_crawl_status.py must never offer for
classification a pending sitemap that already has a chunks row or an L1 FAISS
vector -- both are direct evidence the ORIGINAL title+body filter passed, and
the script's headline-only re-check stamped 582 such rows rejected_filter
(terminal) on 2026-09-16 (DBT-20). Real table; the L1 set is passed in.
"""
import os
import sys
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
SOURCE = "DBT26TEST"


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
        s.execute(text("DELETE FROM chunks WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources = :s)"), {"s": SOURCE})
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources = :s)"), {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _seed(client, with_chunk=False):
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status, last_crawl_attempt) "
                 "VALUES ('Ria Ricis Nangis Lihat Sapi Kurbannya Disembelih', :l, :s, 'news', 20260922, 'pending', NOW()) "
                 "RETURNING sitemap_id"),
            {"l": f"https://dbt26.test/{uuid.uuid4().hex}", "s": SOURCE}).scalar()
        if with_chunk:
            # chunks.article_id is nullable and 100% NULL in production (DBT-11):
            # a chunks row with no articles row is exactly DBT-20's shape.
            s.execute(text("INSERT INTO chunks (sitemap_id, article_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                           "is_last_chunk, text_content, token_count, embedding_id, chunk_status) "
                           "VALUES (:sid, NULL, 1, 0, 1, true, true, 't', 5, 'e', 'embedded')"), {"sid": sid})
        s.commit()
    return sid


class TestEvidencedRowsAreNeverCandidates:
    def test_chunks_row_or_l1_vector_excludes_the_sitemap(self, client):
        from backfill_sitemap_crawl_status import fetch_candidates

        plain = _seed(client)
        with_chunks = _seed(client, with_chunk=True)
        with_l1 = _seed(client)

        with client.get_session() as s:
            rows, evidenced = fetch_candidates(s, SOURCE, l1_ids={with_l1})
        ids = {r.sitemap_id for r in rows}
        assert plain in ids
        assert with_chunks not in ids, "a sitemap with a chunks row must not be re-classified by headline"
        assert with_l1 not in ids, "a sitemap with an L1 vector must not be re-classified by headline"
        assert evidenced == 2

    def test_no_l1_index_means_only_the_chunks_guard(self, client):
        from backfill_sitemap_crawl_status import fetch_candidates
        plain = _seed(client)
        with client.get_session() as s:
            rows, evidenced = fetch_candidates(s, SOURCE, l1_ids=set())
        assert plain in {r.sitemap_id for r in rows} and evidenced == 0
