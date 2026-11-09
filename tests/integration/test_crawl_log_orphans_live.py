"""OPS-39 (#232) against a live PostgreSQL: the orphan query's age arithmetic and the
one-off script's dry run, apply (backup first) and restore go through real SQL."""
import json
import os
import sys

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "OPS39TEST"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))


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
        s.execute(text("DELETE FROM crawl_log WHERE website = :w"), {"w": SOURCE})
        s.commit()


def _insert(client, task, age_sql):
    with client.get_session() as s:
        log_id = s.execute(text(
            f"INSERT INTO crawl_log (website, task, status, started_at) "
            f"VALUES (:w, :task, 'started', NOW() - INTERVAL '{age_sql}') RETURNING log_id"),
            {"w": SOURCE, "task": task}).scalar()
        s.commit()
    return log_id


def _status(client, log_id):
    with client.get_session() as s:
        return s.execute(text("SELECT status, finished_at = started_at AS at_start, error_msg FROM crawl_log "
                              "WHERE log_id = :id"), {"id": log_id}).fetchone()


def test_a_row_5_hours_old_is_an_orphan_and_one_10_minutes_old_is_not(client):
    from newscrawler.tools import crawl_log_orphans
    old = _insert(client, "full_text", "5 hours")
    recent = _insert(client, "full_text", "10 minutes")
    extraction = _insert(client, "extract_knowledge", "5 hours")
    with client.get_session() as s:
        found = {r.log_id for r in crawl_log_orphans.find_orphans(s) if r.website == SOURCE}
    assert found == {old}
    assert recent not in found and extraction not in found


def test_the_script_dry_runs_then_closes_with_a_backup_and_restores(client, tmp_path, capsys):
    import close_abandoned_crawl_log as script
    old = _insert(client, "sitemap", "6 hours")
    recent = _insert(client, "sitemap", "10 minutes")

    assert script.main(["--backup-dir", str(tmp_path)]) == 0                       # dry run
    assert _status(client, old).status == "started"
    assert f"#{old} {SOURCE} sitemap" in capsys.readouterr().out

    assert script.main(["--apply", "--backup-dir", str(tmp_path)]) == 0
    closed = _status(client, old)
    assert closed.status == "failed" and closed.at_start and closed.error_msg.startswith("abandoned: no run owned")
    assert _status(client, recent).status == "started"                              # a live run is left alone
    (backup,) = tmp_path.glob("ops39_crawl_log_*.json")
    saved = {row["log_id"]: row for row in json.load(open(backup, encoding="utf-8"))}
    assert saved[old]["status"] == "started" and saved[old]["finished_at"] is None

    assert script.main(["--restore", str(backup)]) == 0
    assert _status(client, old).status == "started"
