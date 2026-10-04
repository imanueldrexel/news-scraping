"""SYS-73 (#223): scripts/repair_boilerplate_bodies.py --apply against a live PostgreSQL and a real
(temp-directory) FAISS store. The unit tests cannot say whether the three stores stay in step; this
does, in the Done-when's own terms:

  * the stored text of a polluted article is cleaned, a clean article is untouched byte for byte;
  * the old vectors of the repaired articles are gone from NEWS_L1/NEWS_L2 and new ones exist for every
    new chunk row, so no chunk row points at a missing vector and none at an old one;
  * chunk rows hold no boilerplate line any more; the clean article's chunk rows and vectors are the same;
  * an article that had entity mentions loses them and is reset for extraction; counters are recomputed;
  * a second run changes nothing (idempotent); a deadline in the past rewrites but does not re-chunk, and
    `--rechunk-only` finishes it; a running crawl_log row refuses the write; the dry run writes nothing;
  * the run lock is held while it runs and released after.

Uses a temp FAISS directory and a temp backup directory, never the real NEWS_L1/NEWS_L2 or backups/."""
import importlib.util
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "SYS73TEST"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")

POLLUTED_BODY = "\n\n".join([
    "Pemerintah menetapkan target pertumbuhan ekonomi tahun depan sebesar lima persen " + " ".join(f"kata{j}" for j in range(60)),
    "ADVERTISEMENT\nGULIR UNTUK LANJUT BACA",
    "Baca juga: Harga Emas Antam Hari Ini Turun Rp 5.000\nBank Indonesia menahan suku bunga acuan " + " ".join(f"isi{j}" for j in range(60)),
    "Lihat Juga : EDUKASI KEUANGAN Tips Menabung |",
    "Analis memperkirakan rupiah stabil sepanjang pekan " + " ".join(f"data{j}" for j in range(60)),
])
CLEAN_BODY = "\n\n".join(
    f"Berita bersih paragraf {i} " + " ".join(f"bersih{i}{j}" for j in range(70)) for i in range(3))
BOILERPLATE = ("Baca juga", "ADVERTISEMENT", "GULIR UNTUK", "Lihat Juga")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def repair():
    import sys
    sys.path.insert(0, SCRIPTS)
    return _load("repair_boilerplate_bodies_run", "repair_boilerplate_bodies.py")


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
        s.execute(text("DELETE FROM entity_aliases WHERE normalized_alias LIKE 'sys73%'"))
        s.execute(text("DELETE FROM entities WHERE normalized_name LIKE 'sys73%'"))
        s.execute(text(f"DELETE FROM chunks WHERE sitemap_id IN {ids}"), {"s": SOURCE})
        s.execute(text(f"DELETE FROM articles WHERE sitemap_id IN {ids}"), {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.execute(text("DELETE FROM crawl_log WHERE website = :s"), {"s": SOURCE})
        s.commit()


@pytest.fixture
def env(monkeypatch, repair):
    """Temp FAISS, backup and lock paths, and the recount script's backup directory."""
    tmp = tempfile.mkdtemp(prefix="sys73_")
    import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as cfd
    from newscrawler.tools import run_lock
    import sys
    sys.path.insert(0, SCRIPTS)
    import recount_entity_mentions
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L1", f"{tmp}/L1")
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L2", f"{tmp}/L2")
    monkeypatch.setattr(repair, "BACKUP_DIR", f"{tmp}/backups")
    monkeypatch.setattr(recount_entity_mentions, "BACKUP_DIR", f"{tmp}/recount")
    monkeypatch.setattr(run_lock, "LOCK_PATH", f"{tmp}/scheduled_crawl.lock")
    yield SimpleNamespace(tmp=tmp, lock=f"{tmp}/scheduled_crawl.lock")
    shutil.rmtree(tmp, ignore_errors=True)


def _article(client, marker, body, extracted=False):
    with client.get_session() as s:
        sid = s.execute(text(
            "INSERT INTO sitemaps (headline, link, sources, category, posted_at) "
            "VALUES (:h, :l, :s, 'ekonomi', 20260930) RETURNING sitemap_id"),
            {"h": f"{marker} headline", "l": f"https://sys73.test/{uuid.uuid4().hex}", "s": SOURCE}).scalar()
        s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, writer, meta_data, knowledge_extracted) "
                       "VALUES (:sid, :t, '[\"r\"]', '{}', :k)"),
                  {"sid": sid, "t": body, "k": 1 if extracted else 0})
        s.commit()
    return sid


def _mention(client, sid, name):
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
        SQLAlchemyKnowledgeDataSource,
    )
    with client.get_session() as s:
        entity = s.execute(text(
            "INSERT INTO entities (name, normalized_name, entity_type, mention_count, first_seen_at, last_seen_at) "
            "VALUES (:n, :n, 'ORGANIZATION', 1, '2026-09-30', '2026-09-30') RETURNING entity_id"), {"n": name}).scalar()
        article_id = s.execute(text("SELECT articles_id FROM articles WHERE sitemap_id = :i"), {"i": sid}).scalar()
        s.execute(text("INSERT INTO entity_mentions (entity_id, sitemap_id, article_id, posted_at, source, event_type) "
                       "VALUES (:e, :sid, :a, '2026-09-30', :src, 'other')"),
                  {"e": entity, "sid": sid, "a": article_id, "src": SOURCE})
        s.commit()
    return entity


