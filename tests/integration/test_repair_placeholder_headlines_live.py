"""
DBT-32 (#141): scripts/repair_placeholder_headlines.py against a real table --
the candidate SELECT (fetched rows only: an articles row or rejected_filter;
pending rows are the crawler's) and the two UPDATEs (sitemaps.headline always,
articles.meta_data->>'title' only where an article exists). Asserted on what
comes back from the DB, not on the SQL text.
"""
import os
import sys
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

SOURCE = "TIRTO"  # find_placeholders filters on sources; rows are tagged by link prefix instead
LINK_PREFIX = "https://dbt32.test/"


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
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE link LIKE :p)"),
                  {"p": LINK_PREFIX + "%"})
        s.execute(text("DELETE FROM sitemaps WHERE link LIKE :p"), {"p": LINK_PREFIX + "%"})
        s.commit()


def _seed(client, slug, headline, crawl_status, with_article):
    link = f"{LINK_PREFIX}{uuid.uuid4().hex[:6]}/{slug}?page=all"
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
                 "VALUES (:h, :l, :s, 'ekonomi', 20260920, :st) RETURNING sitemap_id"),
            {"h": headline, "l": link, "s": SOURCE, "st": crawl_status},
        ).scalar()
        if with_article:
            s.execute(
                text("INSERT INTO articles (sitemap_id, extracted_text, writer, meta_data) "
                     "VALUES (:sid, 'body', '[]', CAST(:m AS jsonb))"),
                {"sid": sid, "m": '{"title": "%s", "extractor": "site"}' % headline},
            )
        s.commit()
    return sid


def _read(client, sid):
    with client.get_session() as s:
        return s.execute(
            text("SELECT s.headline, a.meta_data->>'title' FROM sitemaps s LEFT JOIN articles a USING (sitemap_id) "
                 "WHERE s.sitemap_id = :id"), {"id": sid}).fetchone()


class TestRepairPlaceholderHeadlinesLive:
    def test_selection_and_write(self, client):
        from repair_placeholder_headlines import apply_titles, find_placeholders

        saved_ph = _seed(client, "rupiah-menguat-hCa5", "Rupiah Menguat Hca5", "saved", True)
        rejected_ph = _seed(client, "apa-dampak-bbm-2287141", "Apa Dampak Bbm 2287141", "rejected_filter", False)
        pending_ph = _seed(client, "harga-bbm-naik-hB7q", "Harga Bbm Naik Hb7Q", "pending", False)
        saved_real = _seed(client, "ihsg-menguat-gZ9x", "IHSG Menguat, Ini Pergerakannya", "saved", True)

        with client.get_session() as s:
            rows = [r for r in find_placeholders(s, [SOURCE]) if r.link.startswith(LINK_PREFIX)]
        assert sorted(r.sitemap_id for r in rows) == sorted([saved_ph, rejected_ph]), \
            "only already-fetched placeholder rows are candidates: pending and real-title rows are not"

        titles = {saved_ph: "Rupiah Menguat, Ini Pergerakannya", rejected_ph: "Apa Dampak Kelangkaan BBM"}
        with client.get_session() as s:
            n_sitemaps, n_articles = apply_titles(s, rows, titles)
            s.commit()
        assert (n_sitemaps, n_articles) == (2, 1)

        assert _read(client, saved_ph) == ("Rupiah Menguat, Ini Pergerakannya", "Rupiah Menguat, Ini Pergerakannya")
        assert _read(client, rejected_ph) == ("Apa Dampak Kelangkaan BBM", None)
        assert _read(client, pending_ph) == ("Harga Bbm Naik Hb7Q", None)
        assert _read(client, saved_real) == ("IHSG Menguat, Ini Pergerakannya", "IHSG Menguat, Ini Pergerakannya")

        # Idempotent: a second pass with the same titles changes nothing.
        with client.get_session() as s:
            assert apply_titles(s, rows, titles) == (0, 0)
            assert [r for r in find_placeholders(s, [SOURCE]) if r.link.startswith(LINK_PREFIX)] == []
