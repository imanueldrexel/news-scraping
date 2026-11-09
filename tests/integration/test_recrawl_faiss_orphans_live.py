"""
DBT-27 (#88): scripts/recrawl_faiss_orphans.py deletes production FAISS
vectors, and nothing tested its selection, its write-off predicate or that it
backs a vector up before deleting it. These tests seed real rows in
newsaggregator_test and check what the SQL actually returns; the FAISS side is
a recording double, because what matters there is WHICH ids are deleted and
that the backup exists first.
"""
import importlib.util
import json
import os
import pickle
import sys
import uuid
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "DBT27A"
OTHER = "DBT27B"
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "recrawl_faiss_orphans.py",
)


@pytest.fixture(scope="module")
def orphans():
    spec = importlib.util.spec_from_file_location("recrawl_faiss_orphans_live", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["recrawl_faiss_orphans.py"]
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
        ids = "SELECT sitemap_id FROM sitemaps WHERE sources IN (:a, :b)"
        s.execute(text(f"DELETE FROM chunks WHERE sitemap_id IN ({ids})"), {"a": SOURCE, "b": OTHER})
        s.execute(text(f"DELETE FROM articles WHERE sitemap_id IN ({ids})"), {"a": SOURCE, "b": OTHER})
        s.execute(text("DELETE FROM sitemaps WHERE sources IN (:a, :b)"), {"a": SOURCE, "b": OTHER})
        s.commit()


def _seed(client, status="pending", fetch_failures=0, source=SOURCE, chunk=False, article=False):
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, posted_at, crawl_status, fetch_failures) "
                 "VALUES ('t', :l, :s, 20260602, :st, :ff) RETURNING sitemap_id"),
            {"l": f"https://dbt27.test/{uuid.uuid4().hex}", "s": source, "st": status, "ff": fetch_failures},
        ).scalar()
        if chunk:
            s.execute(text("INSERT INTO chunks (sitemap_id, chunk_level, chunk_index, text_content) "
                           "VALUES (:id, 1, 0, 'x')"), {"id": sid})
        if article:
            s.execute(text("INSERT INTO articles (sitemap_id, extracted_text) VALUES (:id, 'x')"), {"id": sid})
        s.commit()
    return sid


class _Store:
    """A FAISS double: a docstore of sitemap_id-tagged docs, and a delete that
    records what it was asked to remove and whether the backup existed then."""

    def __init__(self, sitemap_ids, backup_dir):
        self.docstore = SimpleNamespace(_dict={
            f"emb-{sid}": SimpleNamespace(page_content=f"text {sid}", metadata={"sitemap_id": sid})
            for sid in sitemap_ids
        })
        self.backup_dir = backup_dir
        self.deleted = None
        self.backup_existed_at_delete = None

    def delete(self, ids):
        self.backup_existed_at_delete = any(n.startswith("dbt20_written_off_l1_") for n in os.listdir(self.backup_dir))
        self.deleted = list(ids)
        for i in ids:
            self.docstore._dict.pop(i)


class TestSelection:
    def test_find_orphans_returns_only_l1_only_rows_of_the_source(self, orphans, client):
        l1_only = _seed(client)
        with_chunk = _seed(client, chunk=True)
        with_article = _seed(client, article=True)
        rejected = _seed(client, status="rejected_filter")
        no_vector = _seed(client)
        other_source = _seed(client, source=OTHER)

        l1_ids = {l1_only, with_chunk, with_article, rejected, other_source}
        with client.get_session() as s:
            found = {r.sitemap_id for r in orphans.find_orphans(s, l1_ids, SOURCE)}

        assert found == {l1_only, rejected}
        assert no_vector not in found, "only ids that have an L1 vector may be selected"

    def test_the_write_off_predicate_is_the_fleet_terminal_rule(self, orphans):
        cap = orphans.SITEMAP_MAX_FETCH_FAILURES
        rows = [
            SimpleNamespace(sitemap_id=1, crawl_status="rejected_filter", fetch_failures=0),
            SimpleNamespace(sitemap_id=2, crawl_status="pending", fetch_failures=cap),
            SimpleNamespace(sitemap_id=3, crawl_status="pending", fetch_failures=1),
            SimpleNamespace(sitemap_id=4, crawl_status="empty_extraction", fetch_failures=0),
            SimpleNamespace(sitemap_id=5, crawl_status="pending", fetch_failures=0),
            SimpleNamespace(sitemap_id=6, crawl_status="pending", fetch_failures=None),
        ]
        assert [r.sitemap_id for r in orphans.unrecoverable(rows)] == [1, 2], (
            "one transient failure or an empty extraction is retried by the pipeline; its vector must stay"
        )


