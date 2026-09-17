"""
SYS-17 against a live PostgreSQL and a real (temp-directory) FAISS index: reproduces
the exact production bug -- chunks embedded into FAISS with zero matching rows in the
`chunks` table -- and confirms save_chunk_data now repairs it: the SQL rows get
inserted using the *same* embedding_ids FAISS already has (no duplicate vectors),
instead of being permanently skipped because FAISS reported "already embedded".

Uses a temp FAISS directory (not the real NEWS_L1/NEWS_L2), so this never touches
production vector data.
"""
import shutil
import tempfile

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    return c


@pytest.fixture
def temp_faiss_dirs(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="sys17_faiss_")
    l1 = f"{tmp}/L1"
    l2 = f"{tmp}/L2"
    import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as mod
    monkeypatch.setattr(mod, "VECTOR_DB_NAME_L1", l1)
    monkeypatch.setattr(mod, "VECTOR_DB_NAME_L2", l2)
    yield l1, l2
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def sitemap_id(client):
    with client.get_session() as s:
        row = s.execute(
            text(
                "INSERT INTO sitemaps (headline, link, sources, posted_at) "
                "VALUES ('t', 'https://x/SYS-17-orphan-repair', 'TEST', 20260916) "
                "RETURNING sitemap_id"
            )
        ).fetchone()
        s.commit()
    sm_id = row.sitemap_id
    yield sm_id
    with client.get_session() as s:
        s.execute(text("DELETE FROM chunks WHERE sitemap_id = :id"), {"id": sm_id})
        s.execute(text("DELETE FROM sitemaps WHERE sitemap_id = :id"), {"id": sm_id})
        s.commit()


def _make_chunk(sitemap_id, level, index, text_content, chunk_total=1):
    from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
    return ChunkDTO(
        sitemap_id=sitemap_id, chunk_level=level, chunk_index=index, chunk_total=chunk_total,
        is_first_chunk=(index == 0), is_last_chunk=(index == chunk_total - 1),
        text_content=text_content, token_count=len(text_content.split()),
        title="Test title", source="TEST", category="finansial", posted_at=20260916,
    )


class TestOrphanFaissVectorsAreRepairedOnRetry:
    def test_faiss_only_sitemap_gets_its_chunks_row_without_duplicating_the_vector(
        self, client, temp_faiss_dirs, sitemap_id
    ):
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource,
        )
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
            SQLAlchemyChunkDataSource,
        )
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
            DataFlowRepositoryImpl,
        )

        faiss_ds = ChunkFAISSDatasource()
        chunk = _make_chunk(sitemap_id, level=1, index=0, text_content="Berita ekonomi tentang suku bunga.")

        # --- Simulate the production bug: embed into FAISS, then the SQL insert
        # never happens (crash / skipped) ---
        embedded = faiss_ds.save([chunk])
        assert embedded[0].embedding_id is not None
        original_embedding_id = embedded[0].embedding_id

        with client.get_session() as s:
            count = s.execute(
                text("SELECT COUNT(*) FROM chunks WHERE sitemap_id = :id"), {"id": sitemap_id}
            ).scalar()
        assert count == 0, "reproducing the bug precondition: FAISS has it, SQL does not"

        # --- Now go through the real (fixed) repository layer ---
        repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
        repo.chunk_faiss_datasource = faiss_ds
        repo.sql_alchemy_chunk_datasource = SQLAlchemyChunkDataSource(client)

        result = repo.save_chunk_data([chunk])

        assert sitemap_id in result
        with client.get_session() as s:
            row = s.execute(
                text("SELECT embedding_id FROM chunks WHERE sitemap_id = :id"), {"id": sitemap_id}
            ).fetchone()
        assert row is not None, "SYS-17: the chunks row must now exist"
        assert row.embedding_id == original_embedding_id, (
            "must reuse the vector FAISS already had, not create a duplicate"
        )

        # No duplicate vector should have been added to the L1 index.
        matches = [
            doc for doc in faiss_ds.vs_l1.docstore._dict.values()
            if doc.metadata.get("sitemap_id") == sitemap_id
        ]
        assert len(matches) == 1, f"expected exactly 1 vector for this sitemap, found {len(matches)}"

    def test_a_sitemap_with_a_real_chunks_row_is_never_re_embedded(
        self, client, temp_faiss_dirs, sitemap_id
    ):
        """Sanity check the other direction: once the row genuinely exists, a repeat
        call must not touch FAISS at all for that sitemap."""
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource,
        )
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
            SQLAlchemyChunkDataSource,
        )
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
            DataFlowRepositoryImpl,
        )

        faiss_ds = ChunkFAISSDatasource()
        chunk = _make_chunk(sitemap_id, level=1, index=0, text_content="Berita ekonomi tentang inflasi.")

        repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
        repo.chunk_faiss_datasource = faiss_ds
        repo.sql_alchemy_chunk_datasource = SQLAlchemyChunkDataSource(client)

        repo.save_chunk_data([chunk])  # first call: creates the row
        vector_count_after_first = len(faiss_ds.vs_l1.docstore._dict)

        repo.save_chunk_data([chunk])  # second call: row already exists

        assert len(faiss_ds.vs_l1.docstore._dict) == vector_count_after_first, "no new vector added"
        with client.get_session() as s:
            count = s.execute(
                text("SELECT COUNT(*) FROM chunks WHERE sitemap_id = :id"), {"id": sitemap_id}
            ).scalar()
        assert count == 1, "no duplicate row"


