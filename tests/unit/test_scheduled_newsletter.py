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
        api, service = MagicMock(), MagicMock()
        with patch("newscrawler.application.newsletter_app.build_newsletter_service", return_value=service),                 patch.object(lambda_handler, "CrawlerAPI", return_value=api) as crawler_api,                 patch.object(lambda_handler, "init_crawler", side_effect=AssertionError("built the whole crawler")):
            lambda_handler.process_event({"task": "newsletter", "date": "2026-10-03"}, None)
        crawler_api.assert_called_once_with(service)           # DBT-74: the newsletter's own composition root
        api.crawl_websites_in_batch.assert_called_once_with(website_names=[], task="newsletter",
                                                            target_date=date(2026, 10, 3))

    @pytest.mark.parametrize("event", [
        {"task": "newsletter", "date": "03-10-2026"},
        {"task": "newsletter", "date": "not a date"},
        {"task": "extract_knowledge", "date": "2026-10-03"},
    ])
    def test_a_bad_or_misplaced_date_fails_before_the_crawler_is_built(self, event):
        with patch.object(lambda_handler, "init_crawler",
                          side_effect=AssertionError("built the crawler for a bad event")),                 patch("newscrawler.application.newsletter_app.build_newsletter_service",
                      side_effect=AssertionError("built the newsletter for a bad event")):
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

EDITION_MD = """# Rangkuman Berita

> Sabtu, 3 Oktober 2026 · ±5 menit baca

## Hari Ini dalam 60 Detik

- Harga emas Antam bertahan di Rp2.574.000 per gram.
- DPR sahkan APBN 2027 <belanja> & pajak.
- OPEC+ tahan target produksi minyak November.

## Berita Utama

""" + "".join("### [Berita %d](http://x/%d)\n\nInti %d.\n\n" % (i, i, i)
              + "**Diberitakan 3 portal** · [Baca di Kontan →](http://x/%d)\n\n" % i for i in range(7)) + """## Sekilas

- **Hukum ·** Sidang perdana kasus pungli terminal.

---

*Disarikan dari 10 artikel di 3 portal.*
"""


class TestRunDelivers:
    """The script hands every day with articles to `_deliver` (OPS-43), and no other."""

    def test_a_digest_with_articles_is_delivered(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, SimpleNamespace(file_path="d.md", article_count=5, cluster_count=2,
                                                          categories={}), edition="digests/2026-10-03-ringkas.md")
        assert script.main(["--date", "2026-10-03"]) == 0
        assert sent.deliveries == [(date(2026, 10, 3), "digests/2026-10-03.md", "digests/2026-10-03-ringkas.md")]

    def test_an_empty_day_delivers_nothing(self, script, monkeypatch):
        sent = _wire(script, monkeypatch, SimpleNamespace(file_path="d.md", article_count=0, cluster_count=0,
                                                          categories={}))
        script.main(["--date", "2026-10-03"])
        assert sent.deliveries == []


class _Telegram:
    """notify_telegram faked: what was sent, in order, and what fails."""

    def __init__(self, monkeypatch, message_ok=True, document_ok=True):
        monkeypatch.syspath_prepend(os.path.dirname(SCRIPT))
        import notify_telegram
        self.sent = []
        monkeypatch.setattr(notify_telegram, "send_html",
                            lambda text: self.sent.append(("message", text)) or message_ok)
        monkeypatch.setattr(notify_telegram, "send_document",
                            lambda path, caption="": self.sent.append(("document", path, caption)) or document_ok)

    def messages(self):
        return [s[1] for s in self.sent if s[0] == "message"]

    def documents(self):
        return [s[1:] for s in self.sent if s[0] == "document"]


@pytest.fixture
def files(tmp_path):
    digest = tmp_path / "2026-10-03.md"
    digest.write_text(DIGEST_MD, encoding="utf-8")
    edition = tmp_path / "2026-10-03-ringkas.md"
    edition.write_text(EDITION_MD, encoding="utf-8")
    return str(digest), str(edition)


ROW = SimpleNamespace(article_count=10, cluster_count=4, categories={"_summaries": {"summarized": 80, "total": 90}})