class TestWriteOff:
    def _population(self, client, orphans):
        cap = orphans.SITEMAP_MAX_FETCH_FAILURES
        ids = {
            "rejected": _seed(client, status="rejected_filter"),
            "retired": _seed(client, fetch_failures=cap),
            "one_failure": _seed(client, fetch_failures=1),
            "pending": _seed(client),
            "has_chunk_rejected": _seed(client, status="rejected_filter", chunk=True),
        }
        return ids

    def test_backup_is_written_before_the_delete_and_only_terminal_orphans_go(self, orphans, client, tmp_path,
                                                                              monkeypatch):
        ids = self._population(client, orphans)
        monkeypatch.setattr(orphans, "BACKUP_DIR", str(tmp_path))
        store = _Store(ids.values(), str(tmp_path))
        ds = SimpleNamespace(vs_l1=store, _atomic_save_local=lambda vs, path: setattr(store, "saved", path))

        with client.get_session() as s:
            rows = orphans.find_orphans(s, set(ids.values()), SOURCE)
        n = orphans.write_off(client, orphans.unrecoverable(rows), dry_run=False, ds=ds)

        assert n == 2
        assert sorted(store.deleted) == sorted([f"emb-{ids['rejected']}", f"emb-{ids['retired']}"])
        assert store.backup_existed_at_delete is True, "the backup must exist before any vector is deleted"
        assert store.saved == orphans.VECTOR_DB_NAME_L1
        backup = [p for p in os.listdir(tmp_path) if p.startswith("dbt20_written_off_l1_")]
        with open(tmp_path / backup[0], encoding="utf-8") as f:
            entries = json.load(f)
        assert {e["metadata"]["sitemap_id"] for e in entries} == {ids["rejected"], ids["retired"]}
        assert all(e["page_content"] for e in entries)
        for keep in ("one_failure", "pending", "has_chunk_rejected"):
            assert f"emb-{ids[keep]}" in store.docstore._dict, keep

    def test_dry_run_deletes_and_writes_nothing(self, orphans, client, tmp_path, monkeypatch):
        ids = self._population(client, orphans)
        monkeypatch.setattr(orphans, "BACKUP_DIR", str(tmp_path))
        store = _Store(ids.values(), str(tmp_path))
        ds = SimpleNamespace(vs_l1=store, _atomic_save_local=lambda *a: pytest.fail("dry run saved the index"))

        with client.get_session() as s:
            rows = orphans.find_orphans(s, set(ids.values()), SOURCE)
        assert orphans.write_off(client, orphans.unrecoverable(rows), dry_run=True, ds=ds) == 2
        assert store.deleted is None
        assert os.listdir(tmp_path) == []


class TestL1Ids:
    def test_reads_sitemap_ids_from_the_index_pickle(self, orphans, tmp_path, monkeypatch):
        docstore = SimpleNamespace(_dict={
            "a": SimpleNamespace(metadata={"sitemap_id": 7}),
            "b": SimpleNamespace(metadata={"sitemap_id": "8"}),
            "c": SimpleNamespace(metadata={}),
        })
        with open(tmp_path / "index.pkl", "wb") as f:
            pickle.dump((docstore, {}), f)
        monkeypatch.setattr(orphans, "VECTOR_DB_NAME_L1", str(tmp_path))
        assert orphans.load_l1_sitemap_ids() == {7, 8}
