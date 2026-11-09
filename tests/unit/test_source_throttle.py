"""SRC-55 (#201): a source that walls us off with HTTP 403 part-way through a
run stops being fetched for the rest of that run, and neither the streak's
rows nor the rows it never reached are struck, error-stamped or
cooldown-stamped.

KUMPARAN answered 403 to everything after ~100-120 fetches per run; SYS-62
cooldown-stamped the tail and struck it on the next visit, so good URLs
retired as dead. The service-level tests here drive the real
Crawler.batch_crawling_details (only the page loader is scripted), because
the skip happens inside it.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from newscrawler.core.importance_filter import FilterDecision
from newscrawler.core.page_loader.page_loader import PageLoader
from newscrawler.core.page_loader.throttle import NOT_FETCHED_REASON, ThrottleGuard
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

STREAK = 10


class TestThrottleGuard:
    def test_trips_on_the_nth_throttle_answer_in_a_row(self):
        g = ThrottleGuard(3)
        g.record(1, "HTTP 403")
        g.record(2, "HTTP 429")
        assert g.should_fetch()
        g.record(3, "HTTP 403")
        assert g.tripped and not g.should_fetch()
        assert g.throttled_ids == {1, 2, 3}
        assert g.fetches_before_trip == 3
        assert g.trip_reason == "HTTP 403"

    @pytest.mark.parametrize("breaker", [None, "HTTP 404", "HTTP 502", "NameResolutionError after 3 retries",
                                         "AttributeError: x"])
    def test_any_other_outcome_breaks_the_streak(self, breaker):
        """A single dead article answering 403 between served pages is a fact
        about that URL (SYS-62's business), not a wall."""
        g = ThrottleGuard(3)
        g.record(1, "HTTP 403")
        g.record(2, "HTTP 403")
        g.record(3, breaker)
        g.record(4, "HTTP 403")
        g.record(5, "HTTP 403")
        assert not g.tripped
        assert g.throttled_ids == set()

    def test_in_flight_throttle_answers_after_the_trip_join_the_throttled_set(self):
        g = ThrottleGuard(2)
        g.record(1, "HTTP 403")
        g.record(2, "HTTP 403")
        g.record(3, "HTTP 403")   # was already in flight
        g.record(4, None)          # an in-flight success is simply a success
        assert g.throttled_ids == {1, 2, 3}

    @pytest.mark.parametrize("reason", ["ConnectionError after 3 retries", "ReadTimeout after 3 retries",
                                        "ConnectTimeout after 5 retries"])
    def test_a_refusing_host_trips_like_a_403_wall(self, reason):
        """SYS-66 (#213): a host that stops accepting connections or answering,
        after the loader's backed-off retries, is a wall one layer down."""
        g = ThrottleGuard(3)
        for i in range(1, 4):
            g.record(i, reason)
        assert g.tripped and g.trip_reason == reason

    def test_403_and_refusals_make_one_streak(self):
        g = ThrottleGuard(3)
        g.record(1, "HTTP 403")
        g.record(2, "ConnectionError after 3 retries")
        g.record(3, "HTTP 429")
        assert g.tripped

    def test_a_host_that_does_not_resolve_never_trips(self):
        """SYS-66: PIKIRANRAKYAT's retired regional brands do not resolve. Those
        rows are facts about their URLs; if they tripped the guard, the source
        would stop on the same unstamped rows at the head of its queue every run."""
        g = ThrottleGuard(3)
        for i in range(1, 30):
            g.record(i, "NameResolutionError after 3 retries")
        assert not g.tripped

    def test_rejects_a_non_positive_limit(self):
        with pytest.raises(ValueError):
            ThrottleGuard(0)


def _sitemaps(n):
    return [SitemapDTO(headline=f"h{i}", link=f"http://x/{i}", sources="KUMPARAN", category="news", sitemap_id=i)
            for i in range(1, n + 1)]


class _WallLoader(PageLoader):
    """Serves a page for the first `served` requests, then answers `status`
    to every request, in request order (thread-safe)."""

    def __init__(self, served, status="HTTP 403"):
        self.served = served
        self.status = status
        self.calls = 0
        self._lock = threading.Lock()

    def get_soup_with_reason(self, url):
        with self._lock:
            self.calls += 1
            n = self.calls
        if n <= self.served:
            return BeautifulSoup("<html><body><p>isi berita</p></body></html>", "html.parser"), None
        return None, self.status

    def get_soup(self, url):
        return self.get_soup_with_reason(url)[0]


class _Crawler(Crawler):
    def __init__(self, loader, parallel=False):
        super().__init__()
        self.website_name = "KUMPARAN"
        self.parallelize = parallel
        self.max_worker = 4
        self.page_loader = loader

    @staticmethod
    def _get_whole_text(soup):
        return ["Bank Indonesia menahan suku bunga acuan. " * 10]

    def _get_reporter_from_text(self, soup):
        return ["Budi Santoso"]


def _service(crawler, rows):
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.crawler_dict = {"KUMPARAN": crawler}
    svc.chunker = MagicMock()
    svc.chunker.chunk.return_value = []
    repo = svc.data_flow_repo
    repo.load_sitemap_data.return_value = rows
    repo.save_chunk_data.return_value = []
    repo.get_last_fetch_errors.return_value = {}
    repo.discard_terminal_embeddings.return_value = 0
    svc.semantic_filter.classify.return_value = FilterDecision(True, "score", True)
    return svc


def _ids(mock_call):
    out = []
    for call in mock_call.call_args_list:
        out.extend(call.args[0] if call.args else call.kwargs.get("sitemap_ids", []))
    return out


@patch("newscrawler.domain.services.crawler_service_impl.SOURCE_THROTTLE_STREAK", STREAK)
class TestRunStopsAtTheWall:
    def test_rows_after_the_streak_are_neither_struck_nor_stamped(self):
        """The ticket's Done-when: the loader answers 403 from request K on.
        50 rows -> 10 batches of 5. Requests 1-12 are served, 13-22 are the
        streak (spanning batches 3-5), rows 23-50 are never requested."""
        loader = _WallLoader(served=12)
        svc = _service(_Crawler(loader), _sitemaps(50))

        svc.crawl_newsdetails("KUMPARAN")

        repo = svc.data_flow_repo
        assert loader.calls == 22, "nothing may be requested after the streak trips"
        assert sorted(_ids(repo.mark_sitemaps_attempted)) == list(range(1, 13))
        repo.increment_fetch_failures.assert_not_called()
        repo.record_fetch_error.assert_not_called()
        note = repo.log_crawl_complete.call_args.kwargs["note"]
        assert note.startswith("throttled (SRC-55): 10 x HTTP 403 in a row after 22 fetches"), note
        assert "10 throttled and 28 not fetched left untouched" in note, note

    def test_no_batch_is_started_after_the_trip(self):
        """The trip in batch 5 of 10 ends the run: batches 6-10 are not handed
        to the crawler at all (no "Processing batch" lines for work not done)."""
        crawler = _Crawler(_WallLoader(served=12))
        calls = []
        real = crawler.batch_crawling_details
        crawler.batch_crawling_details = lambda **kw: calls.append(len(kw["news"])) or real(**kw)
        svc = _service(crawler, _sitemaps(50))

        svc.crawl_newsdetails("KUMPARAN")

        assert len(calls) == 5

    def test_a_wall_from_the_first_request_is_logged_at_error(self, caplog):
        loader = _WallLoader(served=0)
        svc = _service(_Crawler(loader), _sitemaps(30))

        with caplog.at_level("WARNING"):
            svc.crawl_newsdetails("KUMPARAN")

        assert loader.calls == STREAK
        svc.data_flow_repo.mark_sitemaps_attempted.assert_not_called()
        svc.data_flow_repo.increment_fetch_failures.assert_not_called()
        svc.data_flow_repo.record_fetch_error.assert_not_called()
        errors = [r for r in caplog.records if r.levelname == "ERROR" and "SRC-55" in r.getMessage()]
        assert errors, "a source that serves nothing before the streak must be an ERROR"

    def test_a_short_403_run_is_left_to_sys62(self):
        """Nine 403s then served pages again: no wall. The 403 rows are
        SYS-62's first transient failures, recorded and cooldown-stamped."""
        class Loader(_WallLoader):
            def get_soup_with_reason(self, url):
                with self._lock:
                    self.calls += 1
                    n = self.calls
                if 4 <= n <= 12:
                    return None, "HTTP 403"
                return BeautifulSoup("<p>x</p>", "html.parser"), None

        loader = Loader(served=0)
        svc = _service(_Crawler(loader), _sitemaps(20))

        svc.crawl_newsdetails("KUMPARAN")

        assert loader.calls == 20
        assert sorted(_ids(svc.data_flow_repo.record_fetch_error)) == list(range(4, 13))
        note = svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert "SRC-55" not in note and note.startswith("transient fetch failures: 9/20"), note

    def test_the_rest_of_the_run_is_counted_without_the_released_rows(self):
        """A failure among the served rows is still judged per URL, against a
        denominator that excludes the throttled and never-fetched rows."""
        class Loader(_WallLoader):
            def get_soup_with_reason(self, url):
                with self._lock:
                    self.calls += 1
                    n = self.calls
                if n == 2:
                    return None, "HTTP 404"
                if n <= 5:
                    return BeautifulSoup("<p>x</p>", "html.parser"), None
                return None, "HTTP 403"

        svc = _service(_Crawler(Loader(served=0)), _sitemaps(40))

        svc.crawl_newsdetails("KUMPARAN")

        assert _ids(svc.data_flow_repo.increment_fetch_failures) == [2]
        svc.data_flow_repo.record_fetch_error.assert_not_called()

    def test_the_source_wide_ratio_is_over_the_rows_actually_judged(self):
        """25 served pages whose extraction all raised, then the wall. Judged
        over the 25 rows that count, every one failed: OPS-16's source-wide
        verdict (a crawler regression) spares them. Over all 100 rows it would
        be 25% and strike 25 URLs for a bug in our extractor."""
        class Broken(_Crawler):
            def _fetch_news_details(self, sitemap):
                dto, reason = super()._fetch_news_details(sitemap)
                return (None, "AttributeError: selector gone") if dto else (None, reason)

        crawler = Broken(_WallLoader(served=25))
        svc = _service(crawler, _sitemaps(100))

        svc.crawl_newsdetails("KUMPARAN")

        svc.data_flow_repo.increment_fetch_failures.assert_not_called()
        note = svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert "source-wide fetch failure: 25/25" in note, note

    def test_parallel_workers_stop_within_one_worker_pool_of_the_trip(self):
        loader = _WallLoader(served=12)
        crawler = _Crawler(loader, parallel=True)
        svc = _service(crawler, _sitemaps(200))

        svc.crawl_newsdetails("KUMPARAN")

        repo = svc.data_flow_repo
        assert 22 <= loader.calls <= 22 + crawler.max_worker
        # Which ids the 12 served calls belong to depends on thread scheduling (DBT-54): the
        # requirement is that exactly the 12 served rows were attempted, all from the part of
        # the queue a worker pool could have reached before the trip, and nothing was struck.
        attempted = _ids(repo.mark_sitemaps_attempted)
        assert len(attempted) == 12 and len(set(attempted)) == 12
        assert max(attempted) <= 22 + crawler.max_worker
        repo.increment_fetch_failures.assert_not_called()
        repo.record_fetch_error.assert_not_called()


class TestCrawlerSkipsAfterTheTrip:
    def test_unstarted_rows_carry_the_not_fetched_reason(self):
        loader = _WallLoader(served=1)
        guard = ThrottleGuard(2)
        batch = _Crawler(loader).batch_crawling_details(_sitemaps(5), "KUMPARAN", throttle=guard)

        assert [n.sitemap_id for n in batch] == [1]
        assert batch.failures == {2: "HTTP 403", 3: "HTTP 403",
                                  4: NOT_FETCHED_REASON, 5: NOT_FETCHED_REASON}
        assert loader.calls == 3

    def test_without_a_guard_every_row_is_fetched_as_before(self):
        loader = _WallLoader(served=1)
        batch = _Crawler(loader).batch_crawling_details(_sitemaps(5), "KUMPARAN")
        assert loader.calls == 5
        assert set(batch.failures.values()) == {"HTTP 403"}


@patch("newscrawler.domain.services.crawler_service_impl.SOURCE_THROTTLE_STREAK", STREAK)
class TestRefusalsAndDeadHosts:
    def test_a_connection_wall_stops_the_run_and_leaves_the_rows_untouched(self):
        """SYS-66: the SRC-55 contract, for a host that refuses connections."""
        loader = _WallLoader(served=12, status="ConnectionError after 3 retries")
        svc = _service(_Crawler(loader), _sitemaps(50))

        svc.crawl_newsdetails("KUMPARAN")

        repo = svc.data_flow_repo
        assert loader.calls == 22
        repo.increment_fetch_failures.assert_not_called()
        repo.record_fetch_error.assert_not_called()
        note = repo.log_crawl_complete.call_args.kwargs["note"]
        assert note.startswith("throttled (SRC-55): 10 x ConnectionError after 3 retries in a row"), note

    def test_dead_hosts_never_stop_the_run(self):
        """SYS-66: every row on a host that does not resolve is fetched and goes
        to SYS-62 (first transient failure: recorded, cooldown-stamped), so the
        dead rows leave the head of the queue and retire on the repeat rule."""
        loader = _WallLoader(served=5, status="NameResolutionError after 3 retries")
        svc = _service(_Crawler(loader), _sitemaps(40))

        svc.crawl_newsdetails("KUMPARAN")

        assert loader.calls == 40, "a dead host must not trip SRC-55's guard"
        assert sorted(_ids(svc.data_flow_repo.record_fetch_error)) == list(range(6, 41))
        note = svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert "SRC-55" not in note, note