class TestDelivery:
    """OPS-43 (#243): a message with the 60-second block, then the edition's
    phone PDF; the full digest is the archive and is not sent."""

    def test_a_normal_day_sends_the_message_then_the_edition_pdf(self, script, monkeypatch, files):
        tg = _Telegram(monkeypatch)
        notes = []
        monkeypatch.setattr(script, "_notify", notes.append)
        digest, edition = files
        script._deliver(date(2026, 10, 3), digest, edition, ROW)
        assert [s[0] for s in tg.sent] == ["message", "document"]
        (path, caption), = tg.documents()
        assert path.endswith("2026-10-03-ringkas.pdf") and os.path.exists(path)
        assert caption == "Rangkuman Berita · Sabtu, 3 Okt 2026"
        assert not os.path.exists(digest.replace(".md", ".pdf"))          # the archive is neither rendered nor sent
        assert notes == []

    def test_the_message_is_the_sixty_second_block(self, script, monkeypatch, files):
        tg = _Telegram(monkeypatch)
        script._deliver(date(2026, 10, 3), *files, ROW)
        (text,) = tg.messages()
        lines = text.split("\n")
        assert lines[0] == "<b>Rangkuman Berita</b> · Sabtu, 3 Okt 2026 (±5 menit)"
        bullets = [l for l in lines if l.startswith("• ")]
        assert len(bullets) == 3
        assert "• DPR sahkan APBN 2027 &lt;belanja&gt; &amp; pajak." in bullets      # content is escaped
        assert lines[-1] == "Buka PDF untuk 7 berita utama dan sekilas lainnya."
        assert len(text) <= 4096

    def test_a_message_that_fails_still_sends_the_pdf(self, script, monkeypatch, files):
        tg = _Telegram(monkeypatch, message_ok=False)
        notes = []
        monkeypatch.setattr(script, "_notify", notes.append)
        script._deliver(date(2026, 10, 3), *files, ROW)
        assert len(tg.documents()) == 1
        assert notes == ["reader message not delivered to Telegram"]

    def test_a_pdf_that_cannot_be_made_is_said_in_the_message(self, script, monkeypatch, files):
        tg = _Telegram(monkeypatch)
        notes = []
        monkeypatch.setattr(script, "_notify", notes.append)
        monkeypatch.setattr("newscrawler.core.newsletter_pdf.render_edition_pdf",
                            lambda path: (_ for _ in ()).throw(OSError("disk full")))
        script._deliver(date(2026, 10, 3), *files, ROW)
        (text,) = tg.messages()
        assert text.split("\n")[-1] == "PDF tidak tersedia hari ini." and "Buka PDF" not in text
        assert tg.documents() == []
        assert len(notes) == 1 and "PDF 2026-10-03 not made" in notes[0] and "disk full" in notes[0]

    def test_without_an_edition_the_full_digest_is_sent_with_the_notice(self, script, monkeypatch, files):
        tg = _Telegram(monkeypatch)
        digest, _ = files
        script._deliver(date(2026, 10, 3), digest, None, ROW)
        (text,) = tg.messages()
        assert "Edisi 5 menit tidak tersedia hari ini; terlampir edisi lengkapnya." in text
        assert "Sebagian ringkasan tidak tersedia hari ini. 10 berita hanya ditampilkan judulnya." in text
        (path, caption), = tg.documents()
        assert path == digest.replace(".md", ".pdf")

    def test_without_an_edition_and_every_summary_real_there_is_no_summary_notice(self, script, monkeypatch, files):
        tg = _Telegram(monkeypatch)
        row = SimpleNamespace(article_count=10, cluster_count=4,
                              categories={"_summaries": {"summarized": 9, "total": 9}})
        script._deliver(date(2026, 10, 3), files[0], None, row)
        assert "Sebagian ringkasan" not in tg.messages()[0]

    def test_an_undelivered_pdf_is_reported(self, script, monkeypatch, files):
        _Telegram(monkeypatch, document_ok=False)
        notes = []
        monkeypatch.setattr(script, "_notify", notes.append)
        script._deliver(date(2026, 10, 3), *files, ROW)
        assert len(notes) == 1 and "built but not delivered" in notes[0]

    @pytest.mark.parametrize("edition", [True, False], ids=["edition", "full-digest"])
    def test_a_promised_pdf_that_does_not_arrive_is_said_to_the_reader(self, script, monkeypatch, files, edition):
        """OPS-44 (#248): the message promised a PDF; its upload then failed."""
        tg = _Telegram(monkeypatch, document_ok=False)
        notes = []
        monkeypatch.setattr(script, "_notify", notes.append)
        script._deliver(date(2026, 10, 3), files[0], files[1] if edition else None, ROW)
        assert [s[0] for s in tg.sent] == ["message", "document", "message"]
        assert tg.messages()[-1] == "PDF tidak tersedia hari ini."
        assert len(notes) == 1 and "built but not delivered" in notes[0]       # the operator's line still goes

    def test_a_digest_pdf_that_cannot_be_made_after_the_message_is_said_to_the_reader(self, script, monkeypatch,
                                                                                    files):
        tg = _Telegram(monkeypatch)
        monkeypatch.setattr(script, "_notify", lambda note: None)
        monkeypatch.setattr("newscrawler.core.newsletter_pdf.render_digest_pdf",
                            lambda path: (_ for _ in ()).throw(OSError("disk full")))
        script._deliver(date(2026, 10, 3), files[0], None, ROW)
        assert "terlampir edisi lengkapnya" in tg.messages()[0]
        assert tg.messages()[-1] == "PDF tidak tersedia hari ini." and tg.documents() == []

    def test_a_delivered_pdf_or_one_the_message_never_promised_needs_no_follow_up(self, script, monkeypatch, files):
        tg = _Telegram(monkeypatch)
        script._deliver(date(2026, 10, 3), *files, ROW)
        assert len(tg.messages()) == 1
        tg = _Telegram(monkeypatch)
        monkeypatch.setattr(script, "_notify", lambda note: None)
        monkeypatch.setattr("newscrawler.core.newsletter_pdf.render_edition_pdf",
                            lambda path: (_ for _ in ()).throw(OSError("disk full")))
        script._deliver(date(2026, 10, 3), *files, ROW)
        assert len(tg.messages()) == 1 and tg.messages()[0].endswith("PDF tidak tersedia hari ini.")

    def test_a_message_is_kept_under_telegrams_limit(self, script):
        text = script.edition_message(date(2026, 10, 3), ["kata " * 400] * 5, 7)
        assert len(text) <= 4096 and text.count("• ") < 5
        assert text.endswith("Buka PDF untuk 7 berita utama dan sekilas lainnya.")

    def test_the_full_digest_pdf_still_builds_for_the_archive(self, script, monkeypatch, files):
        """OPS-40's path is the fallback: a digest PDF is still made when there is no edition."""
        _Telegram(monkeypatch)
        script._deliver(date(2026, 10, 3), files[0], None, ROW)
        assert os.path.exists(files[0].replace(".md", ".pdf"))


