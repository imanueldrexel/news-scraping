"""SYS-90 (#255) / DBT-01 (#20): a SitemapDTO's timestamp under pydantic 2.

sitemaps.posted_at is an int yyyymmdd. Given to a `datetime` field, pydantic 2 reads
an int as Unix seconds -- 20260918 became 1970-08-23, and the article saved from
that DTO got meta_data.posted_at 19700823 (193 CNBC rows, from a script that built
DTOs from stored rows). And `timestamp: datetime = None` rejected an explicit None.
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO, posted_at_datetime
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl


@pytest.mark.parametrize("value,expected", [
    (20260918, datetime(2026, 9, 18)),
    (None, None),
    (datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc), datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc)),
    # DBT-60 (#258): the same date as text or a float (meta_data->>'posted_at', FAISS metadata)
    ("20260918", datetime(2026, 9, 18)),
    (" 20260918 ", datetime(2026, 9, 18)),
    (20260918.0, datetime(2026, 9, 18)),
    # DBT-60 send-back: every other numeric form of the date (QA 2026-10-13: each was 1970-08-23)
    ("20260918.0", datetime(2026, 9, 18)),          # str() of the float above
    ("+20260918", datetime(2026, 9, 18)),
    (Decimal("20260918"), datetime(2026, 9, 18)),   # psycopg2 returns NUMERIC as Decimal
    # a date string that is no number is pydantic's to parse
    ("2026-09-18T07:30:00+07:00", "2026-09-18T07:30:00+07:00"),
])
def test_posted_at_datetime(value, expected):
    assert posted_at_datetime(value) == expected


def test_a_numpy_scalar_is_read_as_a_yyyymmdd():
    """pandas.read_sql of sitemaps.posted_at hands numpy.int64 (a numbers.Integral)."""
    np = pytest.importorskip("numpy")
    assert posted_at_datetime(np.int64(20260918)) == datetime(2026, 9, 18)
    assert posted_at_datetime(np.float64(20260918.0)) == datetime(2026, 9, 18)


@pytest.mark.parametrize("value", [
    1758200000,             # Unix seconds: never accepted (it used to pass through to pydantic)
    "1758200000",
    1758200000.0,
    20260918.5,             # not an integral date
    "2026091",              # 7 digits
    -20260918,
    "20261318",             # month 13
    20260230,               # 30 February
    "1758200000.0",         # DBT-60 send-back: Unix seconds as the str of a float...
    Decimal("1758200000"),  # ...as a NUMERIC...
    "+1758200000",          # ...signed
    "NaN",                  # a number, but no date
    "Infinity",             # int() of it raises OverflowError, which pydantic would not turn into a refusal
    float("-inf"),
])
def test_a_number_that_is_not_a_yyyymmdd_is_refused(value):
    """DBT-60: a numeric posted_at is a yyyymmdd or an error, never Unix seconds and 1970."""
    with pytest.raises(ValueError):
        posted_at_datetime(value)


@pytest.mark.parametrize("timestamp", ["20260918", 20260918.0])
def test_the_dto_reads_the_text_and_float_forms_as_that_day(timestamp):
    """The ticket's repro: SitemapDTO(timestamp='20260918') was 1970-08-23."""
    assert SitemapDTO(headline="h", link="l", sources="CNBC", timestamp=timestamp).timestamp == datetime(2026, 9, 18)


@pytest.mark.parametrize("timestamp", ["1758200000", Decimal("1758200000"), True])
def test_the_dto_refuses_unix_seconds_and_a_bool(timestamp):
    """A bool is a numbers.Real too: it must reach pydantic's refusal, not the number path (where
    Decimal('True') would raise InvalidOperation, which pydantic does not turn into a ValidationError)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SitemapDTO(headline="h", link="l", sources="CNBC", timestamp=timestamp)


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
