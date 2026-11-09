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
    kq = qp._keyword_query(question)
    return [] if kq is None else qp._fts_search(kq, 20, Filters(), TODAY)


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


class TestCoverageLive:
    """SYS-106 (#276): a FAISS hit the keyword half did not return is scored by `_coverage`, on the
    paragraph's text. It must give the score the FTS SQL gives the same paragraph from the stored
    `fts_vector`, or the two kinds of hits would not compare like with like."""

    def test_coverage_of_a_text_equals_the_fts_score_of_that_paragraph(self, seeded):
        client, ids = seeded
        qp = QueryProcessor(MagicMock(), client, summarizer=None, usage=MagicMock())
        question = "Apa kata Zqbank soal ZQRATE dan zqputus?"
        kq = qp._keyword_query(question)
        fts = {h["sitemap_id"]: h["keyword_score"] for h in qp._fts_search(kq, 20, Filters(), TODAY)}
        keys = [k for k in ("all", "rate_and_word") if ids[k] in fts]
        assert keys == ["all", "rate_and_word"]
        got = qp._coverage(kq, [PARAGRAPHS[k] for k in keys])
        assert got == [pytest.approx(fts[ids[k]]) for k in keys]

    def test_a_text_without_the_words_covers_nothing_and_order_is_kept(self, seeded):
        client, _ = seeded
        qp = QueryProcessor(MagicMock(), client, summarizer=None, usage=MagicMock())
        kq = qp._keyword_query("Apa kata Zqbank soal ZQRATE dan zqputus?")
        got = qp._coverage(kq, ["Tidak ada kata kunci di sini.", PARAGRAPHS["all"], "zqputus saja"])
        assert got[0] == 0.0 and got[1] == pytest.approx(1.0) and 0 < got[2] < 1


class TestHoldsSubjectLive:
    """ADR-013 (SYS-138): a this-week FAISS hit leads the week window only when its paragraph holds
    the question's subject, tested by the same `to_tsvector('simple', ...)` as the keyword half."""

    def test_a_name_question_needs_one_of_its_names(self, seeded):
        client, _ = seeded
        qp = QueryProcessor(MagicMock(), client, summarizer=None, usage=MagicMock())
        kq = qp._keyword_query("Apa kata Zqbank soal ZQRATE dan zqputus?")
        assert sorted(kq.subject) == ["zqbank", "zqrate"]
        got = qp._holds_subject(kq, [PARAGRAPHS["word_only"], PARAGRAPHS["bank_only"],
                                     "Tidak ada kata kunci di sini.", PARAGRAPHS["rate_and_word"]])
        assert got == [False, True, False, True]

    def test_a_question_without_names_needs_one_of_its_anchors(self, seeded):
        client, _ = seeded
        qp = QueryProcessor(MagicMock(), client, summarizer=None, usage=MagicMock())
        kq = qp._keyword_query("bagaimana zqputus dan zqhasil")
        assert kq.names == [] and sorted(kq.subject) == ["zqhasil", "zqputus"]
        got = qp._holds_subject(kq, ["Kabar zqhasil saja.", "Tidak ada kata kunci di sini."])
        assert got == [True, False]
