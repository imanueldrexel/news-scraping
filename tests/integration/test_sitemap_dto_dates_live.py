"""SYS-90 (#255) against a live PostgreSQL: a sitemap saved and read back as a DTO
keeps its day, and the article saved from that DTO stores posted_at = that day
(not 19700823, which pydantic 2's int-as-Unix-seconds coercion produced)."""
from datetime import datetime, timedelta, timezone

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "SYS90TEST"
WIB = timezone(timedelta(hours=7))


@pytest.fixture
def ds_and_client():
    from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import NewsDataSource
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    try:
        with client.get_session() as s:
            assert s.execute(text("SELECT current_database()")).scalar() == "newsaggregator_test"
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield NewsDataSource(client), client
    with client.get_session() as s:
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources = :s)"),
                  {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def test_save_then_article_keeps_the_day(ds_and_client):
    from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
    from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
    from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl
    ds, client = ds_and_client
    listed = SitemapDTO(headline="Berita", link=f"https://sys90.example.test/{datetime.now().timestamp()}",
                        sources=SOURCE, category="news", timestamp=datetime(2026, 9, 18, 9, 30, tzinfo=WIB))

    saved = ds.save_sitemap([DataFlowRepositoryImpl._to_sitemap_data_model(listed)])
    (dto,) = [DataFlowRepositoryImpl._to_sitemap_dto(m) for m in saved]      # what save_sitemap_data returns
    assert dto.timestamp.date() == datetime(2026, 9, 18).date()

    article = DataFlowRepositoryImpl._to_newsdetail_data_model(
        NewsDetailsDTO(sitemap_id=dto.sitemap_id, extracted_text=["Isi berita."], reporter=[],
                       meta_data={"posted_at": dto.timestamp}))
    ds.save_newsdetails([article])
    with client.get_session() as s:
        stored = s.execute(text("SELECT meta_data->>'posted_at' FROM articles WHERE sitemap_id = :id"),
                           {"id": dto.sitemap_id}).scalar()
    assert stored == "20260918"


def test_the_repair_script_puts_the_day_back_and_restores(ds_and_client, tmp_path, capsys):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import repair_article_posted_at as script
    _, client = ds_and_client
    with client.get_session() as s:
        sid = s.execute(text("INSERT INTO sitemaps (headline, link, sources, category, posted_at) VALUES "
                             "('h', :link, :src, 'news', 20260919) RETURNING sitemap_id"),
                        {"link": f"https://sys90.example.test/r{datetime.now().timestamp()}", "src": SOURCE}).scalar()
        s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, meta_data) VALUES "
                       "(:id, 'x', CAST(:meta AS jsonb))"),
                  {"id": sid, "meta": '{"posted_at": 19700823, "title": "h"}'})
        s.commit()

    def meta():
        with client.get_session() as s:
            return s.execute(text("SELECT meta_data FROM articles WHERE sitemap_id = :id"), {"id": sid}).scalar()

    assert script.main(["--backup-dir", str(tmp_path)]) == 0
    assert meta()["posted_at"] == 19700823                                        # dry run writes nothing
    assert script.main(["--apply", "--backup-dir", str(tmp_path)]) == 0
    assert meta() == {"posted_at": 20260919, "title": "h"}                        # only posted_at changed
    (backup,) = tmp_path.glob("sys90_posted_at_*.json")
    assert script.main(["--restore", str(backup)]) == 0
    assert meta()["posted_at"] == 19700823
