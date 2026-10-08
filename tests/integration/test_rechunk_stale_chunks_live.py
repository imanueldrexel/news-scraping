"""SYS-105 (#275): scripts/rechunk_stale_chunks.py against a live PostgreSQL and a real (temp-directory)
FAISS store, in the Done-when's terms:

  * an article stored with the old chunker's trailing sign-off chunk ("(jon)") is re-chunked: no L2
    chunk under 10 words is left, and every new chunk row has a vector while the old ones are gone;
  * its entity mention is kept and points at the new L1 chunk (the text did not change: nothing is
    re-extracted);
  * an article without a fragment is untouched (same chunk rows); a second run finds nothing;
  * the dry run writes nothing; a running crawl_log row refuses the write.

Uses temp FAISS, backup and lock paths, never the real NEWS_L1/NEWS_L2 or backups/."""
import os
import shutil
import tempfile
import uuid
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "SYS105TEST"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")


def _words(prefix, n):
    return " ".join(f"{prefix}{i}" for i in range(n))


SIGNED_OFF = "\n\n".join([_words("pembuka", 120), _words("isi", 100), "(jon)"])
CLEAN = "\n\n".join([_words("bersih", 120), _words("lanjut", 100)])


@pytest.fixture(scope="module")
def scripts():
    import sys
    sys.path.insert(0, SCRIPTS)
    import rechunk_stale_chunks
    import repair_boilerplate_bodies
    return SimpleNamespace(rechunk=rechunk_stale_chunks, sys73=repair_boilerplate_bodies)


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
        s.execute(text("DELETE FROM entities WHERE normalized_name LIKE 'sys105%'"))
        s.execute(text(f"DELETE FROM chunks WHERE sitemap_id IN {ids}"), {"s": SOURCE})
        s.execute(text(f"DELETE FROM articles WHERE sitemap_id IN {ids}"), {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.execute(text("DELETE FROM crawl_log WHERE website = :s"), {"s": SOURCE})
        s.commit()


@pytest.fixture
def env(monkeypatch, scripts):
    tmp = tempfile.mkdtemp(prefix="sys105_")
    import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as cfd
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L1", f"{tmp}/L1")
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L2", f"{tmp}/L2")
    monkeypatch.setattr(scripts.sys73, "BACKUP_DIR", f"{tmp}/backups")
    yield SimpleNamespace(tmp=tmp)
    shutil.rmtree(tmp, ignore_errors=True)


def _article(client, body):
    with client.get_session() as s:
        sid = s.execute(text(
            "INSERT INTO sitemaps (headline, link, sources, category, posted_at) "
            "VALUES ('h', :l, :s, 'ekonomi', 20260930) RETURNING sitemap_id"),
            {"l": f"https://sys105.test/{uuid.uuid4().hex}", "s": SOURCE}).scalar()
        s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, writer, meta_data, knowledge_extracted) "
                       "VALUES (:sid, :t, '[\"r\"]', '{}', 1)"), {"sid": sid, "t": body})
        s.commit()
    return sid


def _old_merge_short(self, paragraphs):
    """The chunker before SYS-105: the last buffer kept as its own chunk, whatever its length."""
    result, buf = [], ""
    for para in paragraphs:
        if buf and len(buf.split()) < self.min_tokens:
            buf = buf + " " + para
        else:
            if buf:
                result.append(buf)
            buf = para
    if buf:
        result.append(buf)
    return result or paragraphs


def _store_as_production_did(client, monkeypatch, scripts):
    import backfill_orphan_chunks
    from newscrawler.core.chunker import HierarchicalChunker
    from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl
    with client.get_session() as s:
        rows = s.execute(backfill_orphan_chunks._FETCH_SQL, {"website": SOURCE}).fetchall()
    with monkeypatch.context() as m:
        m.setattr(HierarchicalChunker, "_merge_short", _old_merge_short)
        repo = DataFlowRepositoryImpl(client)
        with repo.deferred_embeddings(SOURCE):
            backfill_orphan_chunks.rechunk_articles(repo, HierarchicalChunker(), rows)


