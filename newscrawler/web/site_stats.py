"""The corpus line under the title and the portal list of the filter (SYS-101, SYS-100).

Both come from one cheap aggregate over `articles` (~0.3 s on 95k articles,
measured 2026-10-07), cached for CACHE_S so a page load costs nothing. A failed
query is cached briefly as "unknown": the page then shows the line without
numbers and only "Semua portal", never a zero that reads as an empty corpus.
"""
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import text

from newscrawler.core.newsletter_copy import outlet

logger = logging.getLogger(__name__)

CACHE_S = 600
FAILURE_CACHE_S = 60
WIB = timedelta(hours=7)    # crawl_log timestamps are the DB container's NOW(), UTC


@dataclass(frozen=True)
class SiteStats:
    articles: Optional[int] = None
    portals: Optional[int] = None
    updated_wib: Optional[datetime] = None
    portal_options: Tuple[Tuple[str, str], ...] = ()     # (source value, outlet name), sorted by name


class SiteStatsCache:
    _PORTALS = text("""
        SELECT s.sources AS source, COUNT(*) AS n
        FROM articles a JOIN sitemaps s ON s.sitemap_id = a.sitemap_id
        GROUP BY s.sources
    """)
    # The last time new articles reached the store: the end of the latest completed article crawl.
    _UPDATED = text("""
        SELECT MAX(COALESCE(finished_at, started_at)) FROM crawl_log
        WHERE status = 'completed' AND task IN ('all', 'full_text')
    """)

    def __init__(self, client, clock=time.monotonic):
        self.client = client
        self._clock = clock
        self._lock = threading.Lock()
        self._value: Optional[SiteStats] = None
        self._expires = 0.0

    def get(self) -> SiteStats:
        with self._lock:
            if self._value is not None and self._clock() < self._expires:
                return self._value
        value, ttl = self._load()
        with self._lock:
            self._value, self._expires = value, self._clock() + ttl
        return value

    def _load(self) -> Tuple[SiteStats, float]:
        try:
            with self.client.get_session() as session:
                rows = session.execute(self._PORTALS).fetchall()
                updated = session.execute(self._UPDATED).scalar()
        except Exception as e:  # noqa: BLE001 -- the page renders without numbers
            logger.warning(f"Site stats unavailable: {type(e).__name__}: {e}")
            return SiteStats(), FAILURE_CACHE_S
        counts: List[Tuple[str, int]] = [(r.source, r.n) for r in rows if r.source]
        options = tuple(sorted(((s, outlet(s)) for s, _ in counts), key=lambda o: o[1].lower()))
        return SiteStats(articles=sum(n for _, n in counts), portals=len(counts),
                         updated_wib=updated + WIB if updated else None, portal_options=options), CACHE_S
