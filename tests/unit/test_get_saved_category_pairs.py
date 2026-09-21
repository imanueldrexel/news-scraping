"""DBT-32 (#141) item 4: SQLAlchemySitemapDataSource.get_saved_category_pairs
(SYS-34's baseline for the never-seen-category WARNING) must return the same
key shape the service builds -- `(source, lower(category) or "")` -- for a
NULL category too. The service normalises `None -> ""` on its side; if the
data source did not, a source with NULL categories would WARN on every save
of every run, and the mutation pass (M28) showed nothing pinned it."""
from unittest.mock import MagicMock

from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
    SQLAlchemySitemapDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _data_source(rows):
    client = SQLAlchemyClient()
    session = MagicMock(name="session")
    session.execute.return_value.fetchall.return_value = rows
    client.Session = MagicMock(return_value=session)
    return SQLAlchemySitemapDataSource(client), session


class TestGetSavedCategoryPairs:
    def test_null_category_becomes_the_empty_string_the_service_uses(self):
        ds, session = _data_source([("KOMPAS", None), ("KOMPAS", "nasional"), ("KOMPAS", "")])
        pairs = ds.get_saved_category_pairs("KOMPAS")
        assert pairs == {("KOMPAS", ""), ("KOMPAS", "nasional")}
        assert session.execute.call_args[0][1] == {"website": "KOMPAS"}
        # The SQL lower()s the category so the pair matches what the service
        # builds from the DTO (strip().lower()).
        assert "lower(" in str(session.execute.call_args[0][0]).lower()

    def test_service_side_key_for_a_null_category_matches(self):
        # The two halves of SYS-34's check agree on the NULL shape: a saved row
        # whose sitemap has no category is a known pair, not a warning.
        import logging
        meta = MagicMock(category=None, headline="h")
        known = {("KOMPAS", "")}
        logger = logging.getLogger("newscrawler.domain.services.crawler_service_impl")
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger.addHandler(handler)
        try:
            CrawlerServiceImpl._warn_on_unseen_categories("KOMPAS", [1], {1: meta}, known)
        finally:
            logger.removeHandler(handler)
        assert [r for r in records if r.levelno >= logging.WARNING] == []
        assert known == {("KOMPAS", "")}