class _Sent(list):
    deliveries = None


def _wire(script, monkeypatch, row, note=None, fail=None, edition=None):
    """Fake the crawler, the DB row, the lock and Telegram; return the messages sent
    (`.deliveries`: the reader deliveries requested)."""
    sent = _Sent()
    service = MagicMock()
    if fail:
        service.generate_newsletter.side_effect = fail
    else:
        path = type("P", (str,), {"note": note, "edition": edition})("digests/2026-10-03.md")
        service.generate_newsletter.return_value = path
    # DBT-74: the script builds the newsletter's own composition root, never the whole crawler.
    monkeypatch.setattr("newscrawler.application.newsletter_app.build_newsletter_service", lambda: service)
    monkeypatch.setattr("newscrawler.application.api.lambda_function.lambda_handler.init_crawler",
                        lambda: (_ for _ in ()).throw(AssertionError("the newsletter built the whole crawler")))
    monkeypatch.setattr("newscrawler.infrastructure.network.clients.sqlalchemy_client.SQLAlchemyClient",
                        lambda: MagicMock(get_session=MagicMock(return_value=MagicMock(
                            __enter__=lambda s: MagicMock(), __exit__=lambda s, *a: False))))
    monkeypatch.setattr("newscrawler.tools.run_lock.refused_by_run_lock", lambda log: False)
    monkeypatch.setattr(script, "digest_row", lambda session, d: row)
    monkeypatch.setattr(script, "open_run_log", lambda d: (None, None))
    monkeypatch.setattr(script, "_notify", lambda message: sent.append("Newsletter " + message))
    deliveries = []
    monkeypatch.setattr(script, "_deliver", lambda d, path, edition_path, r: deliveries.append((d, path, edition_path)))
    sent.deliveries = deliveries
    return sent
