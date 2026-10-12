"""SYS-105 (#275) / SYS-109 (#283, ADR-008): scripts/rechunk_stale_chunks.py against a live PostgreSQL and
a real (temp-directory) FAISS store. The repair is L2-only:

  * SYS-105 (`--min-words`): an article stored with the old trailing sign-off chunk ("(jon)") loses it;
  * SYS-109 (`--all`): an article stored with the old 450-word chunks gets windows of at most 80 words;
  * in both, the article's L1 row and L1 vector are the same objects as before, and so is its entity
    mention (it points at the L1 chunk); every new L2 row has a vector and no old L2 vector is left;
  * an article whose layout does not change is untouched; a second run finds nothing;
  * a run stopped at its deadline leaves articles without L2, and `--resume` finishes them without a
    new backup;
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
LONG = "\n\n".join([_words("panjang", 200), _words("kedua", 150)])
SHORT = _words("pendek", 60)


@pytest.fixture(scope="module")
def scripts():
    import sys
    sys.path.insert(0, SCRIPTS)
    import rechunk_stale_chunks
    from newscrawler.tools import store_repair
    return SimpleNamespace(rechunk=rechunk_stale_chunks, store_repair=store_repair)


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
    monkeypatch.setattr(scripts.store_repair, "BACKUP_DIR", f"{tmp}/backups")
    yield SimpleNamespace(tmp=tmp, backups=f"{tmp}/backups")
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


def _store_as_production_did(client, monkeypatch, old_merge=False):
    """Chunk and embed every article of SOURCE with the chunk sizes before SYS-109 (80/450/50) and,
    if asked, the trailing behaviour before SYS-105."""
    import backfill_orphan_chunks
    from newscrawler.core import constants
    from newscrawler.core.chunker import HierarchicalChunker
    from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl
    with client.get_session() as s:
        rows = s.execute(backfill_orphan_chunks._FETCH_SQL, {"website": SOURCE}).fetchall()
    with monkeypatch.context() as m:
        m.setattr(constants, "CHUNK_MIN_TOKENS", 80)
        m.setattr(constants, "CHUNK_MAX_TOKENS", 450)
        m.setattr(constants, "CHUNK_OVERLAP_TOKENS", 50)
        if old_merge:
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


def _rows(client, sid, level):
    with client.get_session() as s:
        return s.execute(text("SELECT chunk_id, token_count, embedding_id FROM chunks WHERE sitemap_id = :i "
                              "AND chunk_level = :l ORDER BY chunk_index"), {"i": sid, "l": level}).fetchall()


def _mention_chunk(client, sid):
    with client.get_session() as s:
        return s.execute(text("SELECT chunk_id FROM entity_mentions WHERE sitemap_id = :i"), {"i": sid}).scalar()


def _vector_ids(level, sid):
    import repair_store_consistency
    from newscrawler.infrastructure.datasource.dataflow.write.faiss import chunk_faiss_data_source as cfd
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    db = cfd.VECTOR_DB_NAME_L1 if level == 1 else cfd.VECTOR_DB_NAME_L2
    store = load_index(db, repair_store_consistency._NoEmbeddings())
    return sorted(i for i, d in store.docstore._dict.items() if d.metadata.get("sitemap_id") == sid)


def _snapshot(client, sid):
    """What an L2-only repair must leave alone: the L1 row and vector, and the mention's chunk."""
    return _rows(client, sid, 1), _vector_ids(1, sid), _mention_chunk(client, sid)


def _args(**kw):
    return SimpleNamespace(**dict(dict(source=SOURCE, min_words=15, all=False, resume=False, block=1000, group=50,
                                       until=None), **kw))


def _assert_l2_consistent(client, sid):
    l2 = _rows(client, sid, 2)
    assert all(r.embedding_id for r in l2), "every new L2 row has its vector"
    assert sorted(r.embedding_id for r in l2) == _vector_ids(2, sid), "no old L2 vector is left"
    return l2


class TestRechunkFragmentsLive:
    def test_the_sign_off_chunk_goes_and_l1_and_the_mention_stay(self, client, env, monkeypatch, scripts):
        signed, short = _article(client, SIGNED_OFF), _article(client, SHORT)
        _store_as_production_did(client, monkeypatch, old_merge=True)
        _mention_on_l1(client, signed)
        assert [r.token_count for r in _rows(client, signed, 2)] == [120, 100, 1], "the old layout"
        before, short_before = _snapshot(client, signed), _rows(client, short, 2)

        assert scripts.rechunk.apply(_args(), client=client) == 0

        l2 = _assert_l2_consistent(client, signed)
        assert min(r.token_count for r in l2) >= 10 and max(r.token_count for r in l2) <= 80
        assert _snapshot(client, signed) == before, "L1 row, L1 vector and mention untouched"
        assert _rows(client, short, 2) == short_before, "an article without a fragment is not a target"
        assert scripts.rechunk.load_targets(client, SOURCE, 15) == {}, "a second run finds nothing"


