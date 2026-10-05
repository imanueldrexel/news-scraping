"""OPS-38 (#212): `task=newsletter` takes a date and defaults to yesterday, and
scripts/run_scheduled_newsletter.py runs it, reports it, and exits 2 under the
run lock. Offline: fake service, fake rows, no Telegram."""
import importlib.util
import os
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from newscrawler.application.api.crawler_api import CrawlerAPI, default_newsletter_date
from newscrawler.application.api.lambda_function import lambda_handler

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "scripts", "run_scheduled_newsletter.py")


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("run_scheduled_newsletter", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDateOnTheTask:
    def test_without_a_date_the_digest_is_yesterdays(self):
        svc = MagicMock()
        CrawlerAPI(svc).crawl_websites_in_batch([], task="newsletter")
        svc.generate_newsletter.assert_called_once_with(date.today() - timedelta(days=1))

    def test_the_date_asked_for_is_the_date_digested(self):
        svc = MagicMock()
        # a date that is never "yesterday", so dropping the argument cannot pass by coincidence
        CrawlerAPI(svc).crawl_websites_in_batch([], task="newsletter", target_date=date(2026, 9, 1))
        svc.generate_newsletter.assert_called_once_with(date(2026, 9, 1))

    def test_the_default_is_a_finished_day(self):
        assert default_newsletter_date() < date.today()

    def test_a_date_on_a_crawl_task_is_refused_before_any_work(self):
        svc = MagicMock()
        with pytest.raises(ValueError, match="newsletter"):
            CrawlerAPI(svc).crawl_websites_in_batch(["KOMPAS"], task="sitemap", target_date=date(2026, 10, 3))
        assert svc.method_calls == []

    def test_process_event_passes_the_parsed_date(self):
        api = MagicMock()
        with patch.object(lambda_handler, "init_crawler", return_value=api):
            lambda_handler.process_event({"task": "newsletter", "date": "2026-10-03"}, None)
        api.crawl_websites_in_batch.assert_called_once_with(website_names=[], task="newsletter",
                                                            target_date=date(2026, 10, 3))

    @pytest.mark.parametrize("event", [
        {"task": "newsletter", "date": "03-10-2026"},
        {"task": "newsletter", "date": "not a date"},
        {"task": "extract_knowledge", "date": "2026-10-03"},
    ])
    def test_a_bad_or_misplaced_date_fails_before_the_crawler_is_built(self, event):
        with patch.object(lambda_handler, "init_crawler",
                          side_effect=AssertionError("built the crawler for a bad event")):
            with pytest.raises(ValueError):
                lambda_handler.process_event(event, None)


class TestScript:
    def test_the_default_date_is_the_previous_day(self, script):
        assert script.default_date(date(2026, 10, 4)) == date(2026, 10, 3)
        assert script.default_date(date(2026, 3, 1)) == date(2026, 2, 28)

    def test_today_and_the_future_are_refused(self, script, monkeypatch):
        # a broken guard must fail this test, not run the script (DBT-53)
        monkeypatch.setattr(script, "_run", lambda *a: pytest.fail("ran for a date that is not a finished day"))
        monkeypatch.setattr(script, "open_run_log", lambda d: (None, None))      # and writes no log file
        assert script.main(["--date", date.today().isoformat()]) == 1
        assert script.main(["--date", (date.today() + timedelta(days=1)).isoformat()]) == 1

    def test_a_malformed_date_is_refused(self, script, monkeypatch):
        monkeypatch.setattr(script, "_run", lambda *a: pytest.fail("ran for a malformed date"))
        monkeypatch.setattr(script, "open_run_log", lambda d: (None, None))
        assert script.main(["--date", "yesterday"]) == 1

    def test_dry_run_builds_nothing(self, script):
        with patch.object(script, "_run", side_effect=AssertionError("ran")):
            assert script.main(["--dry-run"]) == 0

    def test_a_clean_digest_exits_0_and_reports_the_summary_counts(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, SimpleNamespace(
            file_path="digests/2026-10-03.md", article_count=2052, cluster_count=320,
            categories={"markets": {}, "_summaries": {"summarized": 94, "total": 94}}))
        assert script.main(["--date", "2026-10-03"]) == 0
        assert len(sent) == 1
        assert "2052 articles, 320 clusters" in sent[0] and "94/94 summaries" in sent[0]
        assert "DEGRADED" not in sent[0] and "FAILED" not in sent[0]

    def test_a_degraded_digest_says_so(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, SimpleNamespace(
            file_path="d.md", article_count=10, cluster_count=3,
            categories={"_summaries": {"summarized": 0, "total": 3}}), note="kuota harian habis")
        assert script.main(["--date", "2026-10-03"]) == 0
        assert sent[0].startswith("Newsletter DEGRADED") and "kuota harian habis" in sent[0]

    def test_an_empty_day_exits_1_and_says_so(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, SimpleNamespace(file_path="d.md", article_count=0, cluster_count=0,
                                                          categories={}))
        assert script.main(["--date", "2026-10-03"]) == 1
        assert "EMPTY" in sent[0]

    def test_a_failure_is_reported_and_exits_1(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, None, fail=RuntimeError("DB down"))
        assert script.main(["--date", "2026-10-03"]) == 1
        assert sent and "FAILED 2026-10-03" in sent[0] and "RuntimeError: DB down" in sent[0]

    def test_a_missing_digest_row_is_reported_not_hidden(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, None)
        script.main(["--date", "2026-10-03"])
        assert "no newsletter_digests row" in sent[0]

    def test_the_run_lock_refuses_before_the_database_is_touched(self, script, monkeypatch):
        monkeypatch.setattr("newscrawler.tools.run_lock.refused_by_run_lock", lambda log: True)
        monkeypatch.setattr(script, "_run", lambda *a: pytest.fail("ran under a held lock"))
        assert script.main(["--date", "2026-10-03"]) == 2


DIGEST_MD = "# t" + chr(10) * 2 + "### s" + chr(10) * 2 + "- b" + chr(10)


class TestPdfStep:
    """OPS-40 (#235): after the summary, the digest goes to Telegram as a PDF."""

    def test_a_digest_with_articles_is_sent_as_a_pdf(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, SimpleNamespace(file_path="d.md", article_count=5, cluster_count=2,
                                                          categories={}))
        assert script.main(["--date", "2026-10-03"]) == 0
        assert sent.pdfs == [(date(2026, 10, 3), "digests/2026-10-03.md")]

    def test_an_empty_day_sends_no_pdf(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, SimpleNamespace(file_path="d.md", article_count=0, cluster_count=0,
                                                          categories={}))
        script.main(["--date", "2026-10-03"])
        assert sent.pdfs == []

    def test_a_pdf_that_cannot_be_rendered_is_reported_and_the_exit_code_stays_0(self, script, monkeypatch):
        notes = []
        monkeypatch.setattr(script, "_notify", notes.append)
        monkeypatch.setattr("newscrawler.core.newsletter_pdf.render_digest_pdf",
                            lambda path: (_ for _ in ()).throw(OSError("disk full")))
        assert script._send_pdf(date(2026, 10, 3), "digests/2026-10-03.md") is False
        assert len(notes) == 1 and "PDF 2026-10-03 not made" in notes[0] and "disk full" in notes[0]

    def test_a_pdf_that_is_not_delivered_is_reported(self, script, monkeypatch, tmp_path):
        notes = []
        md = tmp_path / "2026-10-03.md"
        md.write_text(DIGEST_MD, encoding="utf-8")
        monkeypatch.setattr(script, "_notify", notes.append)
        monkeypatch.syspath_prepend(os.path.dirname(SCRIPT))
        import notify_telegram
        monkeypatch.setattr(notify_telegram, "send_document", lambda path, caption="": False)
        assert script._send_pdf(date(2026, 10, 3), str(md)) is False
        assert os.path.exists(str(tmp_path / "2026-10-03.pdf"))
        assert len(notes) == 1 and "built but not delivered" in notes[0]

    def test_a_delivered_pdf_sends_the_file_with_the_date_as_caption(self, script, monkeypatch, tmp_path):
        md = tmp_path / "2026-10-03.md"
        md.write_text(DIGEST_MD, encoding="utf-8")
        monkeypatch.setattr(script, "_notify", lambda m: pytest.fail("notified on success: %s" % m))
        monkeypatch.syspath_prepend(os.path.dirname(SCRIPT))
        import notify_telegram
        calls = []
        monkeypatch.setattr(notify_telegram, "send_document", lambda path, caption="": calls.append((path, caption)) or True)
        assert script._send_pdf(date(2026, 10, 3), str(md)) is True
        assert calls == [(str(tmp_path / "2026-10-03.pdf"), "Rangkuman Berita 2026-10-03")]


class _Sent(list):
    pdfs = None


def _wire(script, monkeypatch, row, note=None, fail=None):
    """Fake the crawler, the DB row, the lock and Telegram; return the messages sent
    (`.pdfs`: the PDF steps requested)."""
    sent = _Sent()
    service = MagicMock()
    if fail:
        service.generate_newsletter.side_effect = fail
    else:
        path = type("P", (str,), {"note": note})("digests/2026-10-03.md")
        service.generate_newsletter.return_value = path
    monkeypatch.setattr("newscrawler.application.api.lambda_function.lambda_handler.init_crawler",
                        lambda: SimpleNamespace(crawler_service=service))
    monkeypatch.setattr("newscrawler.infrastructure.network.clients.sqlalchemy_client.SQLAlchemyClient",
                        lambda: MagicMock(get_session=MagicMock(return_value=MagicMock(
                            __enter__=lambda s: MagicMock(), __exit__=lambda s, *a: False))))
    monkeypatch.setattr("newscrawler.tools.run_lock.refused_by_run_lock", lambda log: False)
    monkeypatch.setattr(script, "digest_row", lambda session, d: row)
    monkeypatch.setattr(script, "open_run_log", lambda d: (None, None))
    monkeypatch.setattr(script, "_notify", lambda message: sent.append("Newsletter " + message))
    sent_pdfs = []
    monkeypatch.setattr(script, "_send_pdf", lambda d, path: sent_pdfs.append((d, path)))
    sent.pdfs = sent_pdfs
    return sent