class TestDuplicateSitemapAlreadyInFaissDoesNotAbortTheBatch:
    """SYS-26: DBT-09's own unique index (chunks_sitemap_level_index_uq) turned the
    already-in-FAISS dedup gap from a silent duplicate row into a lost batch. This is
    the exact repro from the ticket: embed into FAISS directly (as DBT-20's repair
    would, going through the `existing` branch for every sitemap), then call
    save_chunk_data with the SAME sitemap_id appearing twice in one list (a
    specific_sitemaps caller with a duplicate, or a repair script's own list)."""

    def test_duplicated_already_embedded_sitemap_leaves_exactly_one_row(
        self, client, temp_faiss_dirs, sitemap_id
    ):
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource,
        )
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
            SQLAlchemyChunkDataSource,
        )
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
            DataFlowRepositoryImpl,
        )

        faiss_ds = ChunkFAISSDatasource()
        chunk = _make_chunk(sitemap_id, level=1, index=0, text_content="Berita ekonomi tentang obligasi.")

        # Pre-condition: FAISS already has the vector, SQL does not (the SYS-17 shape).
        faiss_ds.save([chunk])
        with client.get_session() as s:
            assert s.execute(
                text("SELECT COUNT(*) FROM chunks WHERE sitemap_id = :id"), {"id": sitemap_id}
            ).scalar() == 0

        repo = DataFlowRepositoryImpl.__new__(DataFlowRepositoryImpl)
        repo.chunk_faiss_datasource = faiss_ds
        repo.sql_alchemy_chunk_datasource = SQLAlchemyChunkDataSource(client)

        # Before the fix: both copies passed the `existing` branch, save_chunks
        # inserted two rows with the same (sitemap_id, chunk_level, chunk_index),
        # and chunks_sitemap_level_index_uq raised psycopg2.errors.UniqueViolation,
        # rolling back the whole batch and leaving the sitemap with 0 chunks rows.
        result = repo.save_chunk_data([chunk, chunk])

        assert sitemap_id in result
        with client.get_session() as s:
            rows = s.execute(
                text("SELECT embedding_id FROM chunks WHERE sitemap_id = :id"), {"id": sitemap_id}
            ).fetchall()
        assert len(rows) == 1, f"expected exactly 1 chunks row, found {len(rows)}"
