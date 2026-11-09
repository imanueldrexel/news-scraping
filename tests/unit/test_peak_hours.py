"""SYS-39 (#125): SumoPod DeepSeek's peak window (UTC weekdays 01:00-04:00 and
06:00-10:00, weekends off-peak) and the price of a call."""
from datetime import datetime, timedelta, timezone

import pytest

from newscrawler.core import peak_hours
from newscrawler.core.peak_hours import cost_usd, is_peak, next_off_peak


def _utc(day, hour, minute=0):
    # 2026-10-05 is a Monday, 2026-10-03 a Saturday, 2026-10-04 a Sunday
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


class TestIsPeak:
    @pytest.mark.parametrize("hour", [1, 2, 3, 6, 7, 8, 9])
    def test_the_peak_hours_of_a_weekday(self, hour):
        assert is_peak(_utc(5, hour))
        assert is_peak(_utc(5, hour, 59))

    @pytest.mark.parametrize("hour", [0, 4, 5, 10, 11, 12, 18, 23])
    def test_the_other_hours_of_a_weekday(self, hour):
        assert not is_peak(_utc(5, hour))

    def test_the_blocks_are_half_open(self):
        assert not is_peak(_utc(5, 0, 59)) and is_peak(_utc(5, 1, 0))
        assert is_peak(_utc(5, 3, 59)) and not is_peak(_utc(5, 4, 0))
        assert is_peak(_utc(5, 9, 59)) and not is_peak(_utc(5, 10, 0))

    @pytest.mark.parametrize("day", [3, 4])
    def test_a_weekend_is_off_peak_all_day(self, day):
        assert not any(is_peak(_utc(day, h)) for h in range(24))

    def test_the_weekday_is_the_utc_weekday(self):
        """Friday 23:00 UTC is Saturday 06:00 WIB; Monday 00:30 UTC is already Monday."""
        assert not is_peak(_utc(3, 7))                      # Saturday 07:00 UTC
        assert is_peak(datetime(2026, 10, 9, 7, tzinfo=timezone.utc))   # Friday 07:00 UTC

    def test_another_timezone_is_converted(self):
        wib = timezone(timedelta(hours=7))
        assert is_peak(datetime(2026, 10, 5, 14, 0, tzinfo=wib))        # 07:00 UTC Monday
        assert not is_peak(datetime(2026, 10, 5, 19, 0, tzinfo=wib))    # 12:00 UTC Monday

    def test_a_naive_time_is_utc(self):
        assert is_peak(datetime(2026, 10, 5, 7, 0))

    def test_no_argument_uses_the_clock(self):
        assert isinstance(is_peak(), bool)


class TestNextOffPeak:
    def test_off_peak_now_is_now(self):
        assert next_off_peak(_utc(5, 12, 30)) == _utc(5, 12, 30)

    def test_inside_the_morning_block_it_is_the_end_of_that_block(self):
        assert next_off_peak(_utc(5, 7, 15)) == _utc(5, 10, 0)

    def test_inside_the_early_block(self):
        assert next_off_peak(_utc(5, 1, 0)) == _utc(5, 4, 0)

    def test_the_result_is_off_peak(self):
        for h in range(24):
            assert not is_peak(next_off_peak(_utc(5, h, 20)))


class TestCost:
    def test_off_peak_price(self):
        # $0.15 in, $0.60 out per 1M tokens
        assert cost_usd(1_000_000, 1_000_000, peak=False) == pytest.approx(0.75)

    def test_peak_price_is_double(self):
        assert cost_usd(1_000_000, 1_000_000, peak=True) == pytest.approx(1.50)

    def test_input_and_output_are_priced_apart(self):
        assert cost_usd(1_000_000, 0, peak=False) == pytest.approx(0.15)
        assert cost_usd(0, 1_000_000, peak=False) == pytest.approx(0.60)
        assert cost_usd(0, 1_000_000, peak=True) == pytest.approx(1.20)

    def test_an_article_costs_a_fraction_of_a_cent(self):
        # the PM estimate: ~760 in, ~300 out -> $0.000294 off-peak
        assert cost_usd(760, 300, peak=False) == pytest.approx(0.000294)

    def test_nothing_costs_nothing(self):
        assert cost_usd(0, 0, peak=True) == 0

    def test_the_prices_come_from_the_constants(self, monkeypatch):
        monkeypatch.setattr(peak_hours, "KNOWLEDGE_PRICE_INPUT_OFFPEAK", 1.0)
        monkeypatch.setattr(peak_hours, "KNOWLEDGE_PRICE_OUTPUT_OFFPEAK", 2.0)
        assert cost_usd(1_000_000, 1_000_000, peak=False) == pytest.approx(3.0)