def _build_initial_chunks(client, repair):
    """The state production is in: every article chunked and embedded from its (polluted) text."""
    import sys
    sys.path.insert(0, SCRIPTS)
    import backfill_orphan_chunks
    from newscrawler.core.chunker import HierarchicalChunker
    from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl
    with client.get_session() as s:
        rows = s.execute(backfill_orphan_chunks._FETCH_SQL, {"website": SOURCE}).fetchall()
    repo = DataFlowRepositoryImpl(client)
    with repo.deferred_embeddings(SOURCE):
        backfill_orphan_chunks.rechunk_articles(repo, HierarchicalChunker(), rows)


def _text(client, sid):
    with client.get_session() as s:
        return s.execute(text("SELECT extracted_text FROM articles WHERE sitemap_id = :i"), {"i": sid}).scalar()


def _chunks(client, sid):
    with client.get_session() as s:
        return [dict(r._mapping) for r in s.execute(text(
            "SELECT chunk_id, chunk_level, chunk_index, text_content, embedding_id, chunk_status FROM chunks "
            "WHERE sitemap_id = :i ORDER BY chunk_level, chunk_index"), {"i": sid})]


def _vector_ids(sid):
    """Docstore ids of this sitemap's vectors in both temp indexes."""
    import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as cfd
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    sys_path = SCRIPTS
    import sys
    sys.path.insert(0, sys_path)
    from repair_store_consistency import _NoEmbeddings
    ids = set()
    for db in (cfd.VECTOR_DB_NAME_L1, cfd.VECTOR_DB_NAME_L2):
        store = load_index(db, _NoEmbeddings())
        ids |= {i for i, d in store.docstore._dict.items() if int(d.metadata.get("sitemap_id", -1)) == sid}
    return ids


def _args(**kw):
    base = dict(source=SOURCE, apply=True, rechunk_only=False, block=2, until=None)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def seeded(client, repair, env):
    polluted = _article(client, "polluted", POLLUTED_BODY)
    clean = _article(client, "clean", CLEAN_BODY)
    extracted = _article(client, "extracted", POLLUTED_BODY, extracted=True)
    entity = _mention(client, extracted, "sys73 entity one")
    _build_initial_chunks(client, repair)
    return SimpleNamespace(polluted=polluted, clean=clean, extracted=extracted, entity=entity)


