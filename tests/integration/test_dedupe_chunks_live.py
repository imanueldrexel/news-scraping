"""
DBT-21 (#72): dedupe_chunks.py's backup must be re-insertable into `chunks`
from the JSON alone. That depends on its SELECT returning every column of the
table; the unit tests can only check that what was selected was kept. The
unique index (DBT-09) means no duplicate group can be seeded here, but the
statement's columns are known without a row.
"""
import importlib.util
import os
import sys
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "dedupe_chunks.py",
)


@pytest.fixture(scope="module")
def dedupe():
    spec = importlib.util.spec_from_file_location("dedupe_chunks_live", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["dedupe_chunks.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
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
        s.execute(text("DELETE FROM chunks WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources='DBT21')"))
        s.execute(text("DELETE FROM sitemaps WHERE sources = 'DBT21'"))
        s.commit()


def test_the_duplicate_select_returns_every_chunks_column(dedupe, client):
    with client.get_session() as s:
        selected = set(s.execute(dedupe._DUP_GROUPS_SQL).keys())
        stored = {r[0] for r in s.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'chunks' AND is_generated = 'NEVER'"))}
    backed_up = {c for c in selected if c not in dedupe._NOT_BACKED_UP}
    assert backed_up == stored


def test_a_backup_entry_reinserts_the_same_row(dedupe, client):
    """Round trip through the script's own serialiser: back up, delete,
    re-insert from the JSON-shaped dict alone, compare."""
    import json
    with client.get_session() as s:
        sid = s.execute(text("INSERT INTO sitemaps (headline, link, sources, posted_at) "
                             "VALUES ('t', :l, 'DBT21', 20260917) RETURNING sitemap_id"),
                        {"l": f"https://dbt21.test/{uuid.uuid4().hex}"}).scalar()
        s.execute(text("INSERT INTO chunks (sitemap_id, chunk_level, chunk_index, text_content, token_count, "
                       "embedding_id) VALUES (:id, 2, 3, 'isi paragraf', 2, 'emb-x')"), {"id": sid})
        s.commit()
        row = s.execute(text(
            "SELECT c.*, FALSE AS referenced FROM chunks c WHERE c.sitemap_id = :id"), {"id": sid}).fetchone()
        before = dict(row._mapping)
        entry = json.loads(json.dumps(dedupe._backup_entry(row), default=str))
        s.execute(text("DELETE FROM chunks WHERE chunk_id = :c"), {"c": entry["chunk_id"]})
        cols = ", ".join(entry)
        s.execute(text(f"INSERT INTO chunks ({cols}) VALUES ({', '.join(':' + k for k in entry)})"), entry)
        s.commit()
        after = dict(s.execute(text(
            "SELECT c.*, FALSE AS referenced FROM chunks c WHERE c.sitemap_id = :id"), {"id": sid}).fetchone()._mapping)
    assert after == before
