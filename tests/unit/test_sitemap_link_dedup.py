"""
SYS-29: save_sitemaps must dedup on link alone, not (link, posted_at).

SYS-11 changed how posted_at is derived (00:00-06:59 WIB articles moved forward
one day). With the old (link, posted_at) key, every such article already stored
and still listed by its site dedup-missed on the next crawl and got a second
sitemaps row -> second articles row -> duplicate chunks and FAISS vectors
(3,817 rows waiting on 2026-09-18). A URL identifies an article; the date was
never part of its identity. No database: the session factory is a mock.
"""
from datetime import datetime
from unittest.mock import MagicMock

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
    SQLAlchemySitemapDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _data_source(existing_rows=()):
    client = SQLAlchemyClient()  # create_engine is lazy; no connection is opened
    session = MagicMock(name="session")
    session.query.return_value.filter.return_value.all.return_value = list(existing_rows)
    client.Session = MagicMock(return_value=session)
    return SQLAlchemySitemapDataSource(client), session


def _existing(link, sitemap_id, posted_at=20260506):
    return MagicMock(link=link, sitemap_id=sitemap_id, posted_at=posted_at)


def make_sitemap(link, posted_at=datetime(2026, 5, 7), source="CNBC"):
    return NewsSitemapModel(headline="h", link=link, sources=source, category="market",
                            posted_at=posted_at, keywords=None)


LINK = "https://www.cnbcindonesia.com/market/20260507061753-29-732911/x?page=all"


class TestStoredLinkIsNeverReinserted:
    def test_relisted_link_with_a_different_posted_at_reuses_the_stored_id(self):
        """The exact SYS-11 shape: stored 20260506 (old derivation), listed today
        as 20260507 (new derivation). Must be recognised, not inserted."""
        ds, session = _data_source([_existing(LINK, 8478, posted_at=20260506)])

        result = ds.save_sitemaps([make_sitemap(LINK, posted_at=datetime(2026, 5, 7))])

        assert [s.sitemap_id for s in result] == [8478]
        assert result.new_count == 0
        session.add.assert_not_called()

    def test_relisted_link_with_the_same_posted_at_still_reuses_the_stored_id(self):
        ds, session = _data_source([_existing(LINK, 8478, posted_at=20260507)])

        result = ds.save_sitemaps([make_sitemap(LINK, posted_at=datetime(2026, 5, 7))])

        assert [s.sitemap_id for s in result] == [8478]
        assert result.new_count == 0
        session.add.assert_not_called()

    def test_stored_row_is_left_untouched_when_the_date_moved(self):
        """Decision recorded on SYS-29: an existing row's posted_at is first-seen,
        not refreshed -- articles.meta_data.posted_at was derived the same way at
        save time and would otherwise disagree with its sitemap, and re-stamping
        sites (OKEZONE) would churn the value every crawl. No UPDATE, no add."""
        ds, session = _data_source([_existing(LINK, 8478, posted_at=20260506)])

        ds.save_sitemaps([make_sitemap(LINK, posted_at=datetime(2026, 5, 7))])

        session.add.assert_not_called()
        session.execute.assert_not_called()

    def test_a_genuinely_new_link_is_still_inserted(self):
        ds, session = _data_source([_existing(LINK, 8478)])

        result = ds.save_sitemaps([make_sitemap(LINK), make_sitemap("https://x/new")])

        assert result.new_count == 1
        assert session.add.call_count == 1
        assert session.add.call_args[0][0].link == "https://x/new"


class TestSameLinkTwiceInOneBatch:
    def test_two_entries_for_one_link_with_different_dates_insert_once(self):
        """A site listing the same URL under two dates in one sitemap (OKEZONE
        re-stamps) must produce one row, and both DTOs get that row's id."""
        ds, session = _data_source([])
        session.add.side_effect = lambda entry: setattr(entry, "sitemap_id", 501)

        result = ds.save_sitemaps([
            make_sitemap(LINK, posted_at=datetime(2026, 5, 6)),
            make_sitemap(LINK, posted_at=datetime(2026, 5, 7)),
        ])

        assert session.add.call_count == 1
        assert result.new_count == 1
        assert [s.sitemap_id for s in result] == [501, 501]


class TestLookupIsByLinkNotByDateWindow:
    def test_prefetch_filters_on_link_membership_only(self):
        """With a link-only key, a date-window pre-fetch (posted_at >= earliest in
        batch) would miss exactly the SYS-11 rows -- stored a day EARLIER than
        anything in the batch -- and the insert would then hit sitemaps_link_uq.
        The pre-fetch has to be by link."""
        ds, session = _data_source([])

        ds.save_sitemaps([make_sitemap(LINK)])

        (criterion,), _ = session.query.return_value.filter.call_args
        rendered = str(criterion)
        assert "sitemaps.link IN" in rendered, rendered
        assert "posted_at" not in rendered, rendered
        assert "sources" not in rendered, rendered

    def test_prefetch_selects_link_and_id(self):
        ds, session = _data_source([])

        ds.save_sitemaps([make_sitemap(LINK)])

        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import SitemapTable
        selected = [c.key for c in session.query.call_args[0]]
        assert selected == [SitemapTable.link.key, SitemapTable.sitemap_id.key]

    def test_large_batches_are_looked_up_in_chunks_covering_every_link(self):
        """VIVA lists 2,500+ URLs in one save_sitemaps call; the lookup is chunked
        and every link must be covered -- a truncated lookup would re-insert the
        tail of the batch."""
        ds, session = _data_source([])
        n = SQLAlchemySitemapDataSource.LINK_LOOKUP_CHUNK * 2 + 5
        links = [f"https://x/{i}" for i in range(n)]

        ds.save_sitemaps([make_sitemap(l) for l in links])

        calls = session.query.return_value.filter.call_args_list
        assert len(calls) == 3
        looked_up = set()
        for (criterion,), _ in calls:
            looked_up.update(criterion.right.value)
        assert looked_up == set(links)


class TestFindExistingByLink:
    def test_returns_link_to_id_map_for_stored_links_only(self):
        ds, _ = _data_source([_existing("https://x/a", 1), _existing("https://x/b", 2)])

        assert ds.find_existing_by_link(["https://x/a", "https://x/b", "https://x/c"]) == {
            "https://x/a": 1, "https://x/b": 2,
        }

    def test_empty_and_none_links_are_ignored_without_querying(self):
        ds, session = _data_source([])

        assert ds.find_existing_by_link([None, "", None]) == {}
        session.query.assert_not_called()

    def test_opens_its_own_session_when_none_is_given(self):
        ds, session = _data_source([])

        ds.find_existing_by_link(["https://x/a"])

        session.close.assert_called_once()
