"""
SYS-38 (#122): scripts/requeue_rejected_by_probe.py against newsaggregator_test.
The selection SQL (pre-probe rejects only, --since, fetch cap, no article), the
category gate, --website/--exclude, the write, and that a second run re-queues
nothing. The probe itself is stubbed: this is about which rows move.
"""
import importlib.util
import os
import sys
import uuid
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SRC, OTHER = "SYS38A", "SYS38B"
_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "scripts", "requeue_rejected_by_probe.py")


@pytest.fixture(scope="module")
def rq():
    spec = importlib.util.spec_from_file_location("requeue_rejected_by_probe", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved, sys.argv = sys.argv, ["requeue_rejected_by_probe.py"]
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
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources IN (:a,:b))"),
                  {"a": SRC, "b": OTHER})
        s.execute(text("DELETE FROM sitemaps WHERE sources IN (:a, :b)"), {"a": SRC, "b": OTHER})
        s.execute(text("DELETE FROM crawl_log WHERE task = 'requeue_rejected'"))
        s.commit()


def _seed(client, headline, source=SRC, category="news", attempt="2026-09-10", posted=20260910, failures=0,
          status="rejected_filter", article=False):
    with client.get_session() as s:
        sid = s.execute(text(
            "INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status, last_crawl_attempt, "
            "fetch_failures) VALUES (:h, :l, :s, :c, :p, :st, CAST(:a AS timestamp), :f) RETURNING sitemap_id"),
            {"h": headline, "l": f"https://sys38.test/{uuid.uuid4().hex}", "s": source, "c": category, "p": posted,
             "st": status, "a": attempt, "f": failures}).scalar()
        if article:
            s.execute(text("INSERT INTO articles (sitemap_id, extracted_text) VALUES (:i, 'x')"), {"i": sid})
        s.commit()
    return sid


def _status(client, sid):
    with client.get_session() as s:
        return tuple(s.execute(text("SELECT crawl_status, last_crawl_attempt FROM sitemaps WHERE sitemap_id=:i"),
                               {"i": sid}).fetchone())


def _stub_score(monkeypatch, rq):
    """P(soft) 0.1 for a headline starting 'news', 0.9 otherwise."""
    monkeypatch.setattr(rq, "score", lambda rows: [
        SimpleNamespace(p_soft=0.1 if r["headline"].startswith("news") else 0.9, topic="politics_government")
        for r in rows])


class TestRequeueLive:
    def test_only_pre_probe_non_denied_rows_in_the_window_move(self, rq, client, tmp_path, monkeypatch):
        _stub_score(monkeypatch, rq)
        monkeypatch.setattr(rq, "BACKUP_DIR", str(tmp_path))
        move = _seed(client, "news: DPR sahkan RUU")
        soft_by_probe = _seed(client, "resep rendang")
        after_probe = _seed(client, "news: rejected by the probe itself", attempt="2026-09-25")
        too_old = _seed(client, "news: old", posted=20260101)
        denied = _seed(client, "news: but sport desk", category="sport")
        at_cap = _seed(client, "news: dead url", failures=3)
        other = _seed(client, "news: other source", source=OTHER)

        assert rq.main(["--website", SRC, "--since", "20260801"]) == 0

        assert _status(client, move) == ("pending", None)
        for sid in (soft_by_probe, after_probe, too_old, denied, at_cap, other):
            assert _status(client, sid)[0] == "rejected_filter", sid
        assert len(os.listdir(tmp_path)) == 1
        with client.get_session() as s:
            assert s.execute(text("SELECT article_count FROM crawl_log WHERE task='requeue_rejected' "
                                  "ORDER BY log_id DESC LIMIT 1")).scalar() == 1

    def test_a_second_run_requeues_nothing(self, rq, client, tmp_path, monkeypatch):
        _stub_score(monkeypatch, rq)
        monkeypatch.setattr(rq, "BACKUP_DIR", str(tmp_path))
        _seed(client, "news: once")
        assert rq.main(["--website", SRC, "--since", "20260801"]) == 0
        with client.get_session() as s:
            before = s.execute(text("SELECT count(*) FROM sitemaps WHERE sources=:s AND crawl_status='pending'"),
                               {"s": SRC}).scalar()
        assert rq.main(["--website", SRC, "--since", "20260801"]) == 0
        with client.get_session() as s:
            after = s.execute(text("SELECT count(*) FROM sitemaps WHERE sources=:s AND crawl_status='pending'"),
                              {"s": SRC}).scalar()
        assert before == after == 1

    def test_dry_run_and_exclude(self, rq, client, tmp_path, monkeypatch):
        _stub_score(monkeypatch, rq)
        monkeypatch.setattr(rq, "BACKUP_DIR", str(tmp_path))
        sid = _seed(client, "news: stays for the dry run")
        assert rq.main(["--website", SRC, "--since", "20260801", "--dry-run"]) == 0
        assert _status(client, sid)[0] == "rejected_filter"
        assert rq.main(["--website", SRC, "--exclude", SRC, "--since", "20260801"]) == 0
        assert _status(client, sid)[0] == "rejected_filter"
        assert os.listdir(tmp_path) == []


class TestPure:
    def test_decide_is_lenient_and_checks_the_pairing(self, rq):
        rows = [{"sitemap_id": 1}, {"sitemap_id": 2}]
        requeue, keep = rq.decide(rows, [SimpleNamespace(p_soft=0.69, topic="x"), SimpleNamespace(p_soft=0.7, topic="y")], 0.7)
        assert [r["sitemap_id"] for r in requeue] == [1] and [r["sitemap_id"] for r in keep] == [2]
        with pytest.raises(RuntimeError):
            rq.decide(rows, [SimpleNamespace(p_soft=0.1, topic="x")], 0.7)
