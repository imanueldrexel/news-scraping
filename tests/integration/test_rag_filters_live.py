"""SYS-92 (#261) / SYS-100 (#269): the search filters through the real SQL on the test DB.

The old filter matched `sitemaps.category` by substring, so "Makroekonomi" and three other
options found 0 articles in production. A seeded hybrid result is filtered here by
`articles.topic`, portal and date through QueryProcessor's own FTS and metadata queries;
FAISS is a fake (its search returns hits by sitemap_id, as the real one does).
"""
import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

from newscrawler.web.filters import Filters, parse  # noqa: E402
from newscrawler.web.query_processor import QueryProcessor  # noqa: E402

TODAY = date(2026, 10, 7)
WORD = "zrupiahz"   # a token no other test row carries
# SYS-105: a matched paragraph under MIN_PARAGRAPH_WORDS is never a source, so the seeded ones are real-sized.
FILLER = "menurut keterangan resmi yang disampaikan kepada wartawan di Jakarta pada hari Senin pagi"


@pytest.fixture
def seeded():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    try:
        with client.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    rows = [  # (source, posted_at, topic, has_article)
        ("KONTAN", 20261005, "markets", True),
        ("DETIK", 20261006, "law_crime", True),
        ("KONTAN", 20260901, "markets", True),
        ("CNBC", 20261004, "corporate", True),
        ("CNBC", 20261004, None, False),        # a sitemap without an article: never a source
    ]
    ids = {}
    with client.get_session() as s:
        for i, (source, posted, topic, has_article) in enumerate(rows):
            sid = s.execute(text(
                "INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
                "VALUES (:h, :l, :s, 'news', :p, 'saved') RETURNING sitemap_id"),
                {"h": f"Judul {i}", "l": f"https://rag.test/{uuid.uuid4().hex}", "s": source, "p": posted}).scalar()
            article_id = None
            if has_article:
                article_id = s.execute(text(
                    "INSERT INTO articles (sitemap_id, extracted_text, meta_data, is_embedded, topic) "
                    "VALUES (:sid, 'teks', '{}', true, :t) RETURNING articles_id"),
                    {"sid": sid, "t": topic}).scalar()
            for level, body in ((1, f"Pembuka artikel {i}."), (2, f"Paragraf {WORD} nomor {i} {FILLER}.")):
                s.execute(text(
                    "INSERT INTO chunks (sitemap_id, article_id, chunk_level, chunk_index, chunk_total, "
                    "is_first_chunk, is_last_chunk, text_content, chunk_status) "
                    "VALUES (:sid, :aid, :lvl, 0, 1, true, true, :body, 'embedded')"),
                    {"sid": sid, "aid": article_id, "lvl": level, "body": body})
            ids[i] = sid
        s.commit()
    yield client, ids
    with client.get_session() as s:
        s.execute(text("DELETE FROM chunks WHERE sitemap_id = ANY(:ids)"), {"ids": list(ids.values())})
        s.execute(text("DELETE FROM articles WHERE sitemap_id = ANY(:ids)"), {"ids": list(ids.values())})
        s.execute(text("DELETE FROM sitemaps WHERE sitemap_id = ANY(:ids)"), {"ids": list(ids.values())})
        s.commit()


def _processor(client, semantic_ids=()):
    faiss = MagicMock()
    faiss.search_l2.return_value = [{"sitemap_id": sid, "semantic_score": 0.9, "text_content": f"{WORD} {FILLER}",
                                     "posted_at": "19700823", "source": "WRONG"} for sid in semantic_ids]
    return QueryProcessor(faiss, client, summarizer=None, usage=MagicMock())


class TestFtsWithFiltersLive:
    def _ids(self, client, filters):
        qp = _processor(client)
        return {h["sitemap_id"] for h in qp._fts_search(qp._keyword_query(WORD), 20, filters, TODAY)}

    def test_no_filter(self, seeded):
        client, ids = seeded
        assert self._ids(client, Filters()) == set(ids.values())

    def test_topic_from_articles(self, seeded):
        client, ids = seeded
        assert self._ids(client, Filters(topic="markets")) == {ids[0], ids[2]}

    def test_portal_and_last_7_days(self, seeded):
        client, ids = seeded
        assert self._ids(client, parse(source="KONTAN", rentang="7")) == {ids[0]}

    def test_custom_range(self, seeded):
        client, ids = seeded
        got = self._ids(client, parse(rentang="custom", date_from="2026-10-04", date_to="2026-10-05"))
        assert got == {ids[0], ids[3], ids[4]}


class TestRetrieveLive:
    def test_every_topic_option_narrows_to_its_topic(self, seeded):
        client, ids = seeded
        qp = _processor(client, semantic_ids=ids.values())
        for topic, expected in (("markets", {ids[0], ids[2]}), ("law_crime", {ids[1]}), ("corporate", {ids[3]})):
            hits = qp.retrieve(WORD, Filters(topic=topic), TODAY)
            assert {h["sitemap_id"] for h in hits} == expected, topic
            assert all(h["topic"] == topic for h in hits)

    def test_metadata_comes_from_the_database_and_orphans_are_dropped(self, seeded):
        client, ids = seeded
        hits = _processor(client, semantic_ids=ids.values()).retrieve(WORD, Filters(), TODAY)
        by_id = {h["sitemap_id"]: h for h in hits}
        assert ids[4] not in by_id, "a sitemap without an article is not a source"
        first = by_id[ids[0]]
        assert first["source"] == "KONTAN" and first["posted_date"] == date(2026, 10, 5)
        assert first["l1_text"] == "Pembuka artikel 0." and first["title"] == "Judul 0"
