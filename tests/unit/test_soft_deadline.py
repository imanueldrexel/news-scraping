"""SYS-139 (#320, ADR-011): a full-text run with a soft deadline starts no batch that would end
after it. It then runs its end-of-run steps and flushes its vectors, and completes, instead of
being killed inside its last batch with every vector of the run lost (VIVA, 2026-10-11 19:00 and
2026-10-12 07:00).

The service runs its real batch loop; the crawler, the clock and the store are fakes. Each batch
advances the fake clock by its duration (BATCH_S unless the test scripts them).
"""
from unittest.mock import MagicMock, patch

import pytest

from newscrawler.core.importance_filter import FilterDecision
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl

BATCH_S = 100.0


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _rows(n):
    return [SitemapDTO(headline=f"h{i}", link=f"http://x/{i}", sources="VIVA", category="news", sitemap_id=i)
            for i in range(1, n + 1)]


def _details(sitemap):
    return NewsDetailsDTO(sitemap_id=sitemap.sitemap_id, extracted_text=["Bank Indonesia menahan suku bunga."],
                          reporter=None, meta_data={"title": sitemap.headline})


def _service(rows, clock, batch_seconds=()):
    """100 rows make 10 batches of 10. `batch_seconds`: the first batches' durations."""
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    durations = list(batch_seconds)
    crawler = MagicMock()
    offered = []

    def crawl(news, website_name, throttle):
        offered.append([s.sitemap_id for s in news])
        clock.now += durations.pop(0) if durations else BATCH_S
        return [_details(s) for s in news]
    crawler.batch_crawling_details.side_effect = crawl
    svc.crawler_dict = {"VIVA": crawler}
    svc.chunker = MagicMock()
    svc.chunker.chunk.return_value = ["chunk"]
    svc._clock = clock
    repo = svc.data_flow_repo
    repo.load_sitemap_data.return_value = rows
    repo.save_chunk_data.side_effect = lambda chunks: [r.sitemap_id for r in rows]
    repo.save_newsdetails_data.side_effect = lambda dtos: [d.sitemap_id for d in dtos]
    repo.get_last_fetch_errors.return_value = {}
    repo.discard_terminal_embeddings.return_value = 0
    svc.semantic_filter.classify.return_value = FilterDecision(True, "score", True)
    return svc, offered


def _flushed(repo):
    """The deferred block was left once, without an exception: its flush ran."""
    exits = repo.deferred_embeddings.return_value.__exit__.call_args_list
    return len(exits) == 1 and exits[0].args == (None, None, None)


class TestSoftDeadline:
    def test_a_run_that_would_cross_the_deadline_stops_flushes_and_completes(self):
        """The ticket's Done-when. Batches of 100 s, deadline 450 s away: batches 1-4 end at 400 s,
        batch 5 would end at 500 s, so it is not started."""
        clock = _Clock()
        svc, offered = _service(_rows(100), clock)

        svc.crawl_newsdetails("VIVA", deadline=clock.now + 450)

        repo = svc.data_flow_repo
        assert len(offered) == 4
        assert _flushed(repo)
        repo.log_crawl_failed.assert_not_called()
        note = repo.log_crawl_complete.call_args.kwargs["note"]
        assert note.startswith("stopped early (SYS-139): 4 of 10 batches before the soft deadline"), note
        assert "60 rows left for the next run" in note, note

    def test_the_rows_not_offered_are_left_untouched(self):
        """No attempted stamp, no strike, no cooldown: the next run continues the queue."""
        clock = _Clock()
        svc, _ = _service(_rows(100), clock)

        svc.crawl_newsdetails("VIVA", deadline=clock.now + 450)

        repo = svc.data_flow_repo
        stamped = [sid for call in repo.mark_sitemaps_attempted.call_args_list for sid in call.args[0]]
        assert sorted(stamped) == list(range(1, 41))
        repo.increment_fetch_failures.assert_not_called()
        repo.record_fetch_error.assert_not_called()

    def test_the_source_wide_ratio_is_over_the_rows_offered(self):
        """OPS-16's verdict is judged over the rows this run fetched. All 40 offered rows answer
        HTTP 503: that is a source-wide failure (40/40), not 40 of 100 with 60 never asked."""
        class _Failed(list):
            failures = {}

        clock = _Clock()
        svc, _ = _service(_rows(100), clock)

        def crawl_failing(news, website_name, throttle):
            clock.now += BATCH_S
            empty = _Failed()
            empty.failures = {s.sitemap_id: "HTTP 503" for s in news}
            return empty
        svc.crawler_dict["VIVA"].batch_crawling_details.side_effect = crawl_failing

        svc.crawl_newsdetails("VIVA", deadline=clock.now + 450)

        note = svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert "source-wide fetch failure: 40/40" in note, note

    def test_the_estimate_is_the_slowest_batch_so_far_not_the_last(self):
        """Batches of 200, 50, 50, 50 ... s with 560 s to go. The estimate stays 200 s:
        batch 5 starts at 350 s (350 + 200 = 550 <= 560), batch 6 would start at 400 s
        (600 > 560). With the last batch (50 s) as the estimate, 7 batches would run."""
        clock = _Clock()
        svc, offered = _service(_rows(100), clock, batch_seconds=[200, 50, 50, 50, 50, 50, 50])

        svc.crawl_newsdetails("VIVA", deadline=clock.now + 560)

        assert len(offered) == 5

    def test_the_first_batch_always_runs(self):
        """A deadline already passed still does one batch: the hard kill is the backstop."""
        clock = _Clock()
        svc, offered = _service(_rows(100), clock)

        svc.crawl_newsdetails("VIVA", deadline=clock.now - 1)

        assert len(offered) == 1
        assert _flushed(svc.data_flow_repo)

    @pytest.mark.parametrize("deadline", [None, 10 ** 9])
    def test_without_a_tight_deadline_every_batch_runs_and_there_is_no_note(self, deadline):
        clock = _Clock()
        svc, offered = _service(_rows(100), clock)

        svc.crawl_newsdetails("VIVA", deadline=deadline)

        assert len(offered) == 10
        assert svc.data_flow_repo.log_crawl_complete.call_args.kwargs["note"] is None

    def test_the_end_of_run_steps_still_run(self):
        """SYS-54's discard runs after a soft stop, inside the deferred block: once when the block
        opens (SYS-57) and once after the last batch."""
        clock = _Clock()
        svc, _ = _service(_rows(100), clock)

        svc.crawl_newsdetails("VIVA", deadline=clock.now + 450)

        assert svc.data_flow_repo.discard_terminal_embeddings.call_count == 2


class TestTheApiPassesTheDeadline:
    @pytest.mark.parametrize("task", ["full_text", "all"])
    def test_crawl_website_hands_it_to_the_full_text_crawl(self, task):
        from newscrawler.application.api.crawler_api import CrawlerAPI
        service = MagicMock()
        api = CrawlerAPI.__new__(CrawlerAPI)
        api.crawler_service = service

        api.crawl_website("VIVA", task, deadline=123.0)

        service.crawl_newsdetails.assert_called_once_with(website_name="VIVA", deadline=123.0)
