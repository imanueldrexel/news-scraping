"""
DBT-25 (#82) item 2: scripts/fix_rejected_filter_with_faiss_evidence.py against a
real table.

The unit test asserted the shape of the call ("rejected_filter" appears in the SQL,
params["ids"] was passed) but never that the query USES :ids -- removing
`AND sitemap_id = ANY(:ids)` from find_misclassified left all 436 unit tests
green, and the script would then have flipped every rejected_filter row in
production (24,413 on 2026-09-18) back to pending, undoing SYS-16. These tests
seed rows and check what actually comes back.
"""
import importlib.util
import os
import pickle
import sys
import uuid
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE_A = "DBT25A"
SOURCE_B = "DBT25B"
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "fix_rejected_filter_with_faiss_evidence.py",
)


@pytest.fixture(scope="module")
def fix():
    spec = importlib.util.spec_from_file_location("fix_rejected_filter_live", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["fix_rejected_filter_with_faiss_evidence.py"]
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
        s.execute(text("DELETE FROM sitemaps WHERE sources IN (:a, :b)"), {"a": SOURCE_A, "b": SOURCE_B})
        s.commit()


def _seed(client, status, source=SOURCE_A):
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, posted_at, crawl_status, last_crawl_attempt) "
                 "VALUES ('t', :l, :s, 20260602, :st, NOW() - INTERVAL '100 days') RETURNING sitemap_id"),
            {"l": f"https://dbt25.test/{uuid.uuid4().hex}", "s": source, "st": status},
        ).scalar()
        s.commit()
    return sid


def _status(client, sid):
    with client.get_session() as s:
        return s.execute(text("SELECT crawl_status FROM sitemaps WHERE sitemap_id = :id"), {"id": sid}).scalar()


class TestFindMisclassifiedLive:
    def test_only_rejected_rows_with_l1_evidence_come_back(self, fix, client):
        with_evidence = _seed(client, "rejected_filter")
        without_evidence = _seed(client, "rejected_filter")
        pending_with_evidence = _seed(client, "pending")

        with client.get_session() as s:
            found = fix.find_misclassified(s, {with_evidence, pending_with_evidence}, website=SOURCE_A)

        assert found == [(with_evidence, SOURCE_A)], found
        assert without_evidence not in {sid for sid, _ in found}

    def test_website_filter_scopes_the_result(self, fix, client):
        a = _seed(client, "rejected_filter", source=SOURCE_A)
        b = _seed(client, "rejected_filter", source=SOURCE_B)

        with client.get_session() as s:
            only_a = fix.find_misclassified(s, {a, b}, website=SOURCE_A)
            both = fix.find_misclassified(s, {a, b}, website=None)

        assert only_a == [(a, SOURCE_A)]
        assert sorted(both) == sorted([(a, SOURCE_A), (b, SOURCE_B)])


class TestMainLive:
    def test_main_flips_only_the_evidenced_row(self, fix, client, tmp_path, monkeypatch):
        with_evidence = _seed(client, "rejected_filter")
        without_evidence = _seed(client, "rejected_filter")

        docstore = SimpleNamespace(_dict={"uuid-1": SimpleNamespace(metadata={"sitemap_id": with_evidence})})
        with open(tmp_path / "index.pkl", "wb") as f:
            pickle.dump((docstore, {}), f)
        monkeypatch.setattr(fix, "VECTOR_DB_NAME_L1", str(tmp_path))
        monkeypatch.setattr(sys, "argv", ["fix_rejected_filter_with_faiss_evidence.py", "--website", SOURCE_A])

        assert fix.main() == 0

        assert _status(client, with_evidence) == "pending"
        assert _status(client, without_evidence) == "rejected_filter", (
            "a rejected_filter row with NO FAISS evidence must never be flipped"
        )

    def test_dry_run_changes_nothing(self, fix, client, tmp_path, monkeypatch):
        with_evidence = _seed(client, "rejected_filter")
        docstore = SimpleNamespace(_dict={"uuid-1": SimpleNamespace(metadata={"sitemap_id": with_evidence})})
        with open(tmp_path / "index.pkl", "wb") as f:
            pickle.dump((docstore, {}), f)
        monkeypatch.setattr(fix, "VECTOR_DB_NAME_L1", str(tmp_path))
        monkeypatch.setattr(sys, "argv", ["fix_rejected_filter_with_faiss_evidence.py", "--website", SOURCE_A, "--dry-run"])

        assert fix.main() == 0
        assert _status(client, with_evidence) == "rejected_filter"
