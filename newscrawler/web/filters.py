"""The search page's filters (SYS-92 #261, SYS-100 #269).

A filter value comes from the reader's browser, so each is checked against a
closed set before it reaches retrieval: the topic against `filter_rubric`'s
news topics (the subject an article is filed under since SYS-37/SYS-40, not the
outlet's section), the portal against the outlets the copy table knows, dates
as ISO days. An unknown value is dropped and logged, never passed on.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from newscrawler.core import web_copy as copy
from newscrawler.core.filter_rubric import TOPIC_SOFT, TOPICS
from newscrawler.core.newsletter_copy import OUTLET_NAMES, outlet

logger = logging.getLogger(__name__)

# The topics a reader can filter by, in the newsletter's order (finance first). `soft` is
# never saved (SYS-37), so it is not an option.
TOPIC_CHOICES: Tuple[str, ...] = tuple(t for t in TOPICS if t != TOPIC_SOFT)
RANGE_DAYS = (7, 30)
RANGE_CUSTOM = "custom"


@dataclass(frozen=True)
class Filters:
    topic: Optional[str] = None
    source: Optional[str] = None
    days: Optional[int] = None          # a "7 hari" / "30 hari" chip
    date_from: Optional[date] = None    # "Pilih tanggal"
    date_to: Optional[date] = None

    @property
    def active(self) -> bool:
        return bool(self.topic or self.source or self.days or self.date_from or self.date_to)

    def bounds(self, today: date) -> Tuple[Optional[date], Optional[date]]:
        """The inclusive date range to search: the last N days end today."""
        if self.days:
            return today - timedelta(days=self.days - 1), today
        return self.date_from, self.date_to

    def chips(self) -> List[Tuple[str, str]]:
        """(field, label) of each active filter, for the removable chips under the search."""
        out = []
        if self.topic:
            out.append(("topic", copy.topic_name(self.topic)))
        if self.source:
            out.append(("source", outlet(self.source)))
        rentang = copy.range_chip(self.days, self.date_from, self.date_to)
        if rentang:
            out.append(("rentang", rentang))
        return out

    def narrow_text(self) -> str:
        return copy.narrow(self.topic, self.source, self.days, self.date_from, self.date_to)

    def describe(self) -> str:
        """For the log line (internal names are fine there)."""
        return ",".join(f"{k}={v}" for k, v in (("topic", self.topic), ("source", self.source), ("days", self.days),
                                                ("from", self.date_from), ("to", self.date_to)) if v) or "none"


def _iso_day(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        logger.info(f"Ignoring a date filter that is not YYYY-MM-DD: {value!r}")
        return None


def parse(topic: Optional[str] = None, source: Optional[str] = None, rentang: Optional[str] = None,
          date_from: Optional[str] = None, date_to: Optional[str] = None) -> Filters:
    """Filters from raw form / JSON values. `rentang` is '' (all), '7', '30' or 'custom'.
    The form always sends it, and its date inputs keep their values while hidden, so
    the dates count only with 'custom'. None (a JSON caller that never sends it) means
    the explicit dates decide."""
    topic = (topic or "").strip() or None
    if topic is not None and topic not in TOPIC_CHOICES:
        logger.info(f"Ignoring an unknown topic filter: {topic!r}")
        topic = None
    source = (source or "").strip().upper() or None
    if source is not None and source not in OUTLET_NAMES:
        logger.info(f"Ignoring an unknown portal filter: {source!r}")
        source = None

    if rentang is not None:
        rentang = rentang.strip()
        if rentang.isdigit() and int(rentang) in RANGE_DAYS:
            return Filters(topic, source, days=int(rentang))
        if rentang != RANGE_CUSTOM:
            if rentang:
                logger.info(f"Ignoring an unknown date range: {rentang!r}")
            return Filters(topic, source)
    start, end = _iso_day(date_from), _iso_day(date_to)
    if start and end and start > end:
        start, end = end, start
    return Filters(topic, source, date_from=start, date_to=end)