def _mention_on_l1(client, sid):
    with client.get_session() as s:
        entity = s.execute(text(
            "INSERT INTO entities (name, normalized_name, entity_type, mention_count, first_seen_at, last_seen_at) "
            "VALUES ('sys105 org', 'sys105 org', 'ORGANIZATION', 1, '2026-09-30', '2026-09-30') "
            "RETURNING entity_id")).scalar()
        article_id, l1 = s.execute(text(
            "SELECT a.articles_id, c.chunk_id FROM articles a JOIN chunks c ON c.sitemap_id = a.sitemap_id "
            "AND c.chunk_level = 1 WHERE a.sitemap_id = :i"), {"i": sid}).fetchone()
        s.execute(text("INSERT INTO entity_mentions (entity_id, sitemap_id, article_id, chunk_id, posted_at, source, "
                       "event_type) VALUES (:e, :sid, :a, :c, '2026-09-30', :src, 'other')"),
                  {"e": entity, "sid": sid, "a": article_id, "c": l1, "src": SOURCE})
        s.commit()


def _l2(client, sid):
    with client.get_session() as s:
        return s.execute(text("SELECT chunk_id, token_count, embedding_id FROM chunks WHERE sitemap_id = :i "
                              "AND chunk_level = 2 ORDER BY chunk_index"), {"i": sid}).fetchall()


def _vector_texts(sid):
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
        VECTOR_DB_NAME_L2,
    )
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    import repair_store_consistency
    store = load_index(VECTOR_DB_NAME_L2, repair_store_consistency._NoEmbeddings())
    return sorted(d.page_content.split()[-1] for d in store.docstore._dict.values() if d.metadata.get("sitemap_id") == sid)


def _args(**kw):
    return SimpleNamespace(**dict(dict(source=SOURCE, min_words=15, block=1000, until=None), **kw))


class TestRechunkStaleChunksLive:
    def test_the_sign_off_chunk_is_merged_and_everything_else_is_kept(self, client, env, monkeypatch, scripts):
        signed, clean = _article(client, SIGNED_OFF), _article(client, CLEAN)
        _store_as_production_did(client, monkeypatch, scripts)
        _mention_on_l1(client, signed)
        assert [r.token_count for r in _l2(client, signed)] == [120, 100, 1], "the old layout, as in production"
        clean_before = _l2(client, clean)

        assert scripts.rechunk.apply(_args(), client=client) == 0

        after = _l2(client, signed)
        assert [r.token_count for r in after] == [120, 101]
        assert all(r.embedding_id for r in after), "every new chunk row has its vector"
        assert _vector_texts(signed) == sorted(["pembuka119", "(jon)"]), "old vectors gone, new ones present"
        with client.get_session() as s:
            mention = s.execute(text("SELECT m.chunk_id, c.chunk_level, a.knowledge_extracted FROM entity_mentions m "
                                     "JOIN chunks c ON c.chunk_id = m.chunk_id JOIN articles a "
                                     "ON a.sitemap_id = m.sitemap_id WHERE m.sitemap_id = :i"), {"i": signed}).fetchone()
        assert mention is not None and mention.chunk_level == 1, "the mention points at the new L1 chunk"
        assert mention.knowledge_extracted == 1, "nothing is re-extracted"
        assert _l2(client, clean) == clean_before, "an article without a fragment is untouched"

        assert scripts.rechunk.load_targets(client, SOURCE, 15)[0] == {}, "a second run finds nothing"

    def test_the_dry_run_writes_nothing(self, client, env, monkeypatch, scripts, capsys):
        signed = _article(client, SIGNED_OFF)
        _store_as_production_did(client, monkeypatch, scripts)
        before = _l2(client, signed)
        monkeypatch.setattr(scripts.rechunk, "SQLAlchemyClient", lambda: client)
        assert scripts.rechunk.main(["--source", SOURCE]) == 0
        assert "SYS105TEST" in capsys.readouterr().out
        assert _l2(client, signed) == before

    def test_a_running_crawl_refuses_the_write(self, client, env, monkeypatch, scripts):
        signed = _article(client, SIGNED_OFF)
        _store_as_production_did(client, monkeypatch, scripts)
        before = _l2(client, signed)
        with client.get_session() as s:
            s.execute(text("INSERT INTO crawl_log (website, task, status, started_at) "
                           "VALUES (:s, 'full_text', 'started', NOW())"), {"s": SOURCE})
            s.commit()
        assert scripts.rechunk.apply(_args(), client=client) == 2
        assert _l2(client, signed) == before
