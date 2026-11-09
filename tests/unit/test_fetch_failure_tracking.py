"""
SYS-09: a sitemap whose fetch/extraction fails (soup was None, or _get_news_details
raised) was never marked in any way -- mark_sitemaps_attempted only covers the
sitemaps that made it into batch_crawling_details' return value, so a permanently
dead URL stayed at the front of the "no article yet" queue (posted_at DESC) and
consumed a retry slot on every single run, forever.

_crawl_newsdetails_inner must now call increment_fetch_failures with exactly the
sitemap_ids from `batch` that have no matching NewsDetailsDTO -- computed from the
DB-facing side (what came back), not from anything _get_news_details itself needs to
change about its return type.
"""
from unittest.mock import MagicMock, patch

import pytest

from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.core.importance_filter import FilterDecision
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl


@pytest.fixture
def service():
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.crawler_dict = {"TEST_SITE": MagicMock()}
    svc.data_flow_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=i) for i in (1, 2, 3)]
    svc.data_flow_repo.save_newsdetails_data.side_effect = lambda dtos: [d.sitemap_id for d in dtos]
    svc.semantic_filter.classify.return_value = FilterDecision(True, "score", True)
    # SYS-62: no row has a recorded failure yet, so a transient one is a first.
    svc.data_flow_repo.get_last_fetch_errors.return_value = {}
    return svc


def _sitemap(sitemap_id):
    """OPS-16: the tests above the floor need more than the fixture's 3 rows."""
    return MagicMock(sitemap_id=sitemap_id)


def article(sitemap_id, text="Berita ekonomi tentang suku bunga.", title="Title"):
    return NewsDetailsDTO(sitemap_id=sitemap_id, extracted_text=[text], meta_data={"title": title}, reporter=[])


def _all_failed_ids(mock_call):
    """With 3 sitemaps and the service's batch_size = max(1, ceil(n/10)), 3 items
    become 3 batches of 1 -- so increment_fetch_failures can be called once per
    batch rather than once for the whole run. Flatten every call's ids together."""
    ids = []
    for call in mock_call.call_args_list:
        ids.extend(call.args[0] if call.args else call.kwargs.get("sitemap_ids"))
    return ids


class TestFetchFailureDetection:
    def test_sitemap_missing_from_batch_result_is_counted_as_a_fetch_failure(self, service):
        # 3 sitemaps requested (ids 1,2,3), only 2 came back -- id 3's fetch/extraction failed.
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [article(1), article(2)]

        service.crawl_newsdetails("TEST_SITE")

        assert _all_failed_ids(service.data_flow_repo.increment_fetch_failures) == [3]

    def test_all_sitemaps_extracted_means_no_fetch_failures_recorded(self, service):
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(1), article(2), article(3)
        ]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.increment_fetch_failures.assert_not_called()

    def test_an_entire_batch_failing_is_still_recorded_when_the_source_is_otherwise_working(self, service):
        """batch_crawling_details returning [] for a batch used to `continue`
        immediately, with nothing else in the loop ever seeing those sitemap_ids --
        the exact case that let a source's queue fill up entirely with dead links.
        With 3 sitemaps -> 3 batches of 1, batches 2 and 3 return [] here while
        batch 1 succeeds, so this is two dead URLs on a working source, not a
        source-wide failure (see TestWholeSourceFailure for that case)."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = [[article(1)], [], []]

        service.crawl_newsdetails("TEST_SITE")

        assert sorted(_all_failed_ids(service.data_flow_repo.increment_fetch_failures)) == [2, 3]
        # The early `continue` still means no mark_sitemaps_attempted for them.
        service.data_flow_repo.mark_sitemaps_attempted.assert_called_once_with([1])

    def test_successful_sitemaps_are_not_also_counted_as_failures(self, service):
        """A mixed batch: only the genuinely-missing id must reach
        increment_fetch_failures, never one that has a real NewsDetailsDTO."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [article(1)]

        service.crawl_newsdetails("TEST_SITE")

        failed_ids = _all_failed_ids(service.data_flow_repo.increment_fetch_failures)
        assert 1 not in failed_ids
        assert sorted(failed_ids) == [2, 3]


