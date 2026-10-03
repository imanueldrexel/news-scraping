"""SRC-55 (#201): stop fetching a source for the rest of a run once it is
throttling us.

KUMPARAN answers HTTP 403 to every article request after roughly 100-120
fetches in one run, and every one of those URLs fetches fine hours later. A
run used to keep going through the rest of its queue at full speed; SYS-62
then cooldown-stamped each 403 row and struck it on its next visit, so good
URLs were retired as dead.

A `ThrottleGuard` lives for one source's full-text run and is shared by every
batch and worker thread of it. Each finished fetch is recorded with its
failure reason (None for a page that was served). A streak of `streak_limit`
throttle answers in a row (see THROTTLE_REASONS) trips the guard: fetches not
yet started are skipped with NOT_FETCHED_REASON, and the streak's own rows
are "throttled", not facts about their URLs. The service leaves both sets
untouched: no strike, no last_fetch_error, no cooldown stamp.

"In a row" is in completion order across the worker threads. Any other
outcome (a served page, a 404, a 5xx, a dead host, an extractor exception)
breaks the streak, so one dead article answering 403 among served pages never
trips it.

SYS-66 (#213): a host that stops accepting connections or stops answering is
the same wall one layer down, so `ConnectionError`/`ReadTimeout` that survived
the page loader's backed-off retries count too. A host that does not resolve
(`NameResolutionError after N retries`) does not: that is a fact about the
URL's host (PIKIRANRAKYAT's retired regional brands), and counting it would
stop the source on the same dead rows every run, forever.
"""
import re
import threading
from typing import Optional, Set

# The two statuses a server uses for "you are asking too often". 5xx is left
# out on purpose: VIVA's 502s are scattered over every batch (~12%), not a
# wall, and SYS-62 already handles them per URL.
THROTTLE_REASONS = frozenset({"HTTP 403", "HTTP 429"})

# SYS-66: transport failures that mean "this host is refusing or not answering
# us", as the page loader names them after its retries. NameResolutionError is
# deliberately absent (see the module docstring).
_REFUSAL_AFTER_RETRIES = re.compile(r"^(ConnectionError|ConnectTimeout|ReadTimeout|Timeout) after \d+ retries$")


def is_throttle_reason(reason: Optional[str]) -> bool:
    """True when `reason` says the source, not the URL, turned us away."""
    return reason in THROTTLE_REASONS or bool(reason and _REFUSAL_AFTER_RETRIES.match(reason))

# The reason a skipped row carries in NewsDetailsBatch.failures. The service
# recognises it by this constant, never by parsing the text.
NOT_FETCHED_REASON = "not fetched: source throttled this run (SRC-55)"


class ThrottleGuard:
    def __init__(self, streak_limit: int):
        if streak_limit < 1:
            raise ValueError(f"streak_limit must be >= 1, got {streak_limit}")
        self.streak_limit = streak_limit
        self._lock = threading.Lock()
        self._streak: list = []
        self._tripped = False
        self._throttled: Set[int] = set()
        # Fetches answered before the guard tripped, the tripping streak
        # included: "the source throttled us after N requests".
        self.fetches_before_trip = 0
        self.trip_reason: Optional[str] = None

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def throttled_ids(self) -> Set[int]:
        """Rows whose fetch was answered by the throttle: the streak that
        tripped the guard, plus in-flight fetches answered the same way after
        it. Empty until the guard trips -- an earlier streak that was broken
        is ordinary per-URL evidence for SYS-62."""
        with self._lock:
            return set(self._throttled)

    def should_fetch(self) -> bool:
        return not self._tripped

    def record(self, sitemap_id: int, reason: Optional[str]) -> None:
        """One finished fetch. `reason` is the failure reason the page loader
        or extractor gave, None for success."""
        with self._lock:
            is_throttle = is_throttle_reason(reason)
            if self._tripped:
                if is_throttle:
                    self._throttled.add(sitemap_id)
                return
            self.fetches_before_trip += 1
            if not is_throttle:
                self._streak.clear()
                return
            self._streak.append(sitemap_id)
            if len(self._streak) >= self.streak_limit:
                self._tripped = True
                self.trip_reason = reason
                self._throttled.update(self._streak)
                self._streak.clear()
