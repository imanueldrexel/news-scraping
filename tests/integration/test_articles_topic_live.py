"""
SYS-37 (#121): articles.topic / topic_confidence go through the real write path
(DataFlowRepositoryImpl.save_newsdetails_data -> pg_insert) against the real
schema (scripts/migrate_articles_topic.sql), and read back. The ORM and the
migration are kept in sync by hand -- this is the test that notices when they
are not (the DatatypeMismatch trap in CLAUDE.md).
"""
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "SYS37TOPIC"


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
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources = :s)"), {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _seed_sitemap(client):
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
                 "VALUES ('h', :l, :s, 'bisnis', 20260922, 'pending') RETURNING sitemap_id"),
            {"l": f"https://sys37.test/{uuid.uuid4().hex}", "s": SOURCE},
        ).scalar()
        s.commit()
    return sid


class TestArticlesTopicLive:
    def test_topic_and_confidence_are_written_and_read_back(self, client):
        from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
            SQLAlchemyArticleDataSource,
        )
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl

        with_topic = _seed_sitemap(client)
        without = _seed_sitemap(client)
        dtos = [
            NewsDetailsDTO(sitemap_id=with_topic, extracted_text=["Harga minyak turun."], reporter=[],
                           meta_data={"title": "t", "posted_at": 20260922}, topic="commodities_energy", topic_confidence=0.83),
            NewsDetailsDTO(sitemap_id=without, extracted_text=["Body."], reporter=[], meta_data={"title": "u", "posted_at": 20260922}),
        ]
        models = DataFlowRepositoryImpl._to_newsdetail_data_model(dtos[0]), DataFlowRepositoryImpl._to_newsdetail_data_model(dtos[1])
        assert (models[0].topic, models[0].topic_confidence) == ("commodities_energy", 0.83)
        assert (models[1].topic, models[1].topic_confidence) == (None, None)

        saved = SQLAlchemyArticleDataSource(client).save_newsdetails(list(models))
        assert sorted(saved) == sorted([with_topic, without])

        with client.get_session() as s:
            got = {r[0]: (r[1], r[2]) for r in s.execute(
                text("SELECT sitemap_id, topic, topic_confidence FROM articles WHERE sitemap_id = ANY(:ids)"),
                {"ids": [with_topic, without]}).fetchall()}
        assert got[with_topic][0] == "commodities_energy" and abs(got[with_topic][1] - 0.83) < 1e-6
        assert got[without] == (None, None)


class TestChunksArticleIdLinkLive:
    """DBT-11 (#46): chunks are saved before the articles row exists, so
    save_newsdetails links chunks.article_id right after the insert. Real
    table: two chunk rows with NULL article_id, one article saved -> both
    linked; a chunk of another sitemap untouched."""

    def test_save_newsdetails_links_the_batch_chunks(self, client):
        from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
            SQLAlchemyArticleDataSource,
        )
        from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl

        sid = _seed_sitemap(client)
        other = _seed_sitemap(client)
        with client.get_session() as s:
            for target, idx in ((sid, 0), (sid, 1), (other, 0)):
                s.execute(text("INSERT INTO chunks (sitemap_id, article_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                               "is_last_chunk, text_content, token_count, embedding_id, chunk_status) "
                               "VALUES (:sid, NULL, 2, :ix, 2, false, false, 't', 5, 'e', 'embedded')"), {"sid": target, "ix": idx})
            s.commit()

        model = DataFlowRepositoryImpl._to_newsdetail_data_model(
            NewsDetailsDTO(sitemap_id=sid, extracted_text=["Body."], reporter=[], meta_data={"title": "t", "posted_at": 20260922}))
        assert SQLAlchemyArticleDataSource(client).save_newsdetails([model]) == [sid]

        with client.get_session() as s:
            aid = s.execute(text("SELECT articles_id FROM articles WHERE sitemap_id = :sid"), {"sid": sid}).scalar()
            linked = s.execute(text("SELECT article_id FROM chunks WHERE sitemap_id = :sid ORDER BY chunk_index"), {"sid": sid}).fetchall()
            untouched = s.execute(text("SELECT article_id FROM chunks WHERE sitemap_id = :sid"), {"sid": other}).scalar()
            s.execute(text("DELETE FROM chunks WHERE sitemap_id IN (:a, :b)"), {"a": sid, "b": other})
            s.commit()
        assert [r.article_id for r in linked] == [aid, aid]
        assert untouched is None