def _batch(items, failures):
    from newscrawler.infrastructure.datasource.scrapers.crawler import NewsDetailsBatch
    return NewsDetailsBatch(items, failures=failures)


def _error_msgs(mock_call):
    """{error_msg: sorted ids} across every increment_fetch_failures call."""
    out = {}
    for call in mock_call.call_args_list:
        ids = call.args[0] if call.args else call.kwargs["sitemap_ids"]
        msg = call.kwargs.get("error_msg", call.args[1] if len(call.args) > 1 else None)
        out.setdefault(msg, []).extend(ids)
    return {k: sorted(v) for k, v in out.items()}


class TestWholeSourceFailure:
    """OPS-15 (#81) then OPS-16 (#87): SYS-09's cap retires individually dead
    URLs. When the whole run fails, that can be the source failing (a block, TLS,
    DNS, a crawler regression) and counting it would retire up to 1,000 rows per
    source after three such runs.

    OPS-15 implemented that as a pure ratio with no floor and no persisted output.
    The tests below used to assert THAT behaviour with N=3 -- which OPS-16 showed
    is the bug, not the specification: with 3 rows left and all 3 dead, "100%
    failed" is evidence about those 3 URLs, and sparing them meant they were
    re-fetched on every run forever with no cooldown, worse than before OPS-15."""

    def test_a_small_run_is_dead_urls_not_a_source_failure(self, service, caplog):
        """OPS-16 (a): 3 of 3 failing is below SITEMAP_SOURCE_FAILURE_MIN, so it
        counts individually -- 3 increments and 3 cooldown stamps. This is the
        exact case that kept BISNIS's 3-row queue being re-fetched forever."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = _batch(
            [], {1: "HTTP 404", 2: "HTTP 404", 3: "HTTP 404"}
        )

        with caplog.at_level("WARNING"):
            service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.increment_fetch_failures.assert_called_once_with(
            [1, 2, 3], error_msg="HTTP 404"
        )
        assert any("below SITEMAP_SOURCE_FAILURE_MIN" in r.message for r in caplog.records), caplog.text

    def test_a_blocked_small_queue_still_retires_one_attempt_later(self, service):
        """OPS-16 (a) under SYS-62: BISNIS's shape (3 rows, all 403). A first
        transient failure is cooldown-stamped with its reason but not struck; the
        next attempt, a cooldown later, finds the same 403 recorded and strikes.
        So a URL that is unreachable for good still reaches SYS-09's cap."""
        failures = {1: "HTTP 403", 2: "HTTP 403", 3: "HTTP 403"}
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = _batch([], failures)

        service.crawl_newsdetails("TEST_SITE")
        service.data_flow_repo.increment_fetch_failures.assert_not_called()
        service.data_flow_repo.record_fetch_error.assert_called_once_with([1, 2, 3], error_msg="HTTP 403")

        service.data_flow_repo.reset_mock()
        service.data_flow_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=i) for i in (1, 2, 3)]
        service.data_flow_repo.get_last_fetch_errors.return_value = dict(failures)
        service.crawl_newsdetails("TEST_SITE")
        service.data_flow_repo.increment_fetch_failures.assert_called_once_with([1, 2, 3], error_msg="HTTP 403")
        service.data_flow_repo.record_fetch_error.assert_not_called()

    def test_a_large_all_failing_run_is_source_wide(self, service):
        """OPS-16: above the floor, a 100%-failed run of source-level reasons
        spares the counters -- but stamps the cooldown so the window rotates out
        of load_all_sitemaps' ORDER BY posted_at DESC LIMIT 1000, instead of the
        same dead rows being handed to every run forever."""
        n = 40
        failures = {i: "HTTP 403" for i in range(1, n + 1)}
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = _batch([], failures)
        service.data_flow_repo.load_sitemap_data.return_value = [_sitemap(i) for i in range(1, n + 1)]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.increment_fetch_failures.assert_not_called()
        stamped = service.data_flow_repo.mark_sitemaps_attempted.call_args_list[-1][0][0]
        assert sorted(stamped) == list(range(1, n + 1)), "the spared rows must still get a cooldown"

    def test_a_404_still_counts_even_in_a_source_wide_run(self, service):
        """OPS-16: a 404 is a fact about the URL, not the source -- true whether
        3 of 3 or 1,000 of 1,000 came back that way. Sparing them is what stalled
        a dead top-1,000 window and starved the 10,000 rows behind it."""
        n = 40
        failures = {i: ("HTTP 404" if i <= 25 else "ConnectionError") for i in range(1, n + 1)}
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = _batch([], failures)
        service.data_flow_repo.load_sitemap_data.return_value = [_sitemap(i) for i in range(1, n + 1)]

        service.crawl_newsdetails("TEST_SITE")

        counted = {c.kwargs.get("error_msg"): sorted(c.args[0])
                   for c in service.data_flow_repo.increment_fetch_failures.call_args_list}
        assert counted == {"HTTP 404": list(range(1, 26))}, counted
        stamped = service.data_flow_repo.mark_sitemaps_attempted.call_args_list[-1][0][0]
        assert sorted(stamped) == list(range(26, n + 1)), "only the source-level rows are spared"

    def test_the_verdict_reaches_the_crawl_log_row(self, service):
        """OPS-16 (c): the row used to be status='completed', article_count=0,
        error_msg=NULL -- identical to "1,000 pages fetched fine, all off-topic".
        And basicConfig() has no file handler, so under Task Scheduler the ERROR
        line was gone too."""
        n = 40
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = _batch(
            [], {i: "HTTP 403" for i in range(1, n + 1)}
        )
        service.data_flow_repo.load_sitemap_data.return_value = [_sitemap(i) for i in range(1, n + 1)]

        service.crawl_newsdetails("TEST_SITE")

        note = service.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert note and "source-wide fetch failure" in note and "40/40" in note and "HTTP 403" in note

    def test_a_clean_run_records_no_verdict(self, service):
        service.crawl_newsdetails("TEST_SITE")
        assert service.data_flow_repo.log_crawl_complete.call_args.kwargs["note"] is None

    def test_per_url_classification(self):
        from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl as C
        for reason in ("HTTP 404", "http 404", "soft-404: redirected to /", "HTTP 410"):
            assert C._is_per_url_failure(reason) is True, reason
        for reason in ("HTTP 403", "HTTP 500", "ConnectionError", "SSLError after 5 retries",
                       "ReadTimeout after 5 retries", "AttributeError", ""):
            assert C._is_per_url_failure(reason) is False, reason

    def test_ratio_threshold_is_honoured(self, service):
        """With SITEMAP_SOURCE_FAILURE_RATIO lowered to 0.6 AND the floor lowered,
        2 of 3 failing (67%) is a source-wide failure; at the default floor of 20
        it is two dead URLs however the ratio is set (OPS-16)."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = [
            [article(1)], _batch([], {2: "ConnectionError"}), _batch([], {3: "ConnectionError"}),
        ]

        with patch("newscrawler.domain.services.crawler_service_impl.SITEMAP_SOURCE_FAILURE_RATIO", 0.6),              patch("newscrawler.domain.services.crawler_service_impl.SITEMAP_SOURCE_FAILURE_MIN", 2):
            service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.increment_fetch_failures.assert_not_called()

    def test_partial_failure_below_the_ratio_is_counted(self, service):
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = [
            [article(1)], _batch([], {2: "HTTP 404"}), _batch([], {3: "HTTP 404"}),
        ]

        service.crawl_newsdetails("TEST_SITE")

        assert sorted(_all_failed_ids(service.data_flow_repo.increment_fetch_failures)) == [2, 3]


class TestFailureReasonsReachTheDatabase:
    """OPS-15 (#81): last_fetch_error was the constant "fetch or extraction
    produced no result" for every row, so the runbook query could not tell a 404
    from a timeout from a crash. batch_crawling_details now returns the reason per
    sitemap_id; the service records one increment call per distinct reason."""

    def test_each_distinct_reason_is_stored_against_its_own_sitemaps(self, service):
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = [
            [article(1)],
            _batch([], {2: "HTTP 404"}),
            _batch([], {3: "ReadTimeout after 5 retries"}),
        ]

        service.crawl_newsdetails("TEST_SITE")

        assert _error_msgs(service.data_flow_repo.increment_fetch_failures) == {"HTTP 404": [2]}
        # SYS-62: a first timeout is stored without a strike.
        assert _error_msgs(service.data_flow_repo.record_fetch_error) == {"ReadTimeout after 5 retries": [3]}

    def test_a_404_and_a_timeout_do_not_share_an_error_message(self, service):
        """The ticket's own Done-when, stated directly."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = [
            [article(1)], _batch([], {2: "HTTP 404"}), _batch([], {3: "ReadTimeout after 5 retries"}),
        ]

        service.crawl_newsdetails("TEST_SITE")

        msgs = {**_error_msgs(service.data_flow_repo.increment_fetch_failures),
                **_error_msgs(service.data_flow_repo.record_fetch_error)}
        assert len(msgs) == 2
        assert msgs["HTTP 404"] != msgs["ReadTimeout after 5 retries"]

    def test_a_plain_list_without_reasons_still_gets_the_generic_message(self, service):
        """A crawler (or test double) returning a plain list must keep working --
        the reason just falls back to SYS-09's original text."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = [[article(1)], [], [article(3)]]

        service.crawl_newsdetails("TEST_SITE")

        assert _error_msgs(service.data_flow_repo.increment_fetch_failures) == {
            "fetch or extraction produced no result": [2],
        }


class TestTransientFailuresDoNotStrikeOnce:
    """SYS-62 (#200): OPS-16 decides "source-level or per-URL" once per run, by
    ratio. On 2026-09-28 a four-minute ConnectionError burst inside a healthy
    DETIK run (93 of 1,000 failed) put a strike and a week's cooldown on 92 of
    its newest, working URLs. The code already called a ConnectionError
    source-level; that was consulted only in a wholly failed run."""

    DETIK_BURST = "ConnectionError after 5 retries"
    REDIRECT_LOOP = "request failed: TooManyRedirects: Exceeded 30 redirects."

    def _detik_run(self):
        failures = {i: self.DETIK_BURST for i in range(1, 93)}
        failures[93] = self.REDIRECT_LOOP
        return failures

    def test_the_detik_burst_strikes_only_the_redirect_loop(self, service):
        """The ticket's Done-when: 1,000 attempted, 92 ConnectionError + 1
        TooManyRedirects -> exactly the one per-page failure is counted, and all
        93 are cooldown-stamped (both writes stamp last_crawl_attempt)."""
        note = service._record_fetch_failures("DETIK", 1000, self._detik_run())

        assert _error_msgs(service.data_flow_repo.increment_fetch_failures) == {self.REDIRECT_LOOP: [93]}
        assert _error_msgs(service.data_flow_repo.record_fetch_error) == {self.DETIK_BURST: list(range(1, 93))}
        assert note.startswith("transient fetch failures: 92/1000; 92 not counted"), note

    def test_a_repeated_transient_failure_strikes(self, service):
        """The previous recorded failure was transient too (an attempt at least a
        cooldown ago), so this one counts: a URL unreachable for good retires."""
        service.data_flow_repo.get_last_fetch_errors.return_value = {1: "HTTP 502", 2: self.DETIK_BURST}

        note = service._record_fetch_failures("VIVA", 1000, {1: "HTTP 502", 2: "HTTP 502", 3: "HTTP 502"})

        assert _error_msgs(service.data_flow_repo.increment_fetch_failures) == {"HTTP 502": [1, 2]}
        assert _error_msgs(service.data_flow_repo.record_fetch_error) == {"HTTP 502": [3]}
        assert "1 not counted" in note and "2 counted (transient again)" in note, note

    def test_a_previous_per_url_or_page_failure_is_not_a_transient_repeat(self, service):
        service.data_flow_repo.get_last_fetch_errors.return_value = {1: "HTTP 404", 2: "AttributeError: x", 3: None}

        service._record_fetch_failures("KUMPARAN", 1000, {1: "HTTP 403", 2: "HTTP 403", 3: "HTTP 403"})

        service.data_flow_repo.increment_fetch_failures.assert_not_called()
        assert _error_msgs(service.data_flow_repo.record_fetch_error) == {"HTTP 403": [1, 2, 3]}

    def test_the_note_reaches_the_crawl_log_row(self, service):
        """A burst inside a healthy run is found with SQL, not only in the log."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = [
            [article(1)], _batch([], {2: self.DETIK_BURST}), [article(3)],
        ]

        service.crawl_newsdetails("TEST_SITE")

        note = service.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert note and note.startswith("transient fetch failures: 1/3"), note

    def test_a_source_wide_run_never_reads_the_prior_errors(self, service):
        """Source-wide, a transient failure is spared outright (OPS-16): a long
        outage must not strike a whole queue once per run."""
        failures = {i: self.DETIK_BURST for i in range(1, 41)}

        verdict = service._record_fetch_failures("DETIK", 40, failures)

        assert verdict.startswith("source-wide fetch failure")
        service.data_flow_repo.increment_fetch_failures.assert_not_called()
        service.data_flow_repo.record_fetch_error.assert_not_called()
        service.data_flow_repo.get_last_fetch_errors.assert_not_called()

    @pytest.mark.parametrize("reason, expected", [
        ("HTTP 404", "per_url"), ("HTTP 410", "per_url"), ("soft-404: redirected to /404", "per_url"),
        ("ConnectionError after 5 retries", "transient"), ("ReadTimeout after 5 retries", "transient"),
        ("SSLError after 5 retries", "transient"),
        ("HTTP 403", "transient"), ("HTTP 408", "transient"), ("HTTP 429", "transient"),
        ("HTTP 500", "transient"), ("HTTP 502", "transient"), ("HTTP 599", "transient"),
        ("HTTP 400", "page"), ("HTTP 401", "page"), ("HTTP 451", "page"),
        ("request failed: TooManyRedirects: Exceeded 30 redirects.", "page"),
        ("request failed: InvalidURL: bad", "page"), ("AttributeError: 'NoneType'", "page"),
        ("empty document", "page"), ("fetch or extraction produced no result", "page"),
        ("ConnectionError", "page"), ("HTTP 5020", "page"), ("", "page"), (None, "page"),
    ])
    def test_failure_class(self, reason, expected):
        assert CrawlerServiceImpl._failure_class(reason) == expected

    def test_the_loaders_own_transport_reasons_classify_as_transient(self):
        """Pins the coupling: the classifier recognises the page loader's reason
        by its shape, so a change to that format must fail here, not in a run."""
        import requests
        from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
        loader = RequestsPageLoader()
        for exc in (requests.exceptions.ConnectionError("reset"), requests.exceptions.ReadTimeout("t")):
            with patch("newscrawler.core.page_loader.requests_page_loader.requests.get", side_effect=exc):
                _, reason = loader.get_soup_with_reason("http://x/a")
            assert CrawlerServiceImpl._failure_class(reason) == "transient", reason
