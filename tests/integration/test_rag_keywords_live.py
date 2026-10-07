"""SYS-103 (#273, ADR-006): the keyword half through the real SQL on the test DB.

The old query ANDed every word of the question, so a whole question matched nothing.
Here a question with function words finds the paragraph that holds its rare words,
ranks the one covering all of them first, and applies the anchor and name rules;
df comes from the real `pg_stats` read and the real capped count.
"""
import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

from newscrawler.web.filters import Filters  # noqa: E402
from newscrawler.web.keywords import DocFrequency  # noqa: E402
from newscrawler.web.query_processor import QueryProcessor  # noqa: E402

TODAY = date(2026, 10, 7)
FILLERS = 150       # so each seeded word stays under the 3% anchor share however empty the DB is
PARAGRAPHS = {      # tokens no other test row carries
    "all": "Zqbank menahan ZQRATE, keputusan zqputus diumumkan.",
    "bank_only": "Zqbank menyalurkan kredit ke daerah.",
    "rate_and_word": "ZQRATE diperkirakan naik setelah zqputus pekan lalu.",
    "word_only": "Kabar zqputus beredar di pasar.",
    "two_words_no_name": "Rapat zqputus menghasilkan zqhasil yang ditunggu.",
}


@pytest.fixture
def seeded():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    try:
        with client.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    ids = {}
    with client.get_session() as s:
        def sitemap(key):
            sid = s.execute(text(
                "INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
                "VALUES (:h, :l, 'KONTAN', 'news', 20261006, 'saved') RETURNING sitemap_id"),
                {"h": f"Judul {key}", "l": f"https://rag-kw.test/{uuid.uuid4().hex}"}).scalar()
            aid = s.execute(text(
                "INSERT INTO articles (sitemap_id, extracted_text, meta_data, is_embedded, topic) "
                "VALUES (:sid, 'teks', '{}', true, 'markets') RETURNING articles_id"), {"sid": sid}).scalar()
            ids[key] = sid
            return sid, aid

        def chunk(sid, aid, index, body):
            s.execute(text(
                "INSERT INTO chunks (sitemap_id, article_id, chunk_level, chunk_index, chunk_total, "
                "is_first_chunk, is_last_chunk, text_content, chunk_status) "
                "VALUES (:sid, :aid, 2, :i, 1, true, true, :body, 'embedded')"),
                {"sid": sid, "aid": aid, "i": index, "body": body})

        for key, body in PARAGRAPHS.items():
            chunk(*sitemap(key), 0, body)
        sid, aid = sitemap("filler")
        for i in range(FILLERS):
            chunk(sid, aid, i, f"Paragraf pengisi nomor {i} tanpa kata kunci.")
        s.commit()
    yield client, ids
    with client.get_session() as s:
        for table in ("chunks", "articles", "sitemaps"):
            s.execute(text(f"DELETE FROM {table} WHERE sitemap_id = ANY(:ids)"), {"ids": list(ids.values())})
        s.commit()


def _hits(client, question):
    qp = QueryProcessor(MagicMock(), client, summarizer=None, usage=MagicMock())
    return qp._fts_search(question, 20, Filters(), TODAY)


def _by_key(ids, hits):
    key_of = {sid: key for key, sid in ids.items()}
    return [(key_of.get(h["sitemap_id"]), h["keyword_score"]) for h in hits if h["sitemap_id"] in key_of]


class TestKeywordSearchLive:
    def test_a_whole_question_finds_the_paragraph_and_ranks_full_coverage_first(self, seeded):
        """The old plainto_tsquery needed 'apa', 'kata', 'soal' and 'dan' in the paragraph too: 0 hits."""
        client, ids = seeded
        got = _by_key(ids, _hits(client, "Apa kata Zqbank soal ZQRATE dan zqputus?"))
        assert got[0] == ("all", pytest.approx(1.0))
        keys = [k for k, _ in got]
        assert "rate_and_word" in keys, "two anchors with a name"
        assert 0 < dict(got)["rate_and_word"] < 1
        assert "bank_only" not in keys and "word_only" not in keys, "one anchor is not enough"

    def test_two_anchors_without_the_name_are_not_enough(self, seeded):
        client, ids = seeded
        keys = [k for k, _ in _by_key(ids, _hits(client, "Apa kata Zqbank soal zqputus zqhasil?"))]
        assert "two_words_no_name" not in keys
        assert "all" in keys

    def test_question_of_function_words_searches_nothing(self, seeded):
        client, _ = seeded
        assert _hits(client, "Apa itu yang ini?") == []

    def test_a_typo_does_not_block_the_match(self, seeded):
        client, ids = seeded
        keys = [k for k, _ in _by_key(ids, _hits(client, "Apa kata Zqbank soal ZQRATE zqxtypo?"))]
        assert keys[0] == "all"


class TestDocFrequencyLive:
    def test_counts_rare_words_and_reads_stats(self, seeded):
        client, _ = seeded
        df = DocFrequency(client).get(["zqputus", "zqbank", "zqtidakada"])
        with client.get_session() as s:
            total = s.execute(text("SELECT COUNT(*) FROM chunks WHERE chunk_level = 2")).scalar()
        assert df["zqputus"] == pytest.approx(4 / total)
        assert df["zqbank"] == pytest.approx(2 / total)
        assert df["zqtidakada"] == 0.0
