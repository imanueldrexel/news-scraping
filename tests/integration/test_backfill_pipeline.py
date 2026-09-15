"""
End-to-end integration tests for the chunk + embed backfill pipeline.

Coverage:
  8.1  Happy path
  8.2  Idempotency
  8.3  Dry-run mode
  8.4  Empty text handling
  8.5  Token count accuracy
  8.6  Batch continuity

Requires live PostgreSQL and (for non-dry-run) sentence-transformers + faiss-cpu.
Set SKIP_EMBED=1 to skip embedding-dependent tests and only verify DB structure.
"""
import os
import sys
import tempfile
import shutil
import importlib.util

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")

DB_CONFIG = dict(
    host=os.getenv("POSTGRES_DB_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_DB_PORT", 5431)),
    user=os.getenv("POSTGRES_DB_USER", "postgres"),
    password=os.getenv("POSTGRES_DB_PASS", "postgres"),
    dbname=os.getenv("POSTGRES_DB_NAME", "newsaggregator"),
)
SKIP_EMBED = os.getenv("SKIP_EMBED", "0") == "1"


@pytest.fixture(scope="module")
def pg():
    try:
        c = psycopg2.connect(**DB_CONFIG)
        c.autocommit = False
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    c.close()


@pytest.fixture(autouse=True)
def clean_test_data(pg):
    """Remove test data before and after each test."""
    yield
    pg.rollback()
    with pg.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE text_content LIKE 'BACKFILL_TEST%'")
        cur.execute("DELETE FROM articles WHERE extracted_text LIKE '%BACKFILL_TEST%'")
        cur.execute("DELETE FROM sitemaps WHERE headline LIKE 'BACKFILL_TEST%'")
    pg.commit()


def _insert_sitemap(pg, headline):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO sitemaps (headline, link, posted_at) VALUES (%s, %s, %s) RETURNING sitemap_id",
            (headline, f"http://test.com/{headline}", 20240101),
        )
        sid = cur.fetchone()[0]
    pg.commit()
    return sid


def _insert_article(pg, sitemap_id, paragraphs):
    import json
    raw = json.dumps(paragraphs)
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO articles (sitemap_id, extracted_text) VALUES (%s, %s) RETURNING articles_id",
            (sitemap_id, raw),
        )
        aid = cur.fetchone()[0]
    pg.commit()
    return aid