class TestRechunkToTheEncoderWindowLive:
    def test_all_turns_long_chunks_into_windows_and_keeps_l1(self, client, env, monkeypatch, scripts):
        long_, short = _article(client, LONG), _article(client, SHORT)
        _store_as_production_did(client, monkeypatch)
        _mention_on_l1(client, long_)
        assert [r.token_count for r in _rows(client, long_, 2)] == [200, 150], "the old 450-word layout"
        before, short_before = _snapshot(client, long_), _rows(client, short, 2)

        assert scripts.rechunk.apply(_args(all=True), client=client) == 0

        l2 = _assert_l2_consistent(client, long_)
        assert max(r.token_count for r in l2) <= 80 and len(l2) >= 5
        assert _snapshot(client, long_) == before, "L1 row, L1 vector and mention untouched"
        assert _rows(client, short, 2) == short_before, "a 60-word article keeps its one chunk"
        assert scripts.rechunk.load_targets(client, SOURCE, 15, all_articles=True) == {}
        backups = os.listdir(env.backups)
        assert len(backups) == 1 and backups[0].startswith("sys109_SYS105TEST_")
        with open(os.path.join(env.backups, backups[0], "l2_rows.jsonl"), encoding="utf-8") as f:
            assert sum(1 for _ in f) == 2, "the two deleted L2 rows are in the backup"

    def test_a_stopped_run_is_finished_by_resume_without_a_new_backup(self, client, env, monkeypatch, scripts):
        import functools
        from datetime import datetime, timedelta
        long_ = _article(client, LONG)
        _store_as_production_did(client, monkeypatch)
        before = _snapshot(client, long_)
        rechunk = scripts.rechunk.rechunk
        monkeypatch.setattr(scripts.rechunk, "rechunk", functools.partial(rechunk, now=lambda: datetime.max))
        later = (datetime.now() + timedelta(hours=2)).strftime("%H:%M")
        assert scripts.rechunk.apply(_args(all=True, until=later), client=client) == 3
        monkeypatch.setattr(scripts.rechunk, "rechunk", rechunk)
        assert _rows(client, long_, 2) == [], "stopped after the deletes, before the re-chunk"
        assert scripts.rechunk.apply(_args(resume=True), client=client) == 0
        assert max(r.token_count for r in _assert_l2_consistent(client, long_)) <= 80
        assert _snapshot(client, long_) == before
        assert len(os.listdir(env.backups)) == 1, "--resume takes no backup"

    def test_a_deadline_too_close_refuses_before_the_backup_and_the_deletes(self, client, env, monkeypatch, scripts):
        """SYS-111 (#287): `--until` under MIN_RUN_MINUTES away is exit 2 with nothing touched. The
        2026-10-08 run read 06:15 as already past, deleted 358,398 L2 rows, then stopped (exit 3)."""
        from datetime import datetime, timedelta
        long_ = _article(client, LONG)
        _store_as_production_did(client, monkeypatch)
        before = _rows(client, long_, 2), _vector_ids(2, long_)
        soon = (datetime.now() + timedelta(minutes=scripts.store_repair.MIN_RUN_MINUTES - 5)).strftime("%H:%M")
        assert scripts.rechunk.apply(_args(all=True, until=soon), client=client) == 2
        assert (_rows(client, long_, 2), _vector_ids(2, long_)) == before
        assert not os.path.isdir(env.backups) or os.listdir(env.backups) == [], "no backup taken"

    def test_a_time_already_past_today_is_tomorrow_and_the_run_finishes(self, client, env, monkeypatch, scripts):
        """The 2026-10-08 incident: `--until 06:15` at 20:04. A minute ago means tomorrow, so it runs to the end."""
        from datetime import datetime, timedelta
        long_ = _article(client, LONG)
        _store_as_production_did(client, monkeypatch)
        a_minute_ago = (datetime.now() - timedelta(minutes=1)).strftime("%H:%M")
        assert scripts.rechunk.apply(_args(all=True, until=a_minute_ago), client=client) == 0
        assert max(r.token_count for r in _assert_l2_consistent(client, long_)) <= 80

    def test_the_dry_run_writes_nothing(self, client, env, monkeypatch, scripts, capsys):
        long_ = _article(client, LONG)
        _store_as_production_did(client, monkeypatch)
        before = _rows(client, long_, 2)
        monkeypatch.setattr(scripts.rechunk, "SQLAlchemyClient", lambda: client)
        assert scripts.rechunk.main(["--source", SOURCE, "--all"]) == 0
        out = capsys.readouterr().out
        assert "SYS105TEST" in out and "2 -> " in out
        assert _rows(client, long_, 2) == before

    def test_a_running_crawl_refuses_the_write(self, client, env, monkeypatch, scripts):
        long_ = _article(client, LONG)
        _store_as_production_did(client, monkeypatch)
        before = _rows(client, long_, 2)
        with client.get_session() as s:
            s.execute(text("INSERT INTO crawl_log (website, task, status, started_at) "
                           "VALUES (:s, 'full_text', 'started', NOW())"), {"s": SOURCE})
            s.commit()
        assert scripts.rechunk.apply(_args(all=True), client=client) == 2
        assert _rows(client, long_, 2) == before
