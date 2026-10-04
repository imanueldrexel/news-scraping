"""OPS-11 (#67): task=extract_knowledge and task=newsletter write a crawl_log
row like the crawl tasks (website="ALL"), and a run in which every Gemini call
failed without a response is recorded as status='failed' with the first error
-- not as a quiet completed run with article_count=0."""
from unittest.mock import MagicMock, patch

import pytest

from newscrawler.core.knowledge_extractor import ExtractionResult
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl


@pytest.fixture
def service():
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.data_flow_repo.log_crawl_start.return_value = 77
    return svc


class TestExtractKnowledgeCrawlLog:
    def test_normal_run_is_completed_with_the_processed_count(self, service):
        service.data_flow_repo.extract_knowledge.return_value = ExtractionResult(12, attempted=15, transient_failures=3,
                                                                                first_transient_error="timeout")
        assert service.extract_knowledge() == 12
        service.data_flow_repo.log_crawl_start.assert_called_once_with("ALL", "extract_knowledge")
        service.data_flow_repo.log_crawl_complete.assert_called_once_with(77, 12, note="12/15 extracted")
        service.data_flow_repo.log_crawl_failed.assert_not_called()

    def test_all_calls_failed_is_a_failed_row_with_the_first_error(self, service, caplog):
        service.data_flow_repo.extract_knowledge.return_value = ExtractionResult(
            0, attempted=50, transient_failures=50, first_transient_error="ClientError: 400 API key not valid")
        assert service.extract_knowledge() == 0
        service.data_flow_repo.log_crawl_complete.assert_not_called()
        log_id, msg = service.data_flow_repo.log_crawl_failed.call_args.args
        assert log_id == 77
        assert "all 50 extraction calls failed" in msg and "API key not valid" in msg
        assert any(r.levelname == "ERROR" and "FAILED" in r.message for r in caplog.records)

    def test_a_plain_int_from_an_older_repository_still_completes(self, service):
        service.data_flow_repo.extract_knowledge.return_value = 4
        assert service.extract_knowledge() == 4
        service.data_flow_repo.log_crawl_complete.assert_called_once_with(77, 4, note=None)

    def test_an_exception_is_a_failed_row_and_propagates(self, service):
        service.data_flow_repo.extract_knowledge.side_effect = RuntimeError("db down")
        with pytest.raises(RuntimeError):
            service.extract_knowledge()
        service.data_flow_repo.log_crawl_failed.assert_called_once_with(77, "db down")


    def test_the_row_carries_tokens_cost_and_why_the_run_stopped(self, service):
        """SYS-39 (#125): what a run spent and why it ended early, beside the count."""
        service.data_flow_repo.extract_knowledge.return_value = ExtractionResult(
            40, attempted=42, transient_failures=2, input_tokens=31000, output_tokens=12000, cost_usd=0.0118,
            stopped="peak hours (UTC weekdays 01-04, 06-10)")
        service.extract_knowledge()
        note = service.data_flow_repo.log_crawl_complete.call_args.kwargs["note"]
        assert "40/42 extracted" in note and "31000 in / 12000 out tokens, $0.0118" in note
        assert "stopped: peak hours" in note


class TestNewsletterCrawlLog:
    def test_generated_digest_is_completed(self, service):
        service.data_flow_repo.generate_newsletter.return_value = "digests/2026-09-22.md"
        assert service.generate_newsletter() == "digests/2026-09-22.md"
        service.data_flow_repo.log_crawl_start.assert_called_once_with("ALL", "newsletter")
        service.data_flow_repo.log_crawl_complete.assert_called_once_with(77, 1, note=None)

    def test_a_degraded_digest_puts_its_reason_on_the_row(self, service):
        """SYS-68 (#216): the digest path carries `.note`; crawl_log says what the file says."""
        from newscrawler.core.newsletter_generator import DigestPath
        path = DigestPath("digests/2026-09-22.md", "digest degraded: Ringkasan AI: 0/9")
        service.data_flow_repo.generate_newsletter.return_value = path
        service.generate_newsletter()
        service.data_flow_repo.log_crawl_complete.assert_called_once_with(
            77, 1, note="digest degraded: Ringkasan AI: 0/9")

    def test_exception_is_a_failed_row_and_propagates(self, service):
        service.data_flow_repo.generate_newsletter.side_effect = ValueError("no digest")
        with pytest.raises(ValueError):
            service.generate_newsletter("2026-09-22")
        service.data_flow_repo.log_crawl_failed.assert_called_once_with(77, "no digest")
