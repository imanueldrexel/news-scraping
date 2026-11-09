"""ADR-005: the in-memory turn store between the two steps of a question, and the cached
corpus line / portal list (SYS-101, SYS-100)."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from newscrawler.web.site_stats import CACHE_S, FAILURE_CACHE_S, SiteStatsCache
from newscrawler.web.turn_store import TurnStore


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestTurnStore:
    def test_put_get_done(self):
        store = TurnStore()
        turn = store.put("q", "sid", [{"n": 1}])
        assert store.get(turn.turn_id).question == "q"
        store.done(turn.turn_id)
        assert store.get(turn.turn_id) is None

    def test_turns_expire(self):
        clock = Clock()
        store = TurnStore(ttl_seconds=900, clock=clock)
        turn = store.put("q", "sid", [])
        clock.t += 901
        assert store.get(turn.turn_id) is None

    def test_the_oldest_turn_makes_room(self):
        clock = Clock()
        store = TurnStore(max_turns=2, clock=clock)
        first = store.put("1", "s", [])
        clock.t += 1
        second = store.put("2", "s", [])
        clock.t += 1
        third = store.put("3", "s", [])
        assert store.get(first.turn_id) is None and store.get(second.turn_id) and store.get(third.turn_id)

    def test_ids_are_unique_and_safe_in_an_html_id(self):
        store = TurnStore()
        ids = {store.put("q", "s", []).turn_id for _ in range(200)}
        assert len(ids) == 200 and all(i.isalnum() for i in ids)


def _client(rows=(), updated=None, error=None):
    session = MagicMock()
    if error:
        session.execute.side_effect = error
    session.execute.return_value.fetchall.return_value = list(rows)
    session.execute.return_value.scalar.return_value = updated
    client = MagicMock()
    client.get_session.return_value.__enter__.return_value = session
    return client, session


class TestSiteStats:
    def test_counts_portals_and_wib_time(self):
        rows = [SimpleNamespace(source="KONTAN", n=10), SimpleNamespace(source="DETIK", n=5),
                SimpleNamespace(source="CNBC", n=1)]
        client, _ = _client(rows, updated=datetime(2026, 10, 6, 13, 16))
        stats = SiteStatsCache(client).get()
        assert (stats.articles, stats.portals) == (16, 3)
        assert stats.updated_wib == datetime(2026, 10, 6, 20, 16), "crawl_log is UTC; the page says WIB"
        assert stats.portal_options == (("CNBC", "CNBC Indonesia"), ("DETIK", "detikcom"), ("KONTAN", "Kontan"))

    def test_cached(self):
        clock = Clock()
        client, session = _client([SimpleNamespace(source="KONTAN", n=1)])
        cache = SiteStatsCache(client, clock=clock)
        cache.get(), cache.get()
        calls = session.execute.call_count
        clock.t += CACHE_S + 1
        cache.get()
        assert session.execute.call_count == calls * 2

    def test_a_failure_is_unknown_not_zero_and_retried_soon(self):
        clock = Clock()
        client, session = _client(error=RuntimeError("db down"))
        cache = SiteStatsCache(client, clock=clock)
        stats = cache.get()
        assert stats.articles is None and stats.portal_options == ()
        session.execute.side_effect = None
        session.execute.return_value.fetchall.return_value = [SimpleNamespace(source="KONTAN", n=3)]
        clock.t += FAILURE_CACHE_S + 1
        assert cache.get().articles == 3
