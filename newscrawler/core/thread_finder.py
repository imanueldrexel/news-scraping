"""A story's past coverage, from NEWS_L1 (SYS-147 #337, ADR-016).

The story arcs (SYS-148) tell a top story with its back-story. This module finds
the candidates: articles of the `days` before the story's date whose L1 vector
(title + first two paragraphs) is near the centroid of the story's own articles.

The probe (EXPERIMENTS.md 2026-10-13 "Newsletter story arcs") found that no
cosine floor separates "the same thread" from "a similar topic": 0.70 lets in
loose matches (daya beli), 0.80 cuts real history (Houthi, 9 days -> 2). So the
floor here is wide and membership is decided later -- the arc writer picks the
items that belong (`alur`) and code checks them. What this module guarantees:

- no peeking: only articles dated before `day` (a replay of a past date never
  sees what came later, although the index holds it);
- at most one item per day, the nearest (a daily series -- IHSG, emas -- would
  otherwise be 30 near-identical items), with that day's count of near items;
- at most `max_items` days, the nearest ones, always keeping the earliest day
  (where the arc starts);
- headline, outlet and date from the database, never FAISS metadata (ADR-005,
  SYS-91); the opening is the L1 text without a "Reporter: … | Editor: …" line.

`search` and `lookup` are injected (no I/O here):
    search(vector, k) -> [(sitemap_id, posted_at yyyymmdd int, cosine)]
    lookup(sitemap_ids) -> {sitemap_id: {"headline", "source", "posted_at", "l1_text"}}
"""
import re
from datetime import date, timedelta
from typing import Callable, Dict, Iterable, List, NamedTuple, Sequence, Tuple

from newscrawler.core.constants import ARC_FETCH_K, ARC_FLOOR, ARC_LOOKBACK_DAYS, ARC_MAX_ITEMS

OPENING_CHARS = 300

Search = Callable[[Sequence[float], int], List[Tuple[int, int, float]]]
Lookup = Callable[[Iterable[int]], Dict[int, dict]]

# A byline some outlets put first in the L1 text: "Reporter: X | Editor: Y" (KONTAN), "Penulis: …".
_BYLINE = re.compile(r"^\s*(?:Reporter|Penulis|Editor|Sumber)\s*:[^\n]*\n", re.IGNORECASE)


class TimelineItem(NamedTuple):
    sitemap_id: int
    day: date
    source: str
    headline: str
    opening: str          # the L1 text's start, byline stripped, at most OPENING_CHARS
    cosine: float
    day_volume: int       # items of that day over the floor (how much it was covered)


def ymd(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def as_date(posted_at: int) -> date:
    return date(posted_at // 10000, posted_at // 100 % 100, posted_at % 100)


def opening(l1_text: str) -> str:
    """The L1 text's start without a leading byline, cut at a word."""
    text = l1_text or ""
    while True:
        stripped = _BYLINE.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    text = " ".join(text.split())
    if len(text) <= OPENING_CHARS:
        return text
    return text[:OPENING_CHARS].rsplit(" ", 1)[0] + "…"


def find_thread(centroid: Sequence[float], day: date, exclude_ids: Iterable[int], search: Search, lookup: Lookup, *,
                days: int = ARC_LOOKBACK_DAYS, floor: float = ARC_FLOOR, fetch_k: int = ARC_FETCH_K,
                max_items: int = ARC_MAX_ITEMS) -> List[TimelineItem]:
    """The story's candidate past coverage, oldest first (module docstring)."""
    lo, hi = ymd(day - timedelta(days=days)), ymd(day)
    exclude = set(exclude_ids)
    best: Dict[int, Tuple[float, int]] = {}      # posted_at -> (cosine, sitemap_id) of the day's nearest item
    volume: Dict[int, int] = {}
    seen = set()
    for sitemap_id, posted_at, cosine in search(centroid, fetch_k):
        if sitemap_id in exclude or sitemap_id in seen or not lo <= posted_at < hi or cosine < floor:
            continue
        seen.add(sitemap_id)
        volume[posted_at] = volume.get(posted_at, 0) + 1
        if posted_at not in best or cosine > best[posted_at][0]:
            best[posted_at] = (cosine, sitemap_id)
    if not best:
        return []
    kept = sorted(best, key=lambda p: -best[p][0])[:max_items]
    earliest = min(best)
    if earliest not in kept:
        kept[-1] = earliest
    rows = lookup([best[p][1] for p in kept])
    items = []
    for p in sorted(kept):
        cosine, sitemap_id = best[p]
        row = rows.get(sitemap_id)
        if row is None:          # no article row (settled, deleted): the vector says nothing a reader can follow
            continue
        items.append(TimelineItem(sitemap_id, as_date(p), row["source"], row["headline"],
                                  opening(row.get("l1_text") or ""), round(cosine, 4), volume[p]))
    return items
