"""SYS-91 (#257): scripts/repair_faiss_posted_at.py against the test database and a temp FAISS pair
(fake embeddings: only the metadata matters). Production NEWS_L1/NEWS_L2 and backups/ are never touched."""
import importlib.util
import os
import shutil
import tempfile
import uuid
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from langchain_core.documents import Document  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402
from sqlalchemy import text  # noqa: E402

from newscrawler.tools import store_repair  # noqa: E402

SOURCE = "SYS91TEST"
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "scripts", "repair_faiss_posted_at.py")


class _Fixed(Embeddings):
    def embed_documents(self, texts):
        return [[1.0, float(i), 0.5] for i, _ in enumerate(texts)]

    def embed_query(self, text_):
        return [1.0, 0.0, 0.5]


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("repair_faiss_posted_at_live", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


@pytest.fixture
def env(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="sys91_")
    import newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source as cfd
    from newscrawler.tools import run_lock
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L1", f"{tmp}/L1")
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L2", f"{tmp}/L2")
    monkeypatch.setattr(store_repair, "BACKUP_DIR", f"{tmp}/backups")
    monkeypatch.setattr(run_lock, "LOCK_PATH", f"{tmp}/scheduled_crawl.lock")
    yield SimpleNamespace(tmp=tmp, l1=f"{tmp}/L1", l2=f"{tmp}/L2")
    shutil.rmtree(tmp, ignore_errors=True)


def _sitemap(client, posted_at):
    with client.get_session() as s:
        sid = s.execute(text(
            "INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
            "VALUES ('h', :l, :s, 'news', :p, 'saved') RETURNING sitemap_id"),
            {"l": f"https://sys91.test/{uuid.uuid4().hex}", "s": SOURCE, "p": posted_at}).scalar()
        s.commit()
    return sid


def _write_index(path, metas):
    """A fresh pair on disk (the fixture's; the script's own saves go through the guarded path)."""
    from langchain_community.vectorstores import FAISS
    docs = [Document(page_content=f"paragraf {i}", metadata=dict(m, source=SOURCE)) for i, m in enumerate(metas)]
    FAISS.from_documents(docs, _Fixed(), ids=[f"id{i}" for i in range(len(docs))]).save_local(path)


def _posted(path):
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    store = load_index(path, store_repair.NoEmbeddings())
    return {i: d.metadata["posted_at"] for i, d in store.docstore._dict.items()}, store.index.ntotal


@pytest.fixture
def seeded(client, env):
    broken, fine, other = _sitemap(client, 20260918), _sitemap(client, 20260920), _sitemap(client, 20260921)
    _write_index(env.l1, [{"sitemap_id": broken, "posted_at": "19700823"},
                          {"sitemap_id": fine, "posted_at": "20260920"}])
    _write_index(env.l2, [{"sitemap_id": broken, "posted_at": "19700823"},
                          {"sitemap_id": broken, "posted_at": "19700823"},
                          {"sitemap_id": other, "posted_at": "20260101"}])
    return SimpleNamespace(broken=broken, fine=fine, other=other)


class TestRepairFaissPostedAtLive:
    def test_apply_rewrites_the_1970_documents_and_nothing_else(self, script, client, env, seeded):
        assert script.apply(SimpleNamespace(all_mismatches=False), client=client) == 0
        l1, n1 = _posted(env.l1)
        l2, n2 = _posted(env.l2)
        assert l1 == {"id0": "20260918", "id1": "20260920"} and n1 == 2
        assert l2 == {"id0": "20260918", "id1": "20260918", "id2": "20260101"} and n2 == 3, "the other kind waits"
        backups = os.listdir(store_repair.BACKUP_DIR)
        assert len(backups) == 1 and backups[0].startswith("sys91_ALL_")

    def test_a_second_run_finds_nothing_to_write(self, script, client, env, seeded):
        script.apply(SimpleNamespace(all_mismatches=False), client=client)
        stores = {db: script._load(db) for db in (env.l1, env.l2)}
        assert {db: script.to_write(ms) for db, ms in script.find(client, stores).items()} == {env.l1: [], env.l2: []}

    def test_widened_it_also_rewrites_the_other_kind(self, script, client, env, seeded):
        assert script.apply(SimpleNamespace(all_mismatches=True), client=client) == 0
        assert _posted(env.l2)[0]["id2"] == "20260921"

    def test_the_dry_run_writes_nothing(self, script, client, env, seeded, monkeypatch, capsys):
        before = (_posted(env.l1), _posted(env.l2))
        monkeypatch.setattr(script, "SQLAlchemyClient", lambda: client)
        assert script.main([]) == 0
        out = capsys.readouterr().out
        assert "1 would be rewritten (19xx only)" in out and "2 would be rewritten (19xx only)" in out
        assert (_posted(env.l1), _posted(env.l2)) == before
        assert not os.path.exists(store_repair.BACKUP_DIR)

    def test_a_started_crawl_refuses_before_any_backup(self, script, client, env, seeded, monkeypatch):
        monkeypatch.setattr(script, "crawl_running", lambda session: 1)
        assert script.apply(SimpleNamespace(all_mismatches=False), client=client) == 2
        assert _posted(env.l1)[0]["id0"] == "19700823" and not os.path.exists(store_repair.BACKUP_DIR)
