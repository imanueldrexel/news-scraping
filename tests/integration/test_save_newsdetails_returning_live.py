"""DBT-19 (#69) / SYS-04 (#5): `save_newsdetails` returns the sitemap_ids that were
actually committed, not the ones handed in. `crawl_log.article_count` and the
'saved' crawl_status are driven by that list, so a row that violated a constraint,
or that hit `on_conflict_do_nothing`, must not be in it.

The service layer's half is guarded by unit tests; this is the SQL layer, against
the real schema (newsaggregator_test, articles_sitemap_id_uq), which a mock of
`save_newsdetails_data` never reaches: returning `[n.sitemap_id for n in newsdetails]`
or appending the id whatever RETURNING said left every earlier test green."""
import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

BAD_FK = -999999


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    return c


@pytest.fixture
def sitemap_ids(client):
    ids = []
    with client.get_session() as s:
        for n in range(2):
            ids.append(s.execute(text(
                "INSERT INTO sitemaps (headline, link, sources, posted_at) "
                "VALUES ('t', :link, 'DBT19', 20260916) RETURNING sitemap_id"),
                {"link": f"https://dbt19.test/returning-{n}"}).scalar())
        s.commit()
    yield ids
    with client.get_session() as s:
        s.execute(text("DELETE FROM articles WHERE sitemap_id = ANY(:ids)"), {"ids": ids})
        s.execute(text("DELETE FROM sitemaps WHERE sitemap_id = ANY(:ids)"), {"ids": ids})
        s.commit()


def _row(sitemap_id):
    from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import NewsDetailsModel
    return NewsDetailsModel(sitemap_id=sitemap_id, extracted_text=["para"], reporter=[], meta_data={},
                            is_embedded=False)


def _ds(client):
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
        SQLAlchemyArticleDataSource,
    )
    return SQLAlchemyArticleDataSource(client)


def _articles(client, sitemap_id):
    with client.get_session() as s:
        return s.execute(text("SELECT COUNT(*) FROM articles WHERE sitemap_id = :id"), {"id": sitemap_id}).scalar()


class TestSaveNewsdetailsReturnsWhatLanded:
    def test_a_batch_of_nothing_but_constraint_violations_returns_nothing(self, client):
        assert _ds(client).save_newsdetails([_row(BAD_FK), _row(BAD_FK - 1)]) == []

    def test_a_bad_row_among_good_ones_is_not_returned_and_the_good_one_is(self, client, sitemap_ids):
        good = sitemap_ids[0]
        assert _ds(client).save_newsdetails([_row(BAD_FK), _row(good)]) == [good]
        assert _articles(client, good) == 1

    def test_saving_the_same_row_again_returns_nothing_and_adds_no_row(self, client, sitemap_ids):
        """on_conflict_do_nothing persists nothing new: it must not count as saved."""
        good = sitemap_ids[0]
        ds = _ds(client)
        assert ds.save_newsdetails([_row(good)]) == [good]
        assert ds.save_newsdetails([_row(good)]) == []
        assert _articles(client, good) == 1

    def test_a_mixed_batch_returns_only_the_rows_that_landed_in_order(self, client, sitemap_ids):
        first, second = sitemap_ids
        ds = _ds(client)
        assert ds.save_newsdetails([_row(first)]) == [first]
        assert ds.save_newsdetails([_row(BAD_FK), _row(first), _row(second)]) == [second]
        assert (_articles(client, first), _articles(client, second)) == (1, 1)

    def test_an_empty_batch_returns_nothing(self, client):
        assert _ds(client).save_newsdetails([]) == []
