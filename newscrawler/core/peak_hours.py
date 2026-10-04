"""SumoPod's DeepSeek peak window and the price of a call (SYS-39 #125).

Owner-supplied 2026-10-04: per 1M tokens, input $0.15 off-peak / $0.30 peak and
output $0.60 / $1.20. Peak (UTC) is weekdays 01:00-04:00 and 06:00-10:00
(08:00-11:00 and 13:00-17:00 WIB); weekends are off-peak all day. Chinese public
holidays are also off-peak at the provider; they are not modelled here, so on one
the run waits for a window the provider would not have charged extra for (it
costs time, never money).

Prices are env-overridable (constants.py) so a changed price list is a config
change. Everything here is pure: the caller passes the clock.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from newscrawler.core.constants import (
    KNOWLEDGE_PRICE_INPUT_OFFPEAK,
    KNOWLEDGE_PRICE_INPUT_PEAK,
    KNOWLEDGE_PRICE_OUTPUT_OFFPEAK,
    KNOWLEDGE_PRICE_OUTPUT_PEAK,
)

# [start, end) UTC hours of a weekday.
PEAK_BLOCKS_UTC: Tuple[Tuple[int, int], ...] = ((1, 4), (6, 10))


def _utc(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)


def is_peak(now: Optional[datetime] = None) -> bool:
    """True when `now` (naive means UTC) falls in a peak block of a weekday (UTC)."""
    t = _utc(now)
    return t.weekday() < 5 and any(start <= t.hour < end for start, end in PEAK_BLOCKS_UTC)


def next_off_peak(now: Optional[datetime] = None) -> datetime:
    """The first minute at or after `now` that is off-peak (UTC, aware)."""
    t = _utc(now).replace(second=0, microsecond=0)
    while is_peak(t):
        t = (t + timedelta(hours=1)).replace(minute=0)
    return t


def cost_usd(input_tokens: int, output_tokens: int, peak: bool) -> float:
    """Dollars for one call at the window's price."""
    price_in = KNOWLEDGE_PRICE_INPUT_PEAK if peak else KNOWLEDGE_PRICE_INPUT_OFFPEAK
    price_out = KNOWLEDGE_PRICE_OUTPUT_PEAK if peak else KNOWLEDGE_PRICE_OUTPUT_OFFPEAK
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
