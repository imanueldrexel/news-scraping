"""
SRC-10 (#65): scripts/repair_numeric_bylines.py selects only bylines the
crawler's name guard rejects, backs them up, and writes the re-fetched name
or [] -- never touching a real name that happens to contain a digit.
"""
import importlib.util
import json
import os
import uuid
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "SRC10T"
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "repair_numeric_bylines.py",
)


@pytest.fixture(scope="module")
def repair():
    spec = importlib.util.spec_from_file_location("repair_numeric_bylines", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
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
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources=:s)"),
                  {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _article(client, writer):
    with client.get_session() as s:
        sid = s.execute(text("INSERT INTO sitemaps (headline, link, sources, posted_at) "
                             "VALUES ('t', :l, :s, 20260916) RETURNING sitemap_id"),
                        {"l": f"https://src10.test/{uuid.uuid4().hex}", "s": SOURCE}).scalar()
        aid = s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, writer) "
                             "VALUES (:id, 'x', CAST(:w AS JSON)) RETURNING articles_id"),
                        {"id": sid, "w": json.dumps(writer)}).scalar()
        s.commit()
    return aid


def _writer(client, aid):
    with client.get_session() as s:
        return s.execute(text("SELECT writer FROM articles WHERE articles_id = :a"), {"a": aid}).scalar()


class TestSelection:
    @pytest.mark.parametrize("writer,bad", [
        (["16"], True), (["16/09/2026"], True), (["Desi Angriani", "17"], True),
        (["Desi Angriani"], False), (["Tim Riset 2"], False), ([], False), (None, False),
    ])
    def test_the_guard_decides(self, repair, writer, bad):
        assert repair.is_bad_byline(writer) is bad


class TestRefetch:
    def _crawler(self, soup, names):
        return SimpleNamespace(page_loader=SimpleNamespace(get_soup=lambda link: soup),
                               _get_reporter_from_text=lambda s: names,
                               _looks_like_a_name=repair_guard())

    def test_a_page_that_fails_gives_unknown(self, repair):
        assert repair.refetch_byline(self._crawler(None, ["X"]), "http://x") == []

    def test_the_guard_filters_what_the_selector_returns(self, repair):
        assert repair.refetch_byline(self._crawler(object(), ["16", "Desi Angriani"]), "http://x") == ["Desi Angriani"]


def repair_guard():
    from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
    return Crawler._looks_like_a_name


class TestMainLive:
    def test_no_fetch_writes_unknown_and_backs_up(self, repair, client, tmp_path, monkeypatch):
        bad = _article(client, ["16"])
        good = _article(client, ["Desi Angriani"])
        monkeypatch.setattr(repair, "BACKUP_DIR", str(tmp_path))

        assert repair.main(["--website", SOURCE, "--dry-run", "--no-fetch"]) == 0
        assert _writer(client, bad) == ["16"] and os.listdir(tmp_path) == []

        assert repair.main(["--website", SOURCE, "--no-fetch"]) == 0
        assert _writer(client, bad) == []
        assert _writer(client, good) == ["Desi Angriani"]
        (backup,) = os.listdir(tmp_path)
        with open(tmp_path / backup, encoding="utf-8") as f:
            (entry,) = json.load(f)
        assert (entry["articles_id"], entry["writer"], entry["new_writer"]) == (bad, ["16"], [])
