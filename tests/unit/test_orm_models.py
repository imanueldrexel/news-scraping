"""
Regression tests for ORM model type mismatches.

Bug 8: ChunksTable.is_first_chunk / is_last_chunk were Column(Integer)
       but the DB column is BOOLEAN. ORM was sending int 1/0 instead of bool.

Bug 9: NewsArticlesTable.is_embedded was Column(Integer) but the DB column
       is BOOLEAN. ORM was sending int instead of bool.
"""
import pytest
from newscrawler.infrastructure.datasource.dataflow.model.chunk_model import ChunkModel
from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import NewsDetailsModel
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import (
    ChunksTable,
    NewsArticlesTable,
)


def make_chunk_model(**kwargs):
    defaults = dict(
        sitemap_id=1,
        chunk_level=1,
        chunk_index=0,
        chunk_total=1,
        is_first_chunk=True,
        is_last_chunk=True,
        text_content="test",
        token_count=1,
    )
    defaults.update(kwargs)
    return ChunkModel(**defaults)


def make_details_model(**kwargs):
    defaults = dict(
        sitemap_id=1,
        extracted_text=["paragraph"],
        reporter=[],
        meta_data={},
        is_embedded=True,
    )
    defaults.update(kwargs)
    return NewsDetailsModel(**defaults)


class TestChunksTableBooleanFields:
    """Bug 8: is_first_chunk and is_last_chunk must be stored as bool, not int."""

    def test_is_first_chunk_stored_as_bool_when_true(self):
        entry = ChunksTable(make_chunk_model(is_first_chunk=True))
        assert isinstance(entry.is_first_chunk, bool), (
            f"BUG 8: is_first_chunk should be bool, got {type(entry.is_first_chunk).__name__}"
        )
        assert entry.is_first_chunk is True

    def test_is_first_chunk_stored_as_bool_when_false(self):
        entry = ChunksTable(make_chunk_model(is_first_chunk=False, chunk_index=1))
        assert isinstance(entry.is_first_chunk, bool)
        assert entry.is_first_chunk is False

    def test_is_last_chunk_stored_as_bool_when_true(self):
        entry = ChunksTable(make_chunk_model(is_last_chunk=True))
        assert isinstance(entry.is_last_chunk, bool), (
            f"BUG 8: is_last_chunk should be bool, got {type(entry.is_last_chunk).__name__}"
        )
        assert entry.is_last_chunk is True

    def test_is_last_chunk_stored_as_bool_when_false(self):
        entry = ChunksTable(make_chunk_model(is_last_chunk=False, chunk_index=0, chunk_total=2))
        assert isinstance(entry.is_last_chunk, bool)
        assert entry.is_last_chunk is False

    def test_is_first_chunk_column_type_is_boolean(self):
        from sqlalchemy import Boolean
        col = ChunksTable.__table__.c.is_first_chunk
        assert isinstance(col.type, Boolean), (
            f"BUG 8: is_first_chunk column type should be Boolean, got {type(col.type).__name__}"
        )

    def test_is_last_chunk_column_type_is_boolean(self):
        from sqlalchemy import Boolean
        col = ChunksTable.__table__.c.is_last_chunk
        assert isinstance(col.type, Boolean), (
            f"BUG 8: is_last_chunk column type should be Boolean, got {type(col.type).__name__}"
        )


class TestArticlesTableBooleanFields:
    """Bug 9: is_embedded must be stored as bool, not int."""

    def test_is_embedded_stored_as_bool_when_true(self):
        entry = NewsArticlesTable(make_details_model(is_embedded=True))
        assert isinstance(entry.is_embedded, bool), (
            f"BUG 9: is_embedded should be bool, got {type(entry.is_embedded).__name__}"
        )
        assert entry.is_embedded is True

    def test_is_embedded_stored_as_bool_when_false(self):
        entry = NewsArticlesTable(make_details_model(is_embedded=False))
        assert isinstance(entry.is_embedded, bool)
        assert entry.is_embedded is False

    def test_is_embedded_column_type_is_boolean(self):
        from sqlalchemy import Boolean
        col = NewsArticlesTable.__table__.c.is_embedded
        assert isinstance(col.type, Boolean), (
            f"BUG 9: is_embedded column type should be Boolean, got {type(col.type).__name__}"
        )
