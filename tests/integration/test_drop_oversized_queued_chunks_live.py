"""SYS-137 (#316): scripts/drop_oversized_queued_chunks.py against a live PostgreSQL and a real
(temp-directory) FAISS store, in the production shape: chunks written by a 450-word chunker
(VIVA's June backlog), then

  * a queued sitemap (no article) loses its chunk rows and vectors, both levels;
  * so does one that an earlier run left with L1 only (the 2026-10-12 first run's state);
  * a saved article with the same old chunks is untouched (rechunk_stale_chunks.py owns it);
  * a queued sitemap whose L2 rows fit the limit is untouched;
  * the crawl's own save then writes that sitemap's chunks fresh, every L2 row within CHUNK_MAX_TOKENS;
  * a second run finds nothing; the dry run writes nothing;
  * DBT-69 (#330): `--source` leaves another source's queued stale chunks alone, and a queued L2 row
    of exactly CHUNK_MAX_TOKENS words is not a target (81 words is).

Uses temp FAISS, backup and lock paths, never the real NEWS_L1/NEWS_L2 or backups/."""
import os
import shutil
import tempfile
import uuid
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "VIVA"
OTHER = "JPNN"      # a second source for the --source scope (DBT-69)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")
LONG_BODY = "\n\n".join(" ".join(f"kata{i}x{j}" for j in range(200)) for i in range(2))   # 2 x 200 words
SHORT_BODY = " ".join(f"pendek{j}" for j in range(60))


@pytest.fixture(scope="module")
def scripts():
    import sys
    sys.path.insert(0, SCRIPTS)
    import drop_oversized_queued_chunks
    import repair_boilerplate_bodies
    return SimpleNamespace(drop=drop_oversized_queued_chunks, sys73=repair_boilerplate_bodies)


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            assert s.execute(text("SELECT current_database()")).scalar() == "newsaggregator_test"
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    with c.get_session() as s:
        for source in (SOURCE, OTHER):
            ids = "(SELECT sitemap_id FROM sitemaps WHERE sources = :s)"
            s.execute(text(f"DELETE FROM chunks WHERE sitemap_id IN {ids}"), {"s": source})
            s.execute(text(f"DELETE FROM articles WHERE sitemap_id IN {ids}"), {"s": source})
            s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": source})
        s.commit()


@pytest.fixture
def env(monkeypatch, scripts):
    tmp = tempfile.mkdtemp(prefix="sys137_")
    import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as cfd
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L1", f"{tmp}/L1")
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L2", f"{tmp}/L2")
    monkeypatch.setattr(scripts.sys73, "BACKUP_DIR", f"{tmp}/backups")
    yield SimpleNamespace(tmp=tmp)
    shutil.rmtree(tmp, ignore_errors=True)


def _sitemap(client, body, status, source=SOURCE):
    with client.get_session() as s:
        sid = s.execute(text(
            "INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
            "VALUES ('h', :l, :s, 'berita', 20260602, :st) RETURNING sitemap_id"),
            {"l": f"https://drop-sys137.test/{source}/{uuid.uuid4().hex}", "s": source, "st": status}).scalar()
        s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, writer, meta_data, knowledge_extracted) "
                       "VALUES (:sid, :t, '[\"r\"]', '{}', 0)"), {"sid": sid, "t": body})
        s.commit()
    return sid


def _chunk_like_june(client, source=SOURCE):
    """Chunk and embed every article of `source` with a 450-word window, the chunker of 2026-06-02."""
    import backfill_orphan_chunks
    from newscrawler.core.chunker import HierarchicalChunker
    from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl
    with client.get_session() as s:
        rows = s.execute(backfill_orphan_chunks._FETCH_SQL, {"website": source}).fetchall()
    repo = DataFlowRepositoryImpl(client)
    with repo.deferred_embeddings(source):
        backfill_orphan_chunks.rechunk_articles(repo, HierarchicalChunker(max_tokens=450), rows)
    return repo


def _unsave(client, sid):
    """The queued shape: chunks from June, no article row yet."""
    with client.get_session() as s:
        s.execute(text("DELETE FROM articles WHERE sitemap_id = :i"), {"i": sid})
        s.commit()


def _rows(client, sid, level):
    with client.get_session() as s:
        return s.execute(text("SELECT token_count FROM chunks WHERE sitemap_id = :i AND chunk_level = :l "
                              "ORDER BY chunk_index"), {"i": sid, "l": level}).scalars().all()


def _vectors(sid, level):
    import repair_store_consistency
    from newscrawler.infrastructure.datasource.dataflow.write.faiss import chunk_faiss_data_source as cfd
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    db = cfd.VECTOR_DB_NAME_L1 if level == 1 else cfd.VECTOR_DB_NAME_L2
    return sum(1 for d in load_index(db, repair_store_consistency._NoEmbeddings()).docstore._dict.values()
               if d.metadata.get("sitemap_id") == sid)


