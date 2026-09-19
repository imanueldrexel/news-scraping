"""
DBT-24 (#79) / DBT-19 (#69): scripts/backfill_orphan_chunks.py against a live
PostgreSQL and a real (temp-directory) FAISS store.

backfill_chunks.py was deleted under DBT-24 because its own test module seeded
json.dumps(paragraphs) -- a format the live pipeline stopped writing at SYS-18 --
and so proved nothing about production, where it selected every article. This
module is the test that ticket asked for, pointed at the tool that survives:
  * the article is seeded in the PRODUCTION extracted_text format (prose joined
    with "\\n\\n", exactly what save_newsdetails writes),
  * an article that already has chunks at both levels is NOT selected (the
    script is a no-op on it; a second run writes nothing),
  * an article missing only one level IS selected (SYS-25's level-aware WHERE --
    the DBT-19 mutation survivor: no test used to exercise this clause),
  * every vector it writes lands in NEWS_L1/NEWS_L2 (not a side index) and is
    found by ChunkFAISSDatasource.search_l2().

Uses a temp FAISS directory, never the real NEWS_L1/NEWS_L2.
"""
import importlib.util
import os
import shutil
import tempfile
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "DBT24TEST"
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "backfill_orphan_chunks.py",
)


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("backfill_orphan_chunks_run", _SCRIPT)
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
        s.execute(text("DELETE FROM chunks WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources = :s)"),
                  {"s": SOURCE})
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources = :s)"),
                  {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


@pytest.fixture
def temp_faiss_dirs(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="dbt24_faiss_")
    import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as mod
    monkeypatch.setattr(mod, "VECTOR_DB_NAME_L1", f"{tmp}/L1")
    monkeypatch.setattr(mod, "VECTOR_DB_NAME_L2", f"{tmp}/L2")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def _prose(marker, paragraphs=3, words=100):
    """Production extracted_text: paragraphs joined with a blank line (SYS-18)."""
    return "\n\n".join(f"{marker} paragraf {i} " + " ".join(f"kata{i}{j}" for j in range(words))
                       for i in range(paragraphs))


def _seed_article(client, marker, extracted_text=None):
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, category, posted_at) "
                 "VALUES (:h, :l, :s, 'ekonomi', 20260918) RETURNING sitemap_id"),
            {"h": f"{marker} headline", "l": f"https://dbt24.test/{uuid.uuid4().hex}", "s": SOURCE},
        ).scalar()
        s.execute(
            text("INSERT INTO articles (sitemap_id, extracted_text, writer, meta_data) "
                 "VALUES (:sid, :t, '[\"r\"]', '{}')"),
            {"sid": sid, "t": extracted_text if extracted_text is not None else _prose(marker)},
        )
        s.commit()
    return sid


def _seed_chunk(client, sid, level, index=0, total=1):
    with client.get_session() as s:
        s.execute(
            text("INSERT INTO chunks (sitemap_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                 "is_last_chunk, text_content, token_count, embedding_id, chunk_status) "
                 "VALUES (:sid, :lvl, :idx, :tot, :first, :last, 'seeded', 1, :eid, 'embedded')"),
            {"sid": sid, "lvl": level, "idx": index, "tot": total, "first": index == 0,
             "last": index == total - 1, "eid": f"seeded-{uuid.uuid4().hex}"},
        )
        s.commit()


def _chunk_levels(client, sid):
    with client.get_session() as s:
        rows = s.execute(text("SELECT chunk_level, COUNT(*) FROM chunks WHERE sitemap_id = :sid GROUP BY 1 ORDER BY 1"),
                         {"sid": sid}).fetchall()
    return {r[0]: r[1] for r in rows}


