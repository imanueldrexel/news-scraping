"""
SYS-16: a sitemap rejected by the semantic filter and a sitemap whose extraction
came back empty both used to look identical to load_all_sitemaps -- last_crawl_attempt
set, no articles row -- so both were re-selected forever on the normal cooldown. A
filter rejection is deterministic (same headline/text, same INTERESTS list will
reject it again), so it should stop being re-queued; an empty extraction is transient
(a layout fix, or a later fetch, could still produce something), so it keeps the
normal cooldown retry.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from newscrawler.core.importance_filter import FilterDecision
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl


def decision(flag: bool, gate: str = "score", score_passed=None):
    """SYS-35: the service reads `classify()`; `is_important()` is a wrapper."""
    return FilterDecision(is_important=flag, gate=gate,
                          score_passed=flag if score_passed is None else score_passed)


@pytest.fixture
def service():
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.crawler_dict = {"TEST_SITE": MagicMock()}
    svc.data_flow_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=i) for i in (1, 2, 3)]
    # SYS-34: a MagicMock repo "knows" no categories; return None so the
    # unseen-category check is skipped unless a test sets it explicitly.
    svc.data_flow_repo.get_saved_category_pairs.return_value = None
    # SYS-04: the 'saved' stamp is now driven by what save_newsdetails_data reports
    # as actually committed, not by what was handed to it -- default to "everything
    # handed in commits" so this file's classification tests (not about persistence
    # failure) don't also have to restate the persistence layer's behavior.
    svc.data_flow_repo.save_newsdetails_data.side_effect = (
        lambda dtos: [d.sitemap_id for d in dtos]
    )
    return svc


def article(sitemap_id, text, title="Title"):
    return NewsDetailsDTO(sitemap_id=sitemap_id, extracted_text=text, meta_data={"title": title}, reporter=[])


def sitemap(sitemap_id, category, headline="Headline"):
    return SitemapDTO(sitemap_id=sitemap_id, headline=headline, link=f"http://t/{sitemap_id}",
                      sources="TEST_SITE", category=category)


def per_batch(articles):
    """batch_crawling_details side effect that returns only the batch's own
    articles -- the service splits the queue into up to 10 batches, and a
    constant return_value would hand every article to every batch."""
    by_id = {a.sitemap_id: a for a in articles}
    return lambda news, website_name: [by_id[s.sitemap_id] for s in news if s.sitemap_id in by_id]


class TestTerminalStateClassification:
    def test_off_topic_article_with_real_text_is_marked_rejected_filter(self, service):
        service.semantic_filter.classify.return_value = decision(False)
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(1, ["Celebrity gossip about a wedding."])
        ]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_any_call([1], "rejected_filter")

    def test_empty_extraction_is_marked_empty_extraction_not_rejected_filter(self, service):
        service.semantic_filter.classify.return_value = decision(False)
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(2, [])  # all extractors returned nothing usable
        ]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_any_call([2], "empty_extraction")
        calls = [c.args for c in service.data_flow_repo.mark_sitemaps_status.call_args_list]
        assert ([2], "rejected_filter") not in calls

    def test_empty_extraction_never_reaches_the_filter_even_under_a_news_category(self, service):
        """SYS-35: with the category allow-set a bare title under `bisnis` would
        be waved through and chunk to nothing; the empty body is decided first."""
        service.semantic_filter.classify.return_value = decision(True, gate="allow")
        service.data_flow_repo.load_sitemap_data.return_value = [sitemap(2, "bisnis")]
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [article(2, [], title="Rupiah")]

        service.crawl_newsdetails("TEST_SITE")

        service.semantic_filter.classify.assert_not_called()
        service.data_flow_repo.mark_sitemaps_status.assert_any_call([2], "empty_extraction")
        service.data_flow_repo.save_chunk_data.assert_not_called()

    def test_important_and_embedded_article_is_marked_saved(self, service):
        service.semantic_filter.classify.return_value = decision(True)
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(3, ["Real economic news about banking rates."])
        ]
        service.data_flow_repo.save_chunk_data.return_value = [3]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_any_call([3], "saved")

    def test_mixed_batch_classifies_each_sitemap_independently(self, service):
        def fake_classify(text, category=None):
            return decision("banking" in text)

        service.semantic_filter.classify.side_effect = fake_classify
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(1, ["Real economic news about banking rates."]),  # important -> saved
            article(2, ["Celebrity gossip."]),                        # rejected_filter
            article(3, []),                                           # empty_extraction
        ]
        service.data_flow_repo.save_chunk_data.return_value = [1]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_any_call([2], "rejected_filter")
        service.data_flow_repo.mark_sitemaps_status.assert_any_call([3], "empty_extraction")
        service.data_flow_repo.mark_sitemaps_status.assert_any_call([1], "saved")

    def test_a_filter_exception_marks_neither_status_and_stays_pending(self, service):
        """An error during filtering isn't a deterministic rejection -- it should
        neither be excluded permanently nor pinned to empty_extraction; leaving its
        crawl_status untouched (pending) means it retries at the normal cooldown."""
        service.semantic_filter.classify.side_effect = ValueError("boom")
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [
            article(1, ["Some text."])
        ]

        service.crawl_newsdetails("TEST_SITE")

        service.data_flow_repo.mark_sitemaps_status.assert_not_called()

    def test_category_is_passed_to_the_filter(self, service):
        service.semantic_filter.classify.return_value = decision(False)
        service.data_flow_repo.load_sitemap_data.return_value = [sitemap(1, "hiburan")]
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [article(1, ["x"], title="T")]

        service.crawl_newsdetails("TEST_SITE")

        service.semantic_filter.classify.assert_called_once_with("T x", category="hiburan")


class TestFilterTelemetry:
    """SYS-35 (#118, fix 4): the per-run pass-rate stat on news categories."""

    def test_score_recall_on_news_categories_is_logged_per_category(self, service, caplog):
        def fake_classify(text, category=None):
            # bisnis: 2 saved by category, score would have kept 1 of them.
            return decision(True, gate="allow", score_passed="oil" not in text)

        service.semantic_filter.classify.side_effect = fake_classify
        service.data_flow_repo.load_sitemap_data.return_value = [sitemap(1, "bisnis"), sitemap(2, "bisnis")]
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = per_batch([
            article(1, ["oil prices fell"]), article(2, ["BI raised rates"]),
        ])
        service.data_flow_repo.save_chunk_data.side_effect = lambda chunks: [1, 2]

        with caplog.at_level(logging.INFO, logger="newscrawler.domain.services.crawler_service_impl"):
            service.crawl_newsdetails("TEST_SITE")

        stat_lines = [r.message for r in caplog.records if "semantic-score recall on news categories" in r.message]
        assert len(stat_lines) == 1
        assert "bisnis=1/2 (50%)" in stat_lines[0]
        gate_lines = [r.message for r in caplog.records if "filter decisions this run" in r.message]
        assert gate_lines and "allow=2" in gate_lines[0]


class TestUnseenCategoryWarning:
    """SYS-34 (#115, fix c): the first save under a category this source has
    never saved under before is a WARNING, so the next new vocabulary is seen
    on day one instead of by the next audit."""

    def _run(self, service, known, categories):
        service.data_flow_repo.get_saved_category_pairs.return_value = known
        service.semantic_filter.classify.return_value = decision(True)
        service.data_flow_repo.load_sitemap_data.return_value = [
            sitemap(i, cat, headline=f"H{i}") for i, cat in enumerate(categories, 1)
        ]
        service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = per_batch([
            article(i, ["body"]) for i in range(1, len(categories) + 1)
        ])
        service.data_flow_repo.save_chunk_data.side_effect = lambda chunks: list(range(1, len(categories) + 1))

    def test_first_save_under_an_unseen_category_warns_once(self, service, caplog):
        self._run(service, known={("TEST_SITE", "business")}, categories=["hype", "hype", "business"])

        with caplog.at_level(logging.WARNING, logger="newscrawler.domain.services.crawler_service_impl"):
            service.crawl_newsdetails("TEST_SITE")

        warnings = [r.message for r in caplog.records if "never seen before" in r.message]
        assert len(warnings) == 1
        assert "'hype'" in warnings[0] and "H1" in warnings[0]

    def test_known_category_does_not_warn(self, service, caplog):
        self._run(service, known={("TEST_SITE", "business")}, categories=["business", "Business"])

        with caplog.at_level(logging.WARNING, logger="newscrawler.domain.services.crawler_service_impl"):
            service.crawl_newsdetails("TEST_SITE")

        assert not [r for r in caplog.records if "never seen before" in r.message]

    def test_repository_that_cannot_answer_skips_the_check(self, service, caplog):
        service.data_flow_repo.get_saved_category_pairs.side_effect = RuntimeError("db down")
        service.semantic_filter.classify.return_value = decision(True)
        service.data_flow_repo.load_sitemap_data.return_value = [sitemap(1, "hype")]
        service.crawler_dict["TEST_SITE"].batch_crawling_details.return_value = [article(1, ["body"])]
        service.data_flow_repo.save_chunk_data.return_value = [1]

        with caplog.at_level(logging.WARNING, logger="newscrawler.domain.services.crawler_service_impl"):
            service.crawl_newsdetails("TEST_SITE")

        assert not [r for r in caplog.records if "never seen before" in r.message]
        assert [r for r in caplog.records if "unseen-category check skipped" in r.message]
        service.data_flow_repo.mark_sitemaps_status.assert_any_call([1], "saved")
