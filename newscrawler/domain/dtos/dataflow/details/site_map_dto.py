import re
from typing import List, Union, Optional
from datetime import datetime
from pydantic import field_validator
from pydantic.dataclasses import dataclass


_YYYYMMDD = re.compile(r"^\d{8}$")


def posted_at_datetime(value):
    """sitemaps.posted_at as a datetime: a stored yyyymmdd (SYS-11) is midnight of
    that day; a datetime or a date string (ISO) passes through, None stays None.

    SYS-90 (#255): pydantic 2 reads a number given to a `datetime` field as Unix
    seconds, so 20260918 became 1970-08-23 and 193 articles were saved with
    posted_at 19700823 by a script that built DTOs from stored rows. DBT-60 (#258):
    the same date arrives as text too (`meta_data->>'posted_at'`, the FAISS
    metadata), so an int, an integral float or a digits-only string is a yyyymmdd
    or it is refused. No caller passes Unix seconds; a crawler hands a datetime."""
    if value is None or isinstance(value, (bool, datetime)):
        return value
    numeric = isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit())
    if not numeric:
        return value                                    # an ISO date string: pydantic parses it
    digits = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value).strip()
    if not _YYYYMMDD.match(digits):
        raise ValueError(f"posted_at {value!r} is not a yyyymmdd date (Unix seconds are never accepted)")
    return datetime.strptime(digits, "%Y%m%d")         # an invalid month or day raises ValueError


@dataclass(frozen=True)
class SitemapDTO:
    headline: str
    link: str
    sources: str
    category: Optional[str] = None
    timestamp: Optional[datetime] = None     # DBT-01: pydantic 2 rejects an explicit None for `datetime`
    keywords: Union[None, List[str]] = None
    sitemap_id: Optional[int] = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _stored_date(cls, value):
        """A stored row's int yyyymmdd is a date, never Unix seconds (SYS-90)."""
        return posted_at_datetime(value)
