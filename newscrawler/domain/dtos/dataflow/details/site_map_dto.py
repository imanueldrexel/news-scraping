import numbers
import re
from decimal import Decimal, InvalidOperation
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
    or it is refused. No caller passes Unix seconds; a crawler hands a datetime.

    DBT-60 send-back: "a number" is any `numbers.Real` (a numpy scalar from
    pandas), a Decimal (a NUMERIC column) and any string that reads as one
    ("20260918.0", "+20260918"). Every such value is a yyyymmdd or refused; only a
    string that is no number at all (an ISO date) goes on to pydantic."""
    if value is None or isinstance(value, (bool, datetime)):
        return value
    number = _as_number(value)
    if number is None:
        return value                                    # an ISO date string: pydantic parses it
    digits = str(int(number)) if number == number.to_integral_value() else ""
    if not _YYYYMMDD.match(digits):
        raise ValueError(f"posted_at {value!r} is not a yyyymmdd date (Unix seconds are never accepted)")
    return datetime.strptime(digits, "%Y%m%d")         # an invalid month or day raises ValueError


def _as_number(value) -> Optional[Decimal]:
    """`value` as a finite Decimal when it is a number or a string that reads as one, else None."""
    if isinstance(value, (numbers.Real, Decimal)):      # Decimal is not a numbers.Real
        number = Decimal(str(value))
    elif isinstance(value, str):
        try:
            number = Decimal(value)                     # Decimal ignores surrounding whitespace
        except InvalidOperation:
            return None
    else:
        return None
    if not number.is_finite():
        raise ValueError(f"posted_at {value!r} is not a yyyymmdd date")
    return number


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
