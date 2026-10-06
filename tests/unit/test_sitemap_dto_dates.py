"""SYS-90 (#255) / DBT-01 (#20): a SitemapDTO's timestamp under pydantic 2.

sitemaps.posted_at is an int yyyymmdd. Given to a `datetime` field, pydantic 2 reads
an int as Unix seconds -- 20260918 became 1970-08-23, and the article saved from
that DTO got meta_data.posted_at 19700823 (193 CNBC rows, from a script that built
DTOs from stored rows). And `timestamp: datetime = None` rejected an explicit None.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO, posted_at_datetime
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl


@pytest.mark.parametrize("value,expected", [
    (20260918, datetime(2026, 9, 18)),
    (None, None),
    (datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc), datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc)),
    (1758200000, 1758200000),                 # not a yyyymmdd: left to pydantic (Unix seconds, as before)
])
def test_posted_at_datetime(value, expected):
    assert posted_at_datetime(value) == expected


def test_a_stored_int_date_is_that_day_not_unix_seconds():
    dto = SitemapDTO(headline="h", link="l", sources="CNBC", timestamp=20260918)
    assert dto.timestamp == datetime(2026, 9, 18)


def test_an_explicit_none_timestamp_is_accepted():
    """DBT-01: pydantic 1 made `datetime = None` Optional; pydantic 2 does not."""
    assert SitemapDTO(headline="h", link="l", sources="CNBC", timestamp=None).timestamp is None


def test_a_dto_from_a_stored_row_saves_its_article_with_that_day():
    """The chain that wrote 19700823: stored row -> DTO -> the article's meta_data.posted_at."""
    row = SimpleNamespace(headline="h", link="l", sources="CNBC", category="news", posted_at=20260918,
                          keywords=None, sitemap_id=7)
    dto = DataFlowRepositoryImpl._to_sitemap_dto(row)
    assert dto.timestamp.date() == datetime(2026, 9, 18).date()
    article = DataFlowRepositoryImpl._to_newsdetail_data_model(
        NewsDetailsDTO(sitemap_id=7, extracted_text=["Body."], reporter=[], meta_data={"posted_at": dto.timestamp}))
    assert article.meta_data["posted_at"] == 20260918
