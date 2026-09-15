"""Tests for DateTimeReader.convert_date()."""
from datetime import timezone, timedelta
import pytest
from newscrawler.domain.utils.date_time_reader import DateTimeReader

GMT7 = timezone(timedelta(hours=7))
UTC0 = timezone(timedelta(hours=0))


class TestDateTimeReaderConvertDate:
    def setup_method(self):
        self.reader = DateTimeReader()

    def test_DT01_utc_input_converts_to_gmt7(self):
        dt = DateTimeReader.convert_date("2024-01-01T12:00:00Z")
        assert dt.utcoffset() == timedelta(hours=7)
        assert dt.hour == 19

    def test_DT02_no_timezone_treated_as_gmt7(self):
        dt = DateTimeReader.convert_date("2024-01-01T12:00:00")
        assert dt.utcoffset() == timedelta(hours=7)
        assert dt.hour == 12

    def test_DT03_gmt7_input_stays_gmt7(self):
        dt = DateTimeReader.convert_date("2024-01-01T12:00:00+07:00")
        assert dt.utcoffset() == timedelta(hours=7)
        assert dt.hour == 12

    def test_DT04_utc_plus_0_converts_to_gmt7(self):
        dt = DateTimeReader.convert_date("2024-01-01T05:00:00+00:00")
        assert dt.astimezone(GMT7).hour == 12

    def test_DT05_return_value_has_tzinfo(self):
        dt = DateTimeReader.convert_date("2024-06-15T08:00:00Z")
        assert dt.tzinfo is not None

    def test_DT06_return_value_offset_is_gmt7(self):
        dt = DateTimeReader.convert_date("2024-06-15T08:00:00Z")
        assert dt.utcoffset() == timedelta(hours=7)

    def test_DT07_crawler_astimezone_converts_to_utc0(self):
        dt = DateTimeReader.convert_date("2024-01-01T19:00:00+07:00")
        utc_dt = dt.astimezone(self.reader.gmt_offset)
        assert utc_dt.hour == 12
        assert utc_dt.utcoffset() == timedelta(hours=0)
