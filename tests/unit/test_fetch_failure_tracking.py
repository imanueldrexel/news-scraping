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
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl


@pytest.fixture
def service():
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.crawler_dict = {"TEST_SITE": MagicMock()}
    svc.data_flow_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=i) for i in (1, 2, 3)]
    svc.data_flow_repo.save_newsdetails_data.side_effect = lambda dtos: [d.sitemap_id for d in dtos]
    svc.semantic_filter.is_important.return_value = True
    return svc


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
    """OPS-15 (#81): SYS-09's cap retires individually dead URLs. When EVERY
    attempted sitemap fails in one run, that is the source failing (a block, TLS,
    DNS, a crawler regression), and counting it would retire up to 1,000 rows per
    run per source after three such runs, silently. Count nothing, log ERROR."""

    def test_every_sitemap_failing_increments_nothing_and_logs_an_error(self, service, caplog):
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = _batch(
            [], {1: "HTTP 403", 2: "HTTP 403", 3: "HTTP 403"}
        )

        with caplog.at_level("ERROR"):
            service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.increment_fetch_failures.assert_not_called()
        assert any("source-wide failure" in r.message and "3/3" in r.message and "HTTP 403" in r.message
                   for r in caplog.records if r.levelname == "ERROR"), caplog.text
        # Nothing was marked attempted either, so all three are eligible next run.
        service.data_flow_repo.mark_sitemaps_attempted.assert_not_called()

    def test_ratio_threshold_is_honoured(self, service):
        """With SITEMAP_SOURCE_FAILURE_RATIO lowered to 0.6, 2 of 3 failing (67%)
        is also a source-wide failure; at the default 1.0 it is two dead URLs."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = [
            [article(1)], _batch([], {2: "HTTP 404"}), _batch([], {3: "HTTP 404"}),
        ]

        with patch("newscrawler.domain.services.crawler_service_impl.SITEMAP_SOURCE_FAILURE_RATIO", 0.6):
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

        assert _error_msgs(service.data_flow_repo.increment_fetch_failures) == {
            "HTTP 404": [2],
            "ReadTimeout after 5 retries": [3],
        }

    def test_a_404_and_a_timeout_do_not_share_an_error_message(self, service):
        """The ticket's own Done-when, stated directly."""
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = [
            [article(1)], _batch([], {2: "HTTP 404"}), _batch([], {3: "ReadTimeout after 5 retries"}),
        ]

        service.crawl_newsdetails("TEST_SITE")

        msgs = _error_msgs(service.data_flow_repo.increment_fetch_failures)
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