def _run_backfill(extra_args=None, vector_dir=None):
    """Run backfill_chunks.main() in-process."""
    _SCRIPT_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts", "backfill_chunks.py",
    )
    saved_argv = sys.argv
    saved_env = {}

    if vector_dir:
        saved_env["VECTOR_DB_DIR"] = os.environ.get("VECTOR_DB_DIR", "")
        os.environ["VECTOR_DB_DIR"] = vector_dir

    try:
        sys.argv = ["backfill_chunks.py"] + (extra_args or [])
        spec = importlib.util.spec_from_file_location("backfill_chunks_run", _SCRIPT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
    finally:
        sys.argv = saved_argv
        if vector_dir:
            if saved_env["VECTOR_DB_DIR"]:
                os.environ["VECTOR_DB_DIR"] = saved_env["VECTOR_DB_DIR"]
            else:
                del os.environ["VECTOR_DB_DIR"]


def _count_chunks(pg, article_id):
    with pg.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks WHERE article_id = %s", (article_id,))
        return cur.fetchone()[0]


def _get_chunks(pg, article_id):
    with pg.cursor() as cur:
        cur.execute("""
            SELECT chunk_level, chunk_index, chunk_total, is_first_chunk, is_last_chunk,
                   text_content, token_count, embedding_id, chunk_status
            FROM chunks WHERE article_id = %s
            ORDER BY chunk_level, chunk_index
        """, (article_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# 8.1 Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_happy_path_produces_l1_and_l2_chunks(self, pg):
        paragraphs = [f"BACKFILL_TEST word{j}" + " extra" * 90 for j in range(5)]
        sid = _insert_sitemap(pg, "BACKFILL_TEST Happy")
        aid = _insert_article(pg, sid, paragraphs)

        tmpdir = tempfile.mkdtemp()
        try:
            if SKIP_EMBED:
                _run_backfill(["--dry-run"], vector_dir=tmpdir)
                return  # can't assert DB state in dry-run

            _run_backfill(["--batch-size", "10"], vector_dir=tmpdir)
            chunks = _get_chunks(pg, aid)

            l1 = [c for c in chunks if c["chunk_level"] == 1]
            l2 = [c for c in chunks if c["chunk_level"] == 2]

            assert len(l1) == 1, f"Expected 1 L1 chunk, got {len(l1)}"
            assert len(l2) >= 1, f"Expected at least 1 L2 chunk, got {len(l2)}"

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_l1_structural_fields(self, pg):
        paragraphs = [f"BACKFILL_TEST para{j}" + " word" * 90 for j in range(3)]
        sid = _insert_sitemap(pg, "BACKFILL_TEST L1Fields")
        aid = _insert_article(pg, sid, paragraphs)

        tmpdir = tempfile.mkdtemp()
        try:
            if SKIP_EMBED:
                pytest.skip("SKIP_EMBED=1")

            _run_backfill(["--batch-size", "10"], vector_dir=tmpdir)
            chunks = _get_chunks(pg, aid)
            l1 = [c for c in chunks if c["chunk_level"] == 1][0]

            assert l1["chunk_index"] == 0
            assert l1["chunk_total"] == 1
            assert l1["is_first_chunk"] is True
            assert l1["is_last_chunk"] is True
            assert l1["chunk_status"] == "embedded"
            assert l1["embedding_id"] is not None
            assert l1["embedding_id"].startswith("l1:")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_l2_index_sequence_and_total(self, pg):
        paragraphs = [f"BACKFILL_TEST para{j}" + " word" * 90 for j in range(5)]
        sid = _insert_sitemap(pg, "BACKFILL_TEST L2Seq")
        aid = _insert_article(pg, sid, paragraphs)

        tmpdir = tempfile.mkdtemp()
        try:
            if SKIP_EMBED:
                pytest.skip("SKIP_EMBED=1")

            _run_backfill(["--batch-size", "10"], vector_dir=tmpdir)
            chunks = _get_chunks(pg, aid)
            l2 = [c for c in chunks if c["chunk_level"] == 2]

            indices = [c["chunk_index"] for c in l2]
            assert indices == list(range(len(l2))), f"L2 indices not sequential: {indices}"

            totals = {c["chunk_total"] for c in l2}
            assert len(totals) == 1 and totals.pop() == len(l2)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 8.2 Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_run_inserts_zero_chunks(self, pg):
        paragraphs = [f"BACKFILL_TEST idempotent" + " word" * 90 for _ in range(3)]
        sid = _insert_sitemap(pg, "BACKFILL_TEST Idempotent")
        aid = _insert_article(pg, sid, paragraphs)

        tmpdir = tempfile.mkdtemp()
        try:
            if SKIP_EMBED:
                pytest.skip("SKIP_EMBED=1")

            _run_backfill(["--batch-size", "10"], vector_dir=tmpdir)
            count_after_first = _count_chunks(pg, aid)

            _run_backfill(["--batch-size", "10"], vector_dir=tmpdir)
            count_after_second = _count_chunks(pg, aid)

            assert count_after_second == count_after_first, (
                f"Second run inserted extra chunks: {count_after_first} → {count_after_second}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 8.3 Dry-run mode
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_writes_no_chunks(self, pg):
        paragraphs = [f"BACKFILL_TEST dryrun" + " word" * 90 for _ in range(3)]
        sid = _insert_sitemap(pg, "BACKFILL_TEST DryRun")
        aid = _insert_article(pg, sid, paragraphs)

        tmpdir = tempfile.mkdtemp()
        try:
            _run_backfill(["--dry-run"], vector_dir=tmpdir)
            count = _count_chunks(pg, aid)
            assert count == 0, f"Dry-run wrote {count} chunks — should be 0"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dry_run_creates_no_faiss_files(self, pg):
        sid = _insert_sitemap(pg, "BACKFILL_TEST DryRunFaiss")
        _insert_article(pg, sid, ["BACKFILL_TEST " + "word " * 90])

        tmpdir = tempfile.mkdtemp()
        try:
            _run_backfill(["--dry-run"], vector_dir=tmpdir)
            files = os.listdir(tmpdir)
            faiss_files = [f for f in files if f.endswith(".index")]
            assert faiss_files == [], f"Dry-run created FAISS files: {faiss_files}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 8.4 Empty text handling
# ---------------------------------------------------------------------------

class TestEmptyTextHandling:
    def test_empty_extracted_text_skipped(self, pg):
        sid = _insert_sitemap(pg, "BACKFILL_TEST Empty")
        aid = _insert_article(pg, sid, [])  # empty paragraph list

        tmpdir = tempfile.mkdtemp()
        try:
            if SKIP_EMBED:
                _run_backfill(["--dry-run"], vector_dir=tmpdir)
            else:
                _run_backfill(["--batch-size", "10"], vector_dir=tmpdir)

            count = _count_chunks(pg, aid)
            assert count == 0, f"Empty article produced {count} chunks — should be 0"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 8.5 Token count accuracy
# ---------------------------------------------------------------------------

class TestTokenCountAccuracy:
    def test_token_count_matches_word_split(self, pg):
        p1 = "BACKFILL_TEST " + " ".join(f"w{i}" for i in range(99))  # 100 words
        p2 = "BACKFILL_TEST " + " ".join(f"x{i}" for i in range(89))  # 90 words

        sid = _insert_sitemap(pg, "BACKFILL_TEST TokenCount")
        aid = _insert_article(pg, sid, [p1, p2])

        tmpdir = tempfile.mkdtemp()
        try:
            if SKIP_EMBED:
                pytest.skip("SKIP_EMBED=1")

            _run_backfill(["--batch-size", "10"], vector_dir=tmpdir)
            chunks = _get_chunks(pg, aid)

            for chunk in chunks:
                expected_tc = len(chunk["text_content"].split())
                assert chunk["token_count"] == expected_tc, (
                    f"Token count mismatch for chunk_index={chunk['chunk_index']}: "
                    f"DB={chunk['token_count']}, computed={expected_tc}"
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 8.6 Batch continuity (sequential embedding IDs across batches)
# ---------------------------------------------------------------------------

class TestBatchContinuity:
    def test_embedding_ids_sequential_across_batches(self, pg):
        if SKIP_EMBED:
            pytest.skip("SKIP_EMBED=1")

        articles = []
        for i in range(3):
            sid = _insert_sitemap(pg, f"BACKFILL_TEST Batch{i}")
            paragraphs = [f"BACKFILL_TEST batch{i} " + " ".join(f"w{j}" for j in range(99))]
            aid = _insert_article(pg, sid, paragraphs)
            articles.append(aid)

        tmpdir = tempfile.mkdtemp()
        try:
            _run_backfill(["--batch-size", "1"], vector_dir=tmpdir)

            all_l1_ids = []
            all_l2_ids = []
            for aid in articles:
                chunks = _get_chunks(pg, aid)
                all_l1_ids.extend(
                    int(c["embedding_id"].split(":")[1])
                    for c in chunks if c["chunk_level"] == 1
                )
                all_l2_ids.extend(
                    int(c["embedding_id"].split(":")[1])
                    for c in chunks if c["chunk_level"] == 2
                )

            all_l1_ids.sort()
            all_l2_ids.sort()
            # IDs should be sequential with no gaps
            assert all_l1_ids == list(range(min(all_l1_ids), max(all_l1_ids) + 1)), (
                f"L1 IDs not sequential across batches: {all_l1_ids}"
            )
            assert all_l2_ids == list(range(min(all_l2_ids), max(all_l2_ids) + 1)), (
                f"L2 IDs not sequential across batches: {all_l2_ids}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