class TestApply:
    def test_the_three_stores_stay_in_step(self, repair, client, env, seeded):
        old_vectors = {k: _vector_ids(getattr(seeded, k)) for k in ("polluted", "clean", "extracted")}
        old_clean_chunks = _chunks(client, seeded.clean)
        assert old_vectors["polluted"] and any("Baca juga" in c["text_content"] or "ADVERTISEMENT" in c["text_content"]
                                               for c in _chunks(client, seeded.polluted)), "the fixture must start polluted"

        assert repair.apply_source(_args(), client=client) == 0

        # stored text
        for key in ("polluted", "extracted"):
            body = _text(client, getattr(seeded, key))
            assert not any(b in body for b in BOILERPLATE), body
            assert "Pemerintah menetapkan target" in body and "Bank Indonesia menahan suku bunga" in body
            assert "Analis memperkirakan rupiah" in body, "the real sentences survive"
        assert _text(client, seeded.clean) == CLEAN_BODY, "a clean article is untouched byte for byte"

        # chunk rows and vectors
        for key in ("polluted", "extracted"):
            sid = getattr(seeded, key)
            chunks = _chunks(client, sid)
            assert chunks and {c["chunk_level"] for c in chunks} == {1, 2}
            assert not any(b in c["text_content"] for c in chunks for b in BOILERPLATE)
            assert all(c["embedding_id"] and c["chunk_status"] != "pending_embedding" for c in chunks)
            new_vectors = _vector_ids(sid)
            assert not (new_vectors & old_vectors[key]), "no old vector survives"
            assert {c["embedding_id"] for c in chunks} == new_vectors, "every chunk row points at a vector that exists, and every vector at a row"
        assert _chunks(client, seeded.clean) == old_clean_chunks, "the clean article's rows are the same"
        assert _vector_ids(seeded.clean) == old_vectors["clean"], "and so are its vectors"

    def test_an_extracted_article_loses_its_mentions_and_is_reset(self, repair, client, env, seeded):
        repair.apply_source(_args(), client=client)
        with client.get_session() as s:
            mentions = s.execute(text("SELECT count(*) FROM entity_mentions WHERE sitemap_id = :i"),
                                 {"i": seeded.extracted}).scalar()
            flags = s.execute(text("SELECT knowledge_extracted, knowledge_extract_attempts FROM articles "
                                   "WHERE sitemap_id = :i"), {"i": seeded.extracted}).fetchone()
            count = s.execute(text("SELECT mention_count FROM entities WHERE entity_id = :e"),
                              {"e": seeded.entity}).scalar()
            polluted_flag = s.execute(text("SELECT knowledge_extracted FROM articles WHERE sitemap_id = :i"),
                                      {"i": seeded.polluted}).scalar()
        assert mentions == 0 and tuple(flags) == (0, 0), "reset for the next extraction"
        assert count == 0, "the entity's counter was recomputed (SYS-20)"
        assert polluted_flag == 0

    def test_a_second_run_changes_nothing(self, repair, client, env, seeded):
        repair.apply_source(_args(), client=client)
        before = {k: (_text(client, getattr(seeded, k)), _chunks(client, getattr(seeded, k)),
                      _vector_ids(getattr(seeded, k))) for k in ("polluted", "clean", "extracted")}
        assert repair.apply_source(_args(), client=client) == 0
        after = {k: (_text(client, getattr(seeded, k)), _chunks(client, getattr(seeded, k)),
                     _vector_ids(getattr(seeded, k))) for k in ("polluted", "clean", "extracted")}
        assert after == before

    def test_the_backup_has_the_old_text_and_the_old_faiss(self, repair, client, env, seeded):
        import json
        repair.apply_source(_args(), client=client)
        (backup,) = [os.path.join(repair.BACKUP_DIR, d) for d in os.listdir(repair.BACKUP_DIR)]
        assert os.path.isdir(os.path.join(backup, "L1")) and os.path.isdir(os.path.join(backup, "L2"))
        dump = json.load(open(os.path.join(backup, "rows.json"), encoding="utf-8"))
        old = {a["sitemap_id"]: a["extracted_text"] for a in dump["articles"]}
        assert old[seeded.polluted] == POLLUTED_BODY and seeded.clean not in old
        assert dump["entity_mentions"] and dump["chunks"]

    def test_a_deadline_in_the_past_rewrites_but_does_not_rechunk_and_rechunk_only_finishes(self, repair, client, env, seeded):
        past = (datetime.now() - timedelta(minutes=1)).strftime("%H:%M")
        assert repair.apply_source(_args(until=past), client=client) == 3
        assert not _chunks(client, seeded.polluted), "stopped before re-chunking: no chunk rows yet"
        assert not any(b in _text(client, seeded.polluted) for b in BOILERPLATE), "the text is already clean"
        assert repair.apply_source(_args(rechunk_only=True), client=client) == 0
        assert _chunks(client, seeded.polluted) and _vector_ids(seeded.polluted)

    @pytest.mark.parametrize("block, saves", [(2, 4), (1, 6)])
    def test_faiss_is_saved_once_per_block_not_once_per_article(self, repair, client, env, seeded, monkeypatch,
                                                                block, saves):
        """2 saves delete the old vectors (one per index), then each block flushes both indexes once.
        Per-article saves would rewrite the 2 GB production index for every article (days)."""
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource,
        )
        calls = []
        original = ChunkFAISSDatasource._atomic_save_local
        monkeypatch.setattr(ChunkFAISSDatasource, "_atomic_save_local",
                            staticmethod(lambda vs, db, encoder=None: (calls.append(db), original(vs, db, encoder=encoder))[1]))
        assert repair.apply_source(_args(block=block), client=client) == 0
        assert len(calls) == saves, calls

    def test_a_started_crawl_refuses_the_write(self, repair, client, env, seeded):
        with client.get_session() as s:
            s.execute(text("INSERT INTO crawl_log (website, task, status, started_at) "
                           "VALUES (:w, 'full_text', 'started', NOW())"), {"w": SOURCE})
            s.commit()
        assert repair.apply_source(_args(), client=client) == 2
        assert _text(client, seeded.polluted) == POLLUTED_BODY and _chunks(client, seeded.polluted)

    def test_the_lock_is_held_while_it_runs_and_released_after(self, repair, client, env, seeded, monkeypatch):
        held = []
        original = repair.rechunk

        def spy(*a, **k):
            held.append(os.path.exists(env.lock))
            return original(*a, **k)
        monkeypatch.setattr(repair, "rechunk", spy)
        repair.apply_source(_args(), client=client)
        assert held == [True] and not os.path.exists(env.lock)

    def test_a_crawl_holding_the_lock_refuses_before_anything_is_touched(self, repair, client, env, seeded):
        from newscrawler.tools.run_lock import RunLock
        with RunLock(path=env.lock, purpose="a crawl"):
            assert repair.main(["--apply", "--source", SOURCE]) == 2
        assert _text(client, seeded.polluted) == POLLUTED_BODY


class TestDryRun:
    def test_it_writes_nothing(self, repair, client, env, seeded, tmp_path):
        before = (_text(client, seeded.polluted), _chunks(client, seeded.polluted), _vector_ids(seeded.polluted))
        assert repair.main(["--source", SOURCE, "--report-dir", str(tmp_path)]) == 0
        assert before == (_text(client, seeded.polluted), _chunks(client, seeded.polluted), _vector_ids(seeded.polluted))
