"""SRC-60 (#279): scripts/settle_out_of_scope_links.py against a live PostgreSQL and a real (temp-directory)
FAISS store, with the real KUMPARAN crawler's rule:

  * a reader post's article, chunk rows, vectors and entity mentions go, its sitemap is settled
    rejected_filter, and the entity's counters are recomputed;
  * a pending reader post (no article yet) is settled too, so the queue never fetches it;
  * a newsroom article is untouched (rows and vectors), and so is a reader post settled long ago;
  * a second run finds nothing; the dry run writes nothing.

Uses temp FAISS, backup and lock paths, never the real NEWS_L1/NEWS_L2 or backups/. The test DB is
truncated at the session start, so the source name is the real one."""
import os
import shutil
import tempfile
import uuid
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "KUMPARAN"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")
BODY = "\n\n".join(" ".join(f"kata{i}{j}" for j in range(90)) for i in range(2))


@pytest.fixture(scope="module")
def scripts():
    import sys
    sys.path.insert(0, SCRIPTS)
    import settle_out_of_scope_links
    from newscrawler.tools import store_repair
    return SimpleNamespace(settle=settle_out_of_scope_links, store_repair=store_repair)


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
        ids = "(SELECT sitemap_id FROM sitemaps WHERE sources = :s)"
        s.execute(text(f"DELETE FROM entity_mentions WHERE sitemap_id IN {ids}"), {"s": SOURCE})
        s.execute(text("DELETE FROM entities WHERE normalized_name LIKE 'src60%'"))
        s.execute(text(f"DELETE FROM chunks WHERE sitemap_id IN {ids}"), {"s": SOURCE})
        s.execute(text(f"DELETE FROM articles WHERE sitemap_id IN {ids}"), {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


@pytest.fixture
def env(monkeypatch, scripts):
    tmp = tempfile.mkdtemp(prefix="src60_")
    import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as cfd
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L1", f"{tmp}/L1")
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L2", f"{tmp}/L2")
    monkeypatch.setattr(scripts.store_repair, "BACKUP_DIR", f"{tmp}/backups")
    yield SimpleNamespace(tmp=tmp)
    shutil.rmtree(tmp, ignore_errors=True)


def _sitemap(client, account, status="saved", article=True):
    with client.get_session() as s:
        sid = s.execute(text(
            "INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
            "VALUES ('h', :l, :s, 'bisnis', 20261006, :st) RETURNING sitemap_id"),
            {"l": f"https://kumparan.com/{account}/{uuid.uuid4().hex}?page=all", "s": SOURCE, "st": status}).scalar()
        if article:
            s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, writer, meta_data, knowledge_extracted) "
                           "VALUES (:sid, :t, '[\"r\"]', '{}', 1)"), {"sid": sid, "t": BODY})
        s.commit()
    return sid


def _chunk_and_embed(client):
    import backfill_orphan_chunks
    from newscrawler.core.chunker import HierarchicalChunker
    from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl
    with client.get_session() as s:
        rows = s.execute(backfill_orphan_chunks._FETCH_SQL, {"website": SOURCE}).fetchall()
    repo = DataFlowRepositoryImpl(client)
    with repo.deferred_embeddings(SOURCE):
        backfill_orphan_chunks.rechunk_articles(repo, HierarchicalChunker(), rows)


def _mention(client, sid):
    with client.get_session() as s:
        entity = s.execute(text(
            "INSERT INTO entities (name, normalized_name, entity_type, mention_count, first_seen_at, last_seen_at) "
            "VALUES ('src60 org', 'src60 org', 'ORGANIZATION', 1, '2026-10-06', '2026-10-06') "
            "RETURNING entity_id")).scalar()
        article_id = s.execute(text("SELECT articles_id FROM articles WHERE sitemap_id = :i"), {"i": sid}).scalar()
        s.execute(text("INSERT INTO entity_mentions (entity_id, sitemap_id, article_id, posted_at, source, event_type) "
                       "VALUES (:e, :sid, :a, '2026-10-06', :src, 'other')"),
                  {"e": entity, "sid": sid, "a": article_id, "src": SOURCE})
        s.commit()
    return entity


def _state(client, sid):
    with client.get_session() as s:
        return s.execute(text(
            "SELECT s.crawl_status, (SELECT count(*) FROM articles a WHERE a.sitemap_id = s.sitemap_id) AS articles, "
            "(SELECT count(*) FROM chunks c WHERE c.sitemap_id = s.sitemap_id) AS chunks, "
            "(SELECT count(*) FROM entity_mentions m WHERE m.sitemap_id = s.sitemap_id) AS mentions "
            "FROM sitemaps s WHERE s.sitemap_id = :i"), {"i": sid}).fetchone()


def _vectors(sid):
    import repair_store_consistency
    from newscrawler.infrastructure.datasource.dataflow.write.faiss import chunk_faiss_data_source as cfd
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    return sum(1 for db in (cfd.VECTOR_DB_NAME_L1, cfd.VECTOR_DB_NAME_L2)
               for d in load_index(db, repair_store_consistency._NoEmbeddings()).docstore._dict.values()
               if d.metadata.get("sitemap_id") == sid)


class TestSettleOutOfScopeLinksLive:
    def test_reader_posts_go_and_the_newsroom_stays(self, client, env, scripts):
        desk = _sitemap(client, "kumparanbisnis")
        reader = _sitemap(client, "tyasafira031")
        pending = _sitemap(client, "halizasalda24", status="pending", article=False)
        settled_long_ago = _sitemap(client, "rudi-yahya", status="rejected_filter", article=False)
        _chunk_and_embed(client)
        entity = _mention(client, reader)
        rows = {sid: _state(client, sid).chunks for sid in (reader, desk)}
        assert _vectors(reader) == rows[reader] > 0 and _vectors(desk) == rows[desk] > 0, "one vector per chunk row"
        desk_before = (_state(client, desk), _vectors(desk))

        assert scripts.settle.apply(SimpleNamespace(source=SOURCE), client=client) == 0

        assert tuple(_state(client, reader)) == ("rejected_filter", 0, 0, 0)
        assert _vectors(reader) == 0
        assert tuple(_state(client, pending)) == ("rejected_filter", 0, 0, 0)
        assert tuple(_state(client, settled_long_ago)) == ("rejected_filter", 0, 0, 0)
        assert (_state(client, desk), _vectors(desk)) == desk_before
        with client.get_session() as s:
            assert s.execute(text("SELECT mention_count FROM entities WHERE entity_id = :e"),
                             {"e": entity}).scalar() == 0, "the counters are recomputed (SYS-20)"

        assert scripts.settle.load(client, SOURCE)[1] == [], "a second run finds nothing"

    def test_the_dry_run_writes_nothing(self, client, env, scripts, monkeypatch, capsys):
        reader = _sitemap(client, "tyasafira031")
        _chunk_and_embed(client)
        before = (_state(client, reader), _vectors(reader))
        monkeypatch.setattr(scripts.settle, "SQLAlchemyClient", lambda: client)
        assert scripts.settle.main(["--source", SOURCE]) == 0
        assert "1 sitemap(s) to settle" in capsys.readouterr().out
        assert (_state(client, reader), _vectors(reader)) == before