class TestSelection:
    def test_dry_run_selects_only_articles_missing_a_level(self, script, client):
        orphan = _seed_article(client, "DBT24 orphan")
        complete = _seed_article(client, "DBT24 complete")
        _seed_chunk(client, complete, level=1)
        _seed_chunk(client, complete, level=2)
        missing_l2 = _seed_article(client, "DBT24 missingL2")
        _seed_chunk(client, missing_l2, level=1)

        summary = script.main(["--dry-run", "--website", SOURCE])

        assert summary["selected"] == 2, summary
        assert _chunk_levels(client, orphan) == {}, "dry-run must not write"
        assert _chunk_levels(client, missing_l2) == {1: 1}, "dry-run must not write"

    def test_already_chunked_article_is_a_no_op(self, script, client, temp_faiss_dirs):
        """DBT-24's Done-when: real mode against a live-style chunked article writes
        nothing and exits cleanly (the deleted script crashed here on
        chunks_sitemap_level_index_uq after loading the model)."""
        complete = _seed_article(client, "DBT24 complete2")
        _seed_chunk(client, complete, level=1)
        _seed_chunk(client, complete, level=2)

        summary = script.main(["--website", SOURCE])

        assert summary == {"selected": 0, "repaired": 0, "empty": 0, "failed": 0}
        assert _chunk_levels(client, complete) == {1: 1, 2: 1}
        assert not os.path.exists(os.path.join(temp_faiss_dirs, "L2", "index.faiss")), "nothing embedded"


class TestRepair:
    def test_prose_article_gets_l1_and_l2_chunks_findable_by_search_l2(self, script, client, temp_faiss_dirs):
        marker = f"DBT24 unik{uuid.uuid4().hex[:8]}"
        sid = _seed_article(client, marker)

        summary = script.main(["--website", SOURCE])

        assert summary == {"selected": 1, "repaired": 1, "empty": 0, "failed": 0}
        levels = _chunk_levels(client, sid)
        assert levels.get(1) == 1, levels
        # Prose must be split on "\n\n" -- three ~100-word paragraphs give more than
        # one L2 chunk; treating the prose as one paragraph (the deleted script's
        # behaviour) would collapse it.
        assert levels.get(2, 0) >= 2, levels

        # The vectors are in the real store the pipeline reads, and search_l2 finds them.
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource,
        )
        faiss_ds = ChunkFAISSDatasource()
        hits = faiss_ds.search_l2(f"{marker} paragraf 1", k=5)
        assert any(h["sitemap_id"] == sid for h in hits), hits

        with client.get_session() as s:
            rows = s.execute(text("SELECT chunk_level, embedding_id FROM chunks WHERE sitemap_id = :sid"),
                             {"sid": sid}).fetchall()
        l2_docstore_ids = set(faiss_ds.vs_l2.docstore._dict)
        l1_docstore_ids = set(faiss_ds.vs_l1.docstore._dict)
        for level, eid in rows:
            assert eid in (l1_docstore_ids if level == 1 else l2_docstore_ids), (level, eid)

    def test_second_run_is_a_no_op(self, script, client, temp_faiss_dirs):
        sid = _seed_article(client, "DBT24 twice")

        first = script.main(["--website", SOURCE])
        levels_after_first = _chunk_levels(client, sid)
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource,
        )
        vectors_after_first = ChunkFAISSDatasource().vs_l2.index.ntotal

        second = script.main(["--website", SOURCE])

        assert first["repaired"] == 1
        assert second == {"selected": 0, "repaired": 0, "empty": 0, "failed": 0}
        assert _chunk_levels(client, sid) == levels_after_first
        assert ChunkFAISSDatasource().vs_l2.index.ntotal == vectors_after_first

    def test_article_missing_only_l2_gets_only_l2(self, script, client, temp_faiss_dirs):
        """SYS-25's level-aware selection + save_chunk_data's (sitemap_id, level)
        dedup: the existing L1 row is kept, only L2 is written."""
        sid = _seed_article(client, "DBT24 onlyL2")
        _seed_chunk(client, sid, level=1)

        summary = script.main(["--website", SOURCE])

        assert summary["selected"] == 1 and summary["repaired"] == 1
        levels = _chunk_levels(client, sid)
        assert levels[1] == 1
        assert levels.get(2, 0) >= 1
        with client.get_session() as s:
            l1_eid = s.execute(text("SELECT embedding_id FROM chunks WHERE sitemap_id = :sid AND chunk_level = 1"),
                               {"sid": sid}).scalar()
        assert l1_eid.startswith("seeded-"), "the pre-existing L1 row must be untouched"

    def test_empty_prose_is_skipped_not_failed(self, script, client, temp_faiss_dirs):
        sid = _seed_article(client, "DBT24 empty", extracted_text="")

        summary = script.main(["--website", SOURCE])

        assert summary == {"selected": 1, "repaired": 0, "empty": 1, "failed": 0}
        assert _chunk_levels(client, sid) == {}
