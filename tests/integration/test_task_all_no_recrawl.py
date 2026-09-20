"""
SYS-07 (reopened) against a live PostgreSQL: task='all' must not re-crawl and
re-save articles for sitemaps it has already listed on a prior run. Before the fix,
crawl_website("all") handed crawl_sitemaps' own return value (every currently-listed
sitemap, existing rows included) straight into crawl_newsdetails(specific_sitemaps=
...), bypassing load_all_sitemaps' "no articles row yet" filter entirely -- so every
run re-fetched and re-saved every URL a site lists. The fix makes crawl_website("all")
call crawl_newsdetails with no specific_sitemaps, so it loads from the DB instead
(same path task="full_text" already uses).

This test exercises the real write path (NewsDataSource / SQLAlchemyArticleDataSource
/ SQLAlchemySitemapDataSource against newsaggregator_test) without going over the
network or through the embedding model -- it simulates what a full_text crawl does to
sitemaps.sitemaps and articles directly, the same way the SYS-07 QA re-audit's
original regression repro did.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

from newscrawler.core.importance_filter import FilterDecision  # noqa: E402

WIB = timezone(timedelta(hours=7))
SOURCE = "SYS07ALLTEST"


@pytest.fixture
def ds_and_client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import NewsDataSource
    client = SQLAlchemyClient()
    try:
        with client.get_session() as s:
            assert s.execute(text("SELECT current_database()")).scalar() == "newsaggregator_test"
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    ds = NewsDataSource(client)
    yield ds, client
    with client.get_session() as s:
        s.execute(
            text(
                "DELETE FROM articles WHERE sitemap_id IN "
                "(SELECT sitemap_id FROM sitemaps WHERE sources = :s)"
            ),
            {"s": SOURCE},
        )
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _sitemap_model(link, posted_at):
    from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
    return NewsSitemapModel(headline=link, link=link, sources=SOURCE, category="news",
                            posted_at=posted_at, keywords=None)


def _newsdetail_model(sitemap_id):
    from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import NewsDetailsModel
    return NewsDetailsModel(sitemap_id=sitemap_id, extracted_text=["Body text."], reporter=[], meta_data={})


def _articles_count(client):
    with client.get_session() as s:
        return s.execute(
            text(
                "SELECT COUNT(*) FROM articles a JOIN sitemaps s ON a.sitemap_id = s.sitemap_id "
                "WHERE s.sources = :s"
            ),
            {"s": SOURCE},
        ).scalar()


class TestTaskAllDoesNotReCrawlAlreadyArticledSitemaps:
    def test_second_all_run_produces_the_same_article_count_as_the_first(self, ds_and_client):
        ds, client = ds_and_client
        run = uuid.uuid4().hex[:8]
        links = [f"http://sys07all.test/{run}/{i}" for i in range(3)]
        day = lambda d: datetime(2026, 9, d, 12, 0, tzinfo=WIB)

        # --- "Run 1" of task=all ---
        # step 1: sitemap crawl lists the 3 URLs (none exist yet)
        saved_1 = ds.save_sitemap([_sitemap_model(links[i], day(10 + i)) for i in range(3)])
        assert len(saved_1) == 3

        # step 2 (the fix): crawl_newsdetails with no specific_sitemaps loads the
        # filtered set from the DB, same as task=full_text would.
        eligible_1 = ds.sql_alchemy_sitemap.load_all_sitemaps(website=SOURCE, n_limit=1000)
        assert {r.link for r in eligible_1} == set(links), "all 3 should be eligible on run 1"
        for row in eligible_1:
            ds.save_newsdetails([_newsdetail_model(row.sitemap_id)])

        assert _articles_count(client) == 3

        # --- "Run 2" of task=all (same site listing the same 3 URLs again) ---
        saved_2 = ds.save_sitemap([_sitemap_model(links[i], day(10 + i)) for i in range(3)])
        assert len(saved_2) == 3  # save_sitemaps still returns all 3 (existing, matched via dedup)
        assert {s.sitemap_id for s in saved_1} == {s.sitemap_id for s in saved_2}, \
            "re-listing must match the same rows, not create new ones"

        eligible_2 = ds.sql_alchemy_sitemap.load_all_sitemaps(website=SOURCE, n_limit=1000)
        assert eligible_2 == [], "all 3 already have an articles row -- none should be re-selected"
        for row in eligible_2:
            ds.save_newsdetails([_newsdetail_model(row.sitemap_id)])  # should not run at all

        assert _articles_count(client) == 3, "run 2 must not have added or duplicated any article"

    def test_crawler_api_all_task_wires_the_two_steps_together(self, ds_and_client):
        """End-to-end through CrawlerAPI/CrawlerServiceImpl.crawl_website(task='all'),
        with the network-facing Crawler and the embedding/chunking step mocked out,
        proving the routing fix (no specific_sitemaps) actually reaches the DB-backed
        no-article filter rather than being tested only via direct datasource calls."""
        from unittest.mock import MagicMock, patch
        from newscrawler.application.api.crawler_api import CrawlerAPI
        from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO

        ds, client = ds_and_client
        run = uuid.uuid4().hex[:8]
        links = [f"http://sys07all.test/{run}/{i}" for i in range(3)]
        day = lambda d: datetime(2026, 9, d, 12, 0, tzinfo=WIB)

        class _FakeRepo:
            """Real sitemap/article persistence (newsaggregator_test), fake chunk
            storage (no FAISS/embedding model) -- isolates the routing fix."""

            def __init__(self, ds):
                self.ds = ds

            def load_sitemap_data(self, website, n_limit):
                from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
                    DataFlowRepositoryImpl,
                )
                rows = self.ds.load_sitemap(website=website, n_limit=n_limit)
                return [DataFlowRepositoryImpl._to_sitemap_dto(r) for r in rows]

            def save_sitemap_data(self, sitemaps):
                from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
                    DataFlowRepositoryImpl,
                )
                models = [DataFlowRepositoryImpl._to_sitemap_data_model(s) for s in sitemaps]
                saved = self.ds.save_sitemap(models)
                return [DataFlowRepositoryImpl._to_sitemap_dto(m) for m in saved]

            def save_newsdetails_data(self, newsdetails):
                for n in newsdetails:
                    self.ds.save_newsdetails([_newsdetail_model(n.sitemap_id)])

            def save_chunk_data(self, chunks):
                return list({c.sitemap_id for c in chunks})

            def mark_sitemaps_attempted(self, sitemap_ids):
                self.ds.mark_sitemaps_attempted(sitemap_ids)

            def log_crawl_start(self, website, task):
                return self.ds.sql_alchemy_article.log_crawl_start(website, task)

            def log_crawl_complete(self, log_id, article_count=0):
                self.ds.sql_alchemy_article.log_crawl_complete(log_id, article_count)

            def log_crawl_failed(self, log_id, error_msg):
                self.ds.sql_alchemy_article.log_crawl_failed(log_id, error_msg)

        fake_repo = _FakeRepo(ds)
        with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter") as MockFilter:
            service = CrawlerServiceImpl(data_flow_repo=fake_repo)
        service.semantic_filter.classify.return_value = FilterDecision(True, "score", True)
        service.chunker = MagicMock()
        service.chunker.chunk.return_value = [MagicMock(sitemap_id=None)]

        mock_crawler = MagicMock()
        mock_crawler.get_news_in_bulk.return_value = ["raw"] * 3
        mock_crawler.batch_crawling_sitemap.return_value = [
            SitemapDTO(headline=links[i], link=links[i], sources=SOURCE, timestamp=day(10 + i))
            for i in range(3)
        ]

        def fake_batch_crawling_details(news, website_name):
            for n in news:
                service.chunker.chunk.return_value = [MagicMock(sitemap_id=n.sitemap_id)]
            return [
                NewsDetailsDTO(
                    sitemap_id=n.sitemap_id,
                    extracted_text=["Body text about the economy."],
                    meta_data={"title": "t"},
                    reporter=[],
                )
                for n in news
            ]

        mock_crawler.batch_crawling_details.side_effect = fake_batch_crawling_details
        service.crawler_dict = {SOURCE: mock_crawler}

        api = CrawlerAPI(service)

        api.crawl_website(website_name=SOURCE, task="all")
        assert _articles_count(client) == 3

        # Run 2: same site, same listing -- must not duplicate.
        mock_crawler.batch_crawling_details.reset_mock()
        api.crawl_website(website_name=SOURCE, task="all")
        assert _articles_count(client) == 3, "run 2 must not add duplicate articles"
        mock_crawler.batch_crawling_details.assert_not_called(), \
            "no eligible sitemaps left -- full-text crawl must not run at all on run 2"
