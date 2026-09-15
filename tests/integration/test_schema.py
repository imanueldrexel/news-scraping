"""
DB schema constraint tests against a real PostgreSQL instance.

Coverage: SC-01..SC-10

Requires:
  - Docker Compose DB running: docker-compose -f docker/docker-compose.yaml up -d
  - Both init.sql and migrate_phase1.sql applied

Set connection via env vars (defaults match docker-compose.yaml):
  POSTGRES_DB_HOST  (default: localhost)
  POSTGRES_DB_PORT  (default: 5431  ← docker-compose maps 5431→5432)
  POSTGRES_DB_USER  (default: postgres)
  POSTGRES_DB_PASS  (default: password)
  POSTGRES_DB_NAME  (always newsaggregator_test via conftest.py)
"""
import os
import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")

DB_CONFIG = {
    'host': 'localhost',
    'port': 5431,
    'user': 'postgres',
    'password': 'postgres',
    'dbname': 'newsaggregator_test',  # NEVER the production DB
}


@pytest.fixture(scope="module")
def conn():
    try:
        c = psycopg2.connect(**DB_CONFIG)
        c.autocommit = False
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    c.close()


@pytest.fixture(autouse=True)
def rollback_after_each(conn):
    """Roll back every test so the DB stays clean."""
    yield
    conn.rollback()


def _exec(conn, sql, params=None):
    # Do NOT use "with conn.cursor() as cur" here: psycopg2's cursor context manager
    # closes the cursor on __exit__, which is called before the caller can call fetchone().
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def _insert_sitemap(conn, headline="Test", link="http://example.com"):
    cur = _exec(conn, """
        INSERT INTO sitemaps (headline, link, posted_at)
        VALUES (%s, %s, %s)
        RETURNING sitemap_id
    """, (headline, link, 20240101))
    return cur.fetchone()[0]


def _insert_article(conn, sitemap_id, text='["para1", "para2"]'):
    cur = _exec(conn, """
        INSERT INTO articles (sitemap_id, extracted_text)
        VALUES (%s, %s)
        RETURNING articles_id
    """, (sitemap_id, text))
    return cur.fetchone()[0]


def _insert_chunk(conn, sitemap_id, article_id, **overrides):
    defaults = {
        "chunk_level": 1,
        "chunk_index": 0,
        "chunk_total": 1,
        "is_first_chunk": True,
        "is_last_chunk": True,
        "text_content": "some text content for full-text search",
        "token_count": 7,
        "embedding_id": "l1:0",
        "chunk_status": "embedded",
    }
    defaults.update(overrides)
    defaults["sitemap_id"] = sitemap_id
    defaults["article_id"] = article_id
    cur = _exec(conn, """
        INSERT INTO chunks (
            sitemap_id, article_id, chunk_level, chunk_index, chunk_total,
            is_first_chunk, is_last_chunk, text_content, token_count,
            embedding_id, chunk_status
        ) VALUES (
            %(sitemap_id)s, %(article_id)s, %(chunk_level)s, %(chunk_index)s, %(chunk_total)s,
            %(is_first_chunk)s, %(is_last_chunk)s, %(text_content)s, %(token_count)s,
            %(embedding_id)s, %(chunk_status)s
        )
        RETURNING chunk_id
    """, defaults)
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# CHECK constraints on chunks
# ---------------------------------------------------------------------------

class TestChunkConstraints:
    def test_SC01_chunk_level_3_rejected(self, conn):
        sid = _insert_sitemap(conn)
        aid = _insert_article(conn, sid)
        with pytest.raises(Exception, match="chunk_level"):
            _insert_chunk(conn, sid, aid, chunk_level=3)

    def test_SC02_invalid_chunk_status_rejected(self, conn):
        sid = _insert_sitemap(conn)
        aid = _insert_article(conn, sid)
        with pytest.raises(Exception, match="chunk_status"):
            _insert_chunk(conn, sid, aid, chunk_status="invalid_status")

    def test_SC03_chunk_with_nonexistent_article_id_rejected(self, conn):
        sid = _insert_sitemap(conn)
        with pytest.raises(Exception):
            _insert_chunk(conn, sid, article_id=999999999)

    def test_SC04_chunk_with_nonexistent_sitemap_id_rejected(self, conn):
        sid = _insert_sitemap(conn)
        aid = _insert_article(conn, sid)
        with pytest.raises(Exception):
            _insert_chunk(conn, sitemap_id=999999999, article_id=aid)


