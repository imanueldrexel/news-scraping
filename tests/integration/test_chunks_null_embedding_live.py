"""
DBT-23 (#74): a chunks row with embedding_id NULL is visible to the dedup
(get_existing_sitemap_level_pairs does not count its level as saved) and is
repaired in place by save_chunks (upsert on the DBT-09 unique index) -- no
duplicate row, same chunk_id, embedding_id filled. Against the real table.
"""
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "DBT23TEST"


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


def _seed(client, chunk_rows):
    """chunk_rows: list of (level, index, embedding_id|None)."""
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
                 "VALUES ('h', :l, :s, 'bisnis', 20260922, 'saved') RETURNING sitemap_id"),
            {"l": f"https://dbt23.test/{uuid.uuid4().hex}", "s": SOURCE}).scalar()
        aid = s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, writer, meta_data) "
                             "VALUES (:sid, 'body', '[]', '{}') RETURNING articles_id"), {"sid": sid}).scalar()
        for level, index, emb in chunk_rows:
            s.execute(text("INSERT INTO chunks (sitemap_id, article_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                           "is_last_chunk, text_content, token_count, embedding_id, chunk_status) "
                           "VALUES (:sid, :aid, :lv, :ix, 2, false, false, 'text', 10, :emb, :st)"),
                      {"sid": sid, "aid": aid, "lv": level, "ix": index, "emb": emb,
                       "st": "embedded" if emb else "pending_embedding"})
        s.commit()
    return sid


def _rows(client, sid):
    with client.get_session() as s:
        return s.execute(text("SELECT chunk_id, chunk_level, chunk_index, embedding_id, chunk_status FROM chunks "
                              "WHERE sitemap_id = :sid ORDER BY chunk_level, chunk_index"), {"sid": sid}).fetchall()


class TestNullEmbeddingChunkRowsLive:
    def test_level_with_a_null_row_is_not_counted_as_saved(self, client):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
            SQLAlchemyChunkDataSource,
        )
        ds = SQLAlchemyChunkDataSource(client)
        healthy = _seed(client, [(1, 0, "e-h1"), (2, 0, "e-h2a"), (2, 1, "e-h2b")])
        partial = _seed(client, [(1, 0, "e-p1"), (2, 0, "e-p2a"), (2, 1, None)])   # one NULL at level 2
        pairs = ds.get_existing_sitemap_level_pairs([healthy, partial])
        assert (healthy, 1) in pairs and (healthy, 2) in pairs
        assert (partial, 1) in pairs
        assert (partial, 2) not in pairs, "a level with a NULL embedding_id must be offered for re-save"
        assert ds.count_unembedded() >= 1

    def test_save_chunks_repairs_the_null_row_in_place_without_duplicating(self, client):
        from newscrawler.infrastructure.datasource.dataflow.model.chunk_model import ChunkModel
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
            SQLAlchemyChunkDataSource,
        )
        ds = SQLAlchemyChunkDataSource(client)
        sid = _seed(client, [(2, 0, "e-2a"), (2, 1, None)])
        before = _rows(client, sid)
        null_chunk_id = [r.chunk_id for r in before if r.embedding_id is None][0]

        ds.save_chunks([
            ChunkModel(sitemap_id=sid, chunk_level=2, chunk_index=0, chunk_total=2, is_first_chunk=True,
                       is_last_chunk=False, text_content="text", token_count=10, embedding_id="e-2a", chunk_status="embedded"),
            ChunkModel(sitemap_id=sid, chunk_level=2, chunk_index=1, chunk_total=2, is_first_chunk=False,
                       is_last_chunk=True, text_content="text", token_count=10, embedding_id="e-2b-new", chunk_status="embedded"),
        ])
        after = _rows(client, sid)
        assert len(after) == 2, "upsert must not add rows"
        repaired = [r for r in after if r.chunk_index == 1][0]
        assert repaired.chunk_id == null_chunk_id and repaired.embedding_id == "e-2b-new" and repaired.chunk_status == "embedded"
        assert ds.get_existing_sitemap_level_pairs([sid]) == {(sid, 2)}