class TestDropOversizedQueuedChunksLive:
    def test_queued_l2_goes_l1_and_articles_stay_and_the_crawl_rechunks_it(self, client, env, scripts):
        queued = _sitemap(client, LONG_BODY, "pending")
        saved = _sitemap(client, LONG_BODY, "saved")
        fits = _sitemap(client, SHORT_BODY, "pending")
        _chunk_like_june(client)
        _unsave(client, queued)
        _unsave(client, fits)
        assert max(_rows(client, queued, 2)) > 80 and max(_rows(client, saved, 2)) > 80
        assert max(_rows(client, fits, 2)) <= 80
        before_saved = (_rows(client, saved, 1), _rows(client, saved, 2), _vectors(saved, 2))
        before_fits = (_rows(client, fits, 2), _vectors(fits, 2))
        assert _vectors(queued, 1) == 1

        assert scripts.drop.apply(SimpleNamespace(source=SOURCE), client=client) == 0

        assert _rows(client, queued, 2) == [] and _vectors(queued, 2) == 0
        assert _rows(client, queued, 1) == [] and _vectors(queued, 1) == 0, "both levels go"
        assert (_rows(client, saved, 1), _rows(client, saved, 2), _vectors(saved, 2)) == before_saved
        assert (_rows(client, fits, 2), _vectors(fits, 2)) == before_fits
        assert scripts.drop.load(client, SOURCE) == [], "a second run finds nothing"

        # The crawl reaches the sitemap: its article is saved through the normal path, and its L2
        # level, now missing, is written fresh by today's chunker.
        from newscrawler.core.chunker import HierarchicalChunker
        from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl
        repo = DataFlowRepositoryImpl(client)
        news = NewsDetailsDTO(sitemap_id=queued, extracted_text=LONG_BODY.split("\n\n"), reporter=["r"],
                              meta_data={"title": "h"})
        with repo.deferred_embeddings(SOURCE):
            assert repo.save_chunk_data(HierarchicalChunker().chunk(news)) == [queued]
        l2 = _rows(client, queued, 2)
        assert l2 and max(l2) <= 80 and _vectors(queued, 2) == len(l2)
        assert len(_rows(client, queued, 1)) == 1 and _vectors(queued, 1) == 1

    def test_a_queued_sitemap_left_with_l1_only_is_a_target(self, client, env, scripts):
        """The first production run dropped L2 only; what it left is finished by the next run."""
        half = _sitemap(client, LONG_BODY, "pending")
        _chunk_like_june(client)
        _unsave(client, half)
        with client.get_session() as s:
            s.execute(text("DELETE FROM chunks WHERE sitemap_id = :i AND chunk_level = 2"), {"i": half})
            s.commit()
        assert [t.sitemap_id for t in scripts.drop.load(client, SOURCE)] == [half]

        assert scripts.drop.apply(SimpleNamespace(source=SOURCE), client=client) == 0

        assert _rows(client, half, 1) == [] and _vectors(half, 1) == 0
        assert scripts.drop.load(client, SOURCE) == []

    def test_the_dry_run_writes_nothing(self, client, env, scripts, monkeypatch, capsys):
        queued = _sitemap(client, LONG_BODY, "pending")
        _chunk_like_june(client)
        _unsave(client, queued)
        before = (_rows(client, queued, 2), _vectors(queued, 2))
        monkeypatch.setattr(scripts.drop, "SQLAlchemyClient", lambda: client)
        assert scripts.drop.main(["--source", SOURCE]) == 0
        assert "1 queued sitemap(s) with stale chunks" in capsys.readouterr().out
        assert (_rows(client, queued, 2), _vectors(queued, 2)) == before

    def test_source_scope_leaves_another_sources_queued_chunks_alone(self, client, env, scripts):
        """DBT-69: `--source VIVA --apply` must not drop JPNN's queued stale chunks (QA mutant
        qa1012b_drop_ignores_source)."""
        mine = _sitemap(client, LONG_BODY, "pending")
        theirs = _sitemap(client, LONG_BODY, "pending", source=OTHER)
        _chunk_like_june(client)
        _chunk_like_june(client, OTHER)
        _unsave(client, mine)
        _unsave(client, theirs)
        before = (_rows(client, theirs, 1), _rows(client, theirs, 2), _vectors(theirs, 1), _vectors(theirs, 2))
        assert [t.sitemap_id for t in scripts.drop.load(client, OTHER)] == [theirs]

        assert scripts.drop.apply(SimpleNamespace(source=SOURCE), client=client) == 0

        assert _rows(client, mine, 2) == [] and _vectors(mine, 2) == 0
        assert (_rows(client, theirs, 1), _rows(client, theirs, 2), _vectors(theirs, 1), _vectors(theirs, 2)) == before

    def test_a_queued_l2_row_at_the_limit_is_not_a_target(self, client, env, scripts):
        """DBT-69: SYS-109 allows an L2 row of exactly CHUNK_MAX_TOKENS words; one word more is stale
        (QA mutant qa1012b_drop_at_the_cap)."""
        from newscrawler.core.constants import CHUNK_MAX_TOKENS
        at, over = _sitemap(client, "x", "pending"), _sitemap(client, "x", "pending")
        with client.get_session() as s:
            for sid, words in ((at, CHUNK_MAX_TOKENS), (over, CHUNK_MAX_TOKENS + 1)):
                for level in (1, 2):
                    s.execute(text(
                        "INSERT INTO chunks (sitemap_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                        "is_last_chunk, text_content, chunk_status, token_count) "
                        "VALUES (:sid, :lv, 0, 1, true, true, 'teks', 'embedded', :n)"),
                        {"sid": sid, "lv": level, "n": words})
            s.commit()
        _unsave(client, at)
        _unsave(client, over)
        assert [t.sitemap_id for t in scripts.drop.load(client, SOURCE)] == [over]