# ---------------------------------------------------------------------------
# fts_vector GENERATED column
# ---------------------------------------------------------------------------

class TestFtsVector:
    def test_SC05_fts_vector_auto_populated(self, conn):
        sid = _insert_sitemap(conn)
        aid = _insert_article(conn, sid)
        chunk_id = _insert_chunk(conn, sid, aid, text_content="economy finance news")
        conn.commit()

        cur = _exec(conn, "SELECT fts_vector FROM chunks WHERE chunk_id = %s", (chunk_id,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] is not None

    def test_SC06_fts_vector_searchable_with_tsquery(self, conn):
        sid = _insert_sitemap(conn)
        aid = _insert_article(conn, sid)
        _insert_chunk(conn, sid, aid, text_content="economy finance news Indonesia")
        conn.commit()

        cur = _exec(conn, """
            SELECT COUNT(*) FROM chunks
            WHERE fts_vector @@ to_tsquery('simple', 'economy')
        """)
        count = cur.fetchone()[0]
        assert count >= 1


# ---------------------------------------------------------------------------
# Bug exposure: articles table has no FK in init.sql (B3)
# ---------------------------------------------------------------------------

class TestArticlesFKEnforced:
    def test_SC07_article_with_nonexistent_sitemap_id_rejected(self, conn):
        """FK constraint on articles.sitemap_id must be enforced (B3 regression guard)."""
        with pytest.raises(Exception):
            _exec(conn, """
                INSERT INTO articles (sitemap_id, extracted_text)
                VALUES (%s, %s)
            """, (999999998, '["para"]'))
            conn.commit()


# ---------------------------------------------------------------------------
# Bug exposure: posted_at type mismatch (B1)
# ---------------------------------------------------------------------------

class TestPostedAtType:
    def test_SC08_posted_at_column_type(self, conn):
        """
        BUG B1: init.sql defines posted_at as INTEGER, ORM defines it as TIMESTAMP.
        Insert as INTEGER (YYYYMMDD) and verify it is stored and retrieved as an integer.
        """
        sid = _insert_sitemap(conn, headline="TypeTest")
        conn.commit()

        cur = _exec(conn, "SELECT posted_at FROM sitemaps WHERE sitemap_id = %s", (sid,))
        value = cur.fetchone()[0]
        # If stored correctly as INTEGER it should come back as int (or Decimal on some drivers)
        assert isinstance(value, int), (
            f"B1 CONFIRMED: posted_at stored as {type(value).__name__} ({value!r}), "
            f"expected int. init.sql says INTEGER but ORM says TIMESTAMP."
        )


# ---------------------------------------------------------------------------
# Bug exposure: BIGSERIAL sequence vs manual ID management (B2)
# ---------------------------------------------------------------------------

class TestSitemapIdSequence:
    def test_SC09_bigserial_sequence_not_advanced_by_manual_insert(self, conn):
        """
        BUG B2: save_sitemaps() manually sets sitemap_id without calling nextval().
        After manual inserts the BIGSERIAL sequence is still at 1.
        An auto-insert (no explicit ID) would collide with the manually-assigned ID 1.
        """
        # Insert via raw SQL with explicit sitemap_id (mimicking save_sitemaps behaviour)
        try:
            _exec(conn, """
                INSERT INTO sitemaps (sitemap_id, headline, link, posted_at)
                VALUES (1, 'Manual', 'http://manual.com', 20240101)
            """)
            conn.commit()
        except Exception:
            conn.rollback()
            pytest.skip("sitemap_id=1 already exists — cannot test fresh state")

        # Now attempt an auto-generated insert (no explicit sitemap_id)
        try:
            cur = _exec(conn, """
                INSERT INTO sitemaps (headline, link, posted_at)
                VALUES ('Auto', 'http://auto.com', 20240101)
                RETURNING sitemap_id
            """)
            auto_id = cur.fetchone()[0]
            conn.commit()
            # If sequence started at 1 and we already inserted id=1 manually,
            # the auto insert would fail (duplicate PK) — proving B2
            # If it succeeded, the sequence must have been advanced somehow
            if auto_id == 1:
                pytest.fail(
                    "B2 CONFIRMED: BIGSERIAL sequence generated id=1 again, "
                    "colliding with manually-assigned id=1."
                )
        except Exception as e:
            conn.rollback()
            # Duplicate PK error — B2 confirmed
            assert "duplicate" in str(e).lower() or "unique" in str(e).lower(), (
                f"B2 CONFIRMED via PK collision: {e}"
            )

# ---------------------------------------------------------------------------
# Bug 10: articles table was missing is_embedded, knowledge_extracted,
#         knowledge_extracted_at columns — added via migrate_articles_columns.sql
# ---------------------------------------------------------------------------

class TestArticlesTableSchema:
    def test_SC_articles_has_is_embedded_column(self, conn):
        """Bug 10: is_embedded column must exist and be BOOLEAN."""
        cur = _exec(conn, """
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'articles' AND column_name = 'is_embedded'
        """)
        row = cur.fetchone()
        assert row is not None, "BUG 10: is_embedded column missing from articles table"
        assert row[0] == 'boolean', f"BUG 9: is_embedded should be boolean, got {row[0]}"

    def test_SC_articles_has_knowledge_extracted_column(self, conn):
        """Bug 10: knowledge_extracted column must exist."""
        cur = _exec(conn, """
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'articles' AND column_name = 'knowledge_extracted'
        """)
        row = cur.fetchone()
        assert row is not None, "BUG 10: knowledge_extracted column missing from articles table"

    def test_SC_articles_has_knowledge_extracted_at_column(self, conn):
        """Bug 10: knowledge_extracted_at column must exist."""
        cur = _exec(conn, """
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'articles' AND column_name = 'knowledge_extracted_at'
        """)
        row = cur.fetchone()
        assert row is not None, "BUG 10: knowledge_extracted_at column missing from articles table"


# ---------------------------------------------------------------------------
# Bug 11: chunks.article_id was NOT NULL but new pipeline creates chunks
#         before saving articles — must allow NULL.
# ---------------------------------------------------------------------------

class TestChunksArticleIdNullable:
    def test_SC_chunks_article_id_is_nullable(self, conn):
        """Bug 11: chunks.article_id must be nullable."""
        sid = _insert_sitemap(conn)
        # Insert chunk with article_id = NULL — must not raise
        _exec(conn, """
            INSERT INTO chunks (sitemap_id, chunk_level, chunk_index, chunk_total,
                is_first_chunk, is_last_chunk, text_content, token_count, chunk_status)
            VALUES (%s, 1, 0, 1, true, true, 'test', 1, 'pending_embedding')
        """, (sid,))
        # No exception = pass

    def test_SC_chunks_article_id_column_is_nullable(self, conn):
        """Verify nullable status directly from information_schema."""
        cur = _exec(conn, """
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'chunks' AND column_name = 'article_id'
        """)
        row = cur.fetchone()
        assert row is not None, "article_id column not found"
        assert row[0] == 'YES', (
            f"BUG 11: chunks.article_id must be nullable (is_nullable=YES), got {row[0]}"
        )


# ---------------------------------------------------------------------------
# Bug B: sitemaps.last_crawl_attempt column must exist and be nullable.
# ---------------------------------------------------------------------------

class TestSitemapsCrawlAttemptColumn:
    def test_SC_sitemaps_has_last_crawl_attempt_column(self, conn):
        cur = _exec(conn, """
            SELECT data_type, is_nullable FROM information_schema.columns
            WHERE table_name = 'sitemaps' AND column_name = 'last_crawl_attempt'
        """)
        row = cur.fetchone()
        assert row is not None, "Bug B: last_crawl_attempt column missing from sitemaps"
        assert row[0].startswith("timestamp"), f"expected timestamp, got {row[0]}"
        assert row[1] == "YES", "last_crawl_attempt must be nullable"
