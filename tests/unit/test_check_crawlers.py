"""
Unit tests for scripts/check_crawlers.py — classification + per-outlet check against a
mocked crawler (no network), the OPS-12 per-outlet timestamps that reach crawl_log,
and the OPS-13 delta against each outlet's previous crawl_log row.
"""
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "check_crawlers.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("check_crawlers", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["check_crawlers.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


cc = _load()


def _detail(text, extractor="site"):
    return SimpleNamespace(extracted_text=text, meta_data={"extractor": extractor})


class TestPickBranch:
    """OPS-03: sample the finance/economy section when one exists, not just
    whichever branch a site's sitemap index happens to list first."""

    def test_prefers_a_branch_matching_the_finance_pattern(self):
        branches = {"Bobo": "http://e.com/bobo.xml", "ekonomi": "http://e.com/ekonomi.xml",
                    "olahraga": "http://e.com/olahraga.xml"}
        name, link = cc.pick_branch(branches)
        assert name == "ekonomi" and link == "http://e.com/ekonomi.xml"

    def test_falls_back_to_the_first_branch_when_none_match(self):
        branches = {"Bobo": "http://e.com/bobo.xml", "olahraga": "http://e.com/olahraga.xml"}
        name, link = cc.pick_branch(branches)
        assert name == "Bobo"

    def test_matches_case_insensitively_and_substrings(self):
        branches = {"AksaraJabar": "x", "EkonomiBisnis": "http://e.com/eb.xml"}
        name, _ = cc.pick_branch(branches)
        assert name == "EkonomiBisnis"

    def test_single_branch_is_returned_regardless_of_name(self):
        branches = {"www": "http://e.com/www.xml"}
        assert cc.pick_branch(branches) == ("www", "http://e.com/www.xml")

    def test_matches_any_of_the_documented_finance_keywords(self):
        for keyword in ("ekonomi", "bisnis", "market", "finance", "keuangan", "money", "uang"):
            branches = {"other": "x", keyword: "y"}
            name, _ = cc.pick_branch(branches)
            assert name == keyword, keyword

    def test_first_match_wins_when_multiple_finance_branches_exist(self):
        branches = {"olahraga": "x", "bisnis": "http://e.com/bisnis.xml", "market": "http://e.com/market.xml"}
        name, _ = cc.pick_branch(branches)
        assert name == "bisnis"


class TestClassify:
    def test_ok(self):
        assert cc.classify(sitemap_links=10, detail_ok=2, extractors=["site", "site"]) == cc.STATUS_OK

    def test_ok_when_at_least_one_sample_used_the_site_extractor(self):
        assert cc.classify(sitemap_links=10, detail_ok=2, extractors=["site", "trafilatura"]) == cc.STATUS_OK

    def test_fallback_when_no_sample_used_the_site_extractor(self):
        assert cc.classify(sitemap_links=10, detail_ok=2, extractors=["trafilatura", "newspaper"]) == cc.STATUS_FALLBACK

    def test_ok_when_extractors_not_provided(self):
        """Backward-compatible default: no extractor info at all doesn't demote to
        FALLBACK -- only a confirmed all-fallback sample set does."""
        assert cc.classify(sitemap_links=10, detail_ok=2) == cc.STATUS_OK

    def test_partial_when_no_extraction(self):
        assert cc.classify(sitemap_links=10, detail_ok=0) == cc.STATUS_PARTIAL

    def test_broken_when_no_links(self):
        assert cc.classify(sitemap_links=0, detail_ok=0) == cc.STATUS_BROKEN

    def test_error_flag(self):
        assert cc.classify(sitemap_links=10, detail_ok=2, error=True) == cc.STATUS_ERROR


class TestExtractedLen:
    def test_list(self):
        assert cc._extracted_len(_detail(["abc", "de"])) == 5

    def test_string(self):
        assert cc._extracted_len(_detail("hello")) == 5

    def test_empty(self):
        assert cc._extracted_len(_detail(None)) == 0
        assert cc._extracted_len(_detail([])) == 0


def _mock_crawler(soup="SOUP", branches=None, articles=None, dtos=None, details=None):
    c = MagicMock()
    c.website_url = "http://example.com/sitemap.xml"
    c.page_loader.get_soup.return_value = soup
    # OPS-17: check_one reads the reason-carrying API now, so the double has to
    # speak it -- otherwise every test here exercises the compatibility path.
    c.page_loader.get_soup_with_reason.return_value = (soup, None if soup else "HTTP 404")
    c._get_branches.return_value = branches if branches is not None else {"news": "http://e.com/news.xml"}
    # DBT-05: FALLBACK is judged against the crawler's declared extractor.
    c.PRIMARY_EXTRACTOR = "site"
    # SRC-35: check_one drops soft branches before sampling one -- apply the
    # real vocabulary here so the mock behaves like a crawler, not a MagicMock.
    from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler as _RealCrawler
    c.drop_soft_branches.side_effect = lambda b: {k: v for k, v in (b or {}).items() if not _RealCrawler.is_soft_branch(k)}
    c._scrape.return_value = articles if articles is not None else [{"link": "http://e.com/a"}]
    c.out_of_scope_reason.return_value = None     # SRC-60: every URL in scope unless a test says otherwise
    c.batch_crawling_sitemap.return_value = dtos if dtos is not None else [SitemapDTO(headline="h", link="http://e.com/a", sources="KOMPAS")]
    c.batch_crawling_details.return_value = details if details is not None else [_detail(["body text here"])]
    return c


class TestCheckOne:
    def test_the_sample_drops_what_production_drops_by_url(self):
        """SRC-60 (#279): production never stores a KUMPARAN reader post; the health sample does
        not fetch one either, and the count is in the result."""
        c = _mock_crawler(articles=[{"link": "https://kumparan.com/kumparannews/a"},
                                    {"link": "https://kumparan.com/tyasafira031/b"}])
        c.out_of_scope_reason.side_effect = lambda link: None if "/kumparannews/" in link else "reader post"
        r = cc.check_one("KUMPARAN", c, sample_size=2)
        assert r["out_of_scope"] == 1 and r["sitemap_links"] == 1
        sampled = c.batch_crawling_sitemap.call_args.args[0]
        assert [a["link"] for a in sampled] == ["https://kumparan.com/kumparannews/a"]

    def test_a_trafilatura_first_source_is_judged_by_its_declaration(self):
        """DBT-05: CNBC is trafilatura by design -- its samples coming from
        trafilatura is OK, not FALLBACK."""
        c = _mock_crawler(details=[_detail(["body text here"], extractor="trafilatura")])
        c.PRIMARY_EXTRACTOR = "trafilatura"
        assert cc.check_one("CNBC", c, sample_size=2)["status"] == cc.STATUS_OK

    def test_happy_path_ok(self):
        r = cc.check_one("KOMPAS", _mock_crawler(), sample_size=2)
        assert r["status"] == cc.STATUS_OK
        assert r["sitemap_links"] == 1
        assert r["detail_ok"] == 1

    def test_scrapes_the_finance_branch_not_just_the_first_one(self):
        """OPS-03: TEMPO-style crawler whose sitemap index lists a non-finance
        branch first ('www') but does have an 'ekonomi' branch further along."""
        c = _mock_crawler(branches={"www": "http://e.com/www.xml", "ekonomi": "http://e.com/ekonomi.xml"})
        r = cc.check_one("TEMPO", c, sample_size=2)
        assert r["branch"] == "ekonomi"
        c._scrape.assert_called_once_with(branch_link="http://e.com/ekonomi.xml", branch_name="ekonomi")

    def test_branch_recorded_even_when_no_finance_branch_exists(self):
        c = _mock_crawler(branches={"suara-pembaca": "http://e.com/x.xml"})
        r = cc.check_one("DETIK", c, sample_size=2)
        assert r["branch"] == "suara-pembaca"

    def test_partial_when_extraction_empty(self):
        c = _mock_crawler(details=[_detail([]), _detail("")])
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_PARTIAL
        assert "extraction" in r["note"].lower()

    def test_broken_when_soup_none(self):
        c = _mock_crawler(soup=None)
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_BROKEN

    def test_broken_when_no_branches(self):
        c = _mock_crawler(branches={})
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_BROKEN

    def test_broken_when_no_links(self):
        c = _mock_crawler(articles=[])
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_BROKEN

    def test_error_when_method_raises(self):
        c = _mock_crawler()
        c._scrape.side_effect = RuntimeError("boom")
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_ERROR
        assert "RuntimeError" in r["note"]

    def test_fallback_when_every_sample_was_rescued(self):
        """OPS-02: articles come through, but the site's own selector produced
        nothing for any of them -- trafilatura/newspaper are doing all the work."""
        c = _mock_crawler(details=[_detail(["rescued body"], extractor="trafilatura")])
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_FALLBACK
        assert "trafilatura" in r["note"]

    def test_ok_when_at_least_one_sample_used_the_site_selector(self):
        c = _mock_crawler(details=[
            _detail(["site body"], extractor="site"),
            _detail(["rescued body"], extractor="trafilatura"),
        ])
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_OK

    def test_repeated_when_a_sample_body_cascades(self):
        """SRC-54 (#177): nested <p> stores each paragraph plus everything after
        it. The sample produced text from the site selector -- the old check
        called that OK -- but the body repeats itself."""
        tail = "Paragraf ketiga menutup artikel dengan jadwal RUPS."
        mid = "Paragraf kedua tentang rencana dividen tahun depan. " + tail
        head = "Paragraf pertama tentang laba bersih emiten naik tajam. " + mid
        c = _mock_crawler(details=[_detail([head, mid, tail], extractor="site"),
                                   _detail(["clean body"], extractor="site")])
        r = cc.check_one("EMITENNEWS", c, sample_size=2)
        assert r["status"] == cc.STATUS_REPEATED
        assert r["cascaded"] == 1
        assert "1/2" in r["note"]
        assert cc.STATUS_REPEATED in cc.UNHEALTHY

    def test_clean_bodies_have_zero_cascaded(self):
        r = cc.check_one("KOMPAS", _mock_crawler(), sample_size=2)
        assert r["cascaded"] == 0


class TestSampleOrder:
    """OPS-30 (#181): EMITENNEWS's first entries are scheduled posts (dated today
    and tomorrow) that soft-404 until they publish."""
    NOW = datetime(2026, 9, 26, 14, 40, tzinfo=timezone(timedelta(hours=7)))

    def _entry(self, link, hours_ago):
        ts = None if hours_ago is None else self.NOW - timedelta(hours=hours_ago)
        return {"link": link, "timestamp": ts}

    def test_settled_entries_are_sampled_before_recent_and_future_ones(self):
        listing = [self._entry("tomorrow", -10), self._entry("today", 14), self._entry("yesterday", 38),
                   self._entry("old", 300)]
        order = [a["link"] for a in cc.sample_order(listing, now=self.NOW)]
        assert order == ["yesterday", "old", "tomorrow", "today"]

    def test_listing_with_nothing_old_enough_is_sampled_as_listed(self):
        listing = [self._entry("a", 1), self._entry("b", None), self._entry("c", -2)]
        assert [a["link"] for a in cc.sample_order(listing, now=self.NOW)] == ["a", "b", "c"]

    def test_check_one_samples_the_settled_entries(self):
        now = datetime.now(timezone.utc)  # check_one uses the real clock
        listing = [{"link": "http://e.com/tomorrow", "timestamp": now + timedelta(hours=10)},
                   {"link": "http://e.com/old", "timestamp": now - timedelta(hours=48)}]
        c = _mock_crawler(articles=listing)
        cc.check_one("EMITENNEWS", c, sample_size=1)
        sampled = c.batch_crawling_sitemap.call_args[0][0]
        assert [a["link"] for a in sampled] == ["http://e.com/old"]


class TestReportingHelpers:
    def test_summary_line_flags_unhealthy(self):
        results = [
            {"website": "KOMPAS", "status": cc.STATUS_OK, "note": ""},
            {"website": "DETIK", "status": cc.STATUS_PARTIAL, "note": "x"},
        ]
        line = cc.summary_line(results)
        assert "DETIK" in line and "OK=1" in line

    def test_summary_line_lists_fallback_as_needs_attention_but_counts_separately(self):
        results = [
            {"website": "KOMPAS", "status": cc.STATUS_OK, "note": ""},
            {"website": "CNBC", "status": cc.STATUS_FALLBACK, "note": "x"},
        ]
        line = cc.summary_line(results)
        assert "CNBC" in line
        assert "FALLBACK=1" in line

    def test_fallback_does_not_affect_exit_code(self):
        """OPS-02: FALLBACK is needs-attention but non-fatal."""
        results = [{"website": "CNBC", "status": cc.STATUS_FALLBACK, "note": "", "sitemap_links": 1}]
        assert not any(r["status"] in cc.UNHEALTHY for r in results)
        assert any(r["status"] in cc.NEEDS_ATTENTION for r in results)

    def test_render_table_has_header_and_rows(self):
        results = [{"website": "KOMPAS", "status": cc.STATUS_OK, "sitemap_links": 5,
                    "dto_count": 3, "detail_total": 3, "detail_ok": 3, "avg_chars": 900, "note": "",
                    "duration_sec": 12.3}]
        table = cc.render_table(results)
        assert "SOURCE" in table and "KOMPAS" in table
        assert "SECS" in table and "12.3" in table


# ── OPS-12 (#75): per-outlet started_at / finished_at ─────────────────────────

def _is_aware_utc(dt):
    return isinstance(dt, datetime) and dt.tzinfo is not None and dt.utcoffset() == timedelta(0)


class TestCheckOneTimestamps:
    """crawl_log's started_at/finished_at must be the outlet's own check window --
    not the logging transaction's NOW() twice -- and must be timezone-aware UTC so
    Postgres converts them exactly as it converts the pipeline's NOW() writes."""

    @pytest.mark.parametrize("crawler_factory", [
        lambda: _mock_crawler(),                                       # OK path
        lambda: _mock_crawler(soup=None),                              # early-return BROKEN
        lambda: _mock_crawler(details=[_detail([])]),                  # PARTIAL
    ])
    def test_every_exit_path_stamps_both_timestamps(self, crawler_factory):
        r = cc.check_one("KOMPAS", crawler_factory(), sample_size=1)
        assert _is_aware_utc(r["started_at"]) and _is_aware_utc(r["finished_at"])
        assert r["finished_at"] >= r["started_at"]
        assert r["duration_sec"] >= 0

    def test_exception_path_stamps_finished_at_too(self):
        c = _mock_crawler()
        c._scrape.side_effect = RuntimeError("boom")
        r = cc.check_one("KOMPAS", c, sample_size=1)
        assert r["status"] == cc.STATUS_ERROR
        assert _is_aware_utc(r["finished_at"])

    def test_duration_reflects_real_elapsed_time(self):
        c = _mock_crawler()
        c._scrape.side_effect = lambda **kw: time.sleep(0.15) or [{"link": "http://e.com/a"}]
        r = cc.check_one("KOMPAS", c, sample_size=1)
        assert (r["finished_at"] - r["started_at"]).total_seconds() >= 0.15
        assert r["duration_sec"] >= 0.1


class TestRunChecksTimeoutRow:
    def test_timeout_row_carries_its_own_window(self):
        c = _mock_crawler()
        # OPS-17: the listing stage fetches through get_soup_with_reason now, so
        # the delay has to be on the call check_one actually makes.
        c.page_loader.get_soup_with_reason.side_effect = lambda url: time.sleep(0.6) or (None, "slow")
        c.page_loader.get_soup.side_effect = lambda url: time.sleep(0.6) or None
        before = cc._utcnow()
        results = cc.run_checks({"SLOW": c}, sample_size=1, workers=1, timeout=0.2)
        assert len(results) == 1
        r = results[0]
        assert r["status"] == cc.STATUS_ERROR and "timeout" in r["note"]
        assert _is_aware_utc(r["started_at"]) and _is_aware_utc(r["finished_at"])
        assert r["started_at"] >= before
        # Timed out at ~0.2s: the window is the time actually budgeted, not zero.
        assert 0.15 <= (r["finished_at"] - r["started_at"]).total_seconds() < 1.0


class TestLogToDb:
    def test_passes_both_timestamps_explicitly_instead_of_defaulting(self):
        """The bug: only finished_at=NOW() was bound, started_at fell to DEFAULT NOW()
        (transaction start), so every row had started_at = finished_at = end of run."""
        session = MagicMock()
        started = datetime(2026, 9, 17, 22, 30, 5, tzinfo=timezone.utc)
        finished = started + timedelta(seconds=42)
        results = [{"website": "KOMPAS", "status": cc.STATUS_OK, "note": "", "sitemap_links": 9,
                    "started_at": started, "finished_at": finished, "duration_sec": 42.0}]

        cc.log_to_db(results, session)

        session.execute.assert_called_once()
        sql, params = session.execute.call_args[0]
        sql_text = str(sql)
        assert "started_at" in sql_text and "finished_at" in sql_text
        assert "NOW()" not in sql_text, "timestamps must come from the result, not the transaction clock"
        assert params["started"] == started
        assert params["finished"] == finished
        assert params["started"] != params["finished"]
        session.commit.assert_called_once()

    def test_status_and_note_encoding_is_unchanged(self):
        session = MagicMock()
        base = {"started_at": cc._utcnow(), "finished_at": cc._utcnow(), "sitemap_links": 0}
        cc.log_to_db([
            dict(base, website="A", status=cc.STATUS_FALLBACK, note="rescued by trafilatura"),
            dict(base, website="B", status=cc.STATUS_BROKEN, note=""),
        ], session)
        p1 = session.execute.call_args_list[0][0][1]
        p2 = session.execute.call_args_list[1][0][1]
        assert p1["s"] == "completed" and p1["e"] == "FALLBACK: rescued by trafilatura"
        assert p2["s"] == "failed" and p2["e"] == "BROKEN"


class TestPayloadSerialization:
    def test_json_report_serializes_the_datetimes(self, tmp_path):
        results = [cc.check_one("KOMPAS", _mock_crawler(), sample_size=1)]
        path = cc.write_report(cc.build_payload(results), str(tmp_path))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        r = data["results"][0]
        assert r["started_at"].endswith("+00:00") and r["finished_at"].endswith("+00:00")
        assert data["summary"].startswith("Crawler health")
        assert data["delta"] is None


# ── OPS-13 (#76): delta against each outlet's previous crawl_log row ──────────

def _r(website, status):
    return {"website": website, "status": status, "note": "", "sitemap_links": 1}


def _prev(status, finished_at=None):
    return {"status": status, "finished_at": finished_at or datetime(2026, 9, 17, 22, 32, 10, tzinfo=timezone.utc)}


class TestClassifyChange:
    @pytest.mark.parametrize("now, before, expected", [
        (cc.STATUS_BROKEN, cc.STATUS_OK, cc.CHANGE_NEW),
        (cc.STATUS_FALLBACK, cc.STATUS_OK, cc.CHANGE_NEW),        # a dead selector is NEW even though non-fatal
        (cc.STATUS_OK, cc.STATUS_BROKEN, cc.CHANGE_RECOVERED),
        (cc.STATUS_OK, cc.STATUS_FALLBACK, cc.CHANGE_RECOVERED),
        (cc.STATUS_FALLBACK, cc.STATUS_BROKEN, cc.CHANGE_CHANGED),
        (cc.STATUS_BROKEN, cc.STATUS_ERROR, cc.CHANGE_CHANGED),
        (cc.STATUS_BROKEN, cc.STATUS_BROKEN, cc.CHANGE_UNCHANGED),
        (cc.STATUS_OK, cc.STATUS_OK, cc.CHANGE_UNCHANGED),
        (cc.STATUS_BROKEN, None, cc.CHANGE_BASELINE),
        (cc.STATUS_OK, None, cc.CHANGE_BASELINE),
    ])
    def test_table(self, now, before, expected):
        assert cc.classify_change(now, before) == expected


class TestComputeDelta:
    def test_buckets_new_recovered_changed_unchanged(self):
        results = [_r("KOMPAS", cc.STATUS_BROKEN), _r("TEMPO", cc.STATUS_OK),
                   _r("CNBC", cc.STATUS_FALLBACK), _r("ANTARANEWS", cc.STATUS_BROKEN), _r("DETIK", cc.STATUS_OK)]
        previous = {"KOMPAS": _prev(cc.STATUS_OK), "TEMPO": _prev(cc.STATUS_ERROR),
                    "CNBC": _prev(cc.STATUS_BROKEN), "ANTARANEWS": _prev(cc.STATUS_BROKEN), "DETIK": _prev(cc.STATUS_OK)}
        d = cc.compute_delta(results, previous)
        assert d["new"] == [{"website": "KOMPAS", "status": "BROKEN", "previous": "OK"}]
        assert d["recovered"] == [{"website": "TEMPO", "status": "OK", "previous": "ERROR"}]
        assert d["changed"] == [{"website": "CNBC", "status": "FALLBACK", "previous": "BROKEN"}]
        assert [e["website"] for e in d["unchanged"]] == ["ANTARANEWS", "DETIK"]
        assert d["baseline"] == []
        assert d["no_change"] is False

    def test_no_change_when_every_outlet_matches(self):
        results = [_r("A", cc.STATUS_BROKEN), _r("B", cc.STATUS_OK)]
        d = cc.compute_delta(results, {"A": _prev(cc.STATUS_BROKEN), "B": _prev(cc.STATUS_OK)})
        assert d["no_change"] is True
        assert d["compared_to"] == datetime(2026, 9, 17, 22, 32, 10, tzinfo=timezone.utc)

    def test_first_run_with_no_prior_rows_is_all_baseline_not_no_change(self):
        results = [_r("A", cc.STATUS_BROKEN), _r("B", cc.STATUS_OK)]
        d = cc.compute_delta(results, {})
        assert [e["website"] for e in d["baseline"]] == ["A", "B"]
        assert d["no_change"] is False
        assert d["compared_to"] is None

    def test_compares_per_outlet_so_a_partial_manual_run_only_moves_that_outlet(self):
        """Done-when (e): the baseline is the last row *per outlet*. A manual
        `--website KOMPAS --log-db` yesterday evening updated KOMPAS's row only; the
        other outlets still compare against the morning batch, not against nothing."""
        morning = datetime(2026, 9, 17, 22, 32, 10, tzinfo=timezone.utc)
        evening = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
        previous = {"KOMPAS": _prev(cc.STATUS_OK, evening), "ANTARANEWS": _prev(cc.STATUS_BROKEN, morning)}
        d = cc.compute_delta([_r("KOMPAS", cc.STATUS_OK), _r("ANTARANEWS", cc.STATUS_BROKEN)], previous)
        assert d["baseline"] == []
        assert d["no_change"] is True
        assert d["compared_to"] == evening

    def test_does_not_mutate_results(self):
        results = [_r("A", cc.STATUS_OK)]
        snapshot = [dict(r) for r in results]
        cc.compute_delta(results, {"A": _prev(cc.STATUS_BROKEN)})
        assert results == snapshot


class TestLoadPreviousStatuses:
    def test_parses_the_status_prefix_from_error_msg(self):
        ts = datetime(2026, 9, 17, 22, 32, 10, tzinfo=timezone.utc)
        session = MagicMock()
        session.execute.return_value = [
            ("KOMPAS", "OK", ts),
            ("CNBC", "FALLBACK: site selector produced nothing; rescued by trafilatura", ts),
            ("BISNIS", "BROKEN: sitemap fetch failed (get_soup returned None)", ts),
            ("TEMPO", "ERROR: timeout after 60s", ts),
            ("WEIRD", "hand-written note with no status", ts),   # skipped -> treated as no baseline
            ("EMPTY", None, ts),                                 # skipped
        ]
        previous = cc.load_previous_statuses(session)
        assert previous["KOMPAS"] == {"status": "OK", "finished_at": ts}
        assert previous["CNBC"]["status"] == "FALLBACK"
        assert previous["BISNIS"]["status"] == "BROKEN"
        assert previous["TEMPO"]["status"] == "ERROR"
        assert "WEIRD" not in previous and "EMPTY" not in previous

    def test_query_is_per_outlet_and_ordered_newest_first(self):
        session = MagicMock()
        session.execute.return_value = []
        cc.load_previous_statuses(session)
        sql = str(session.execute.call_args[0][0])
        assert "DISTINCT ON (website)" in sql
        assert "task = 'health_check'" in sql
        assert "finished_at DESC" in sql


class TestSummaryLineWithDelta:
    def _results(self):
        return [_r("KOMPAS", cc.STATUS_BROKEN), _r("TEMPO", cc.STATUS_OK), _r("CNBC", cc.STATUS_FALLBACK),
                _r("ANTARANEWS", cc.STATUS_BROKEN), _r("BISNIS", cc.STATUS_BROKEN), _r("DETIK", cc.STATUS_OK)]

    def test_new_breakage_leads_the_first_line_with_previous_status(self):
        previous = {"KOMPAS": _prev(cc.STATUS_OK), "TEMPO": _prev(cc.STATUS_ERROR), "CNBC": _prev(cc.STATUS_BROKEN),
                    "ANTARANEWS": _prev(cc.STATUS_BROKEN), "BISNIS": _prev(cc.STATUS_BROKEN), "DETIK": _prev(cc.STATUS_OK)}
        results = self._results()
        text = cc.summary_line(results, cc.compute_delta(results, previous))
        first, totals = text.split("\n")
        assert first.startswith("Crawler health ")
        assert "NEW: KOMPAS (BROKEN, was OK)" in first
        assert "RECOVERED: TEMPO (OK, was ERROR)" in first
        assert "CHANGED: CNBC (FALLBACK, was BROKEN)" in first
        assert "unchanged: 2 known (2 BROKEN)" in first
        assert first.index("NEW:") < first.index("RECOVERED:")
        assert totals == "Totals: OK=2, FALLBACK=1, PARTIAL=0, BROKEN=3, ERROR=0 (of 6)"
        # The wall of known-broken names is gone from the delta form.
        assert "ANTARANEWS" not in first and "BISNIS" not in first

    def test_no_change_day_says_so_in_the_first_line(self):
        results = self._results()
        previous = {r["website"]: _prev(r["status"]) for r in results}
        text = cc.summary_line(results, cc.compute_delta(results, previous))
        first = text.split("\n")[0]
        assert "no change since" in first
        expected_since = datetime(2026, 9, 17, 22, 32, 10, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        assert expected_since in first
        assert "4 known (3 BROKEN, 1 FALLBACK)" in first
        assert "NEW" not in first and "RECOVERED" not in first

    def test_first_run_lists_baseline_outlets_instead_of_claiming_no_change(self):
        results = self._results()
        first = cc.summary_line(results, cc.compute_delta(results, {})).split("\n")[0]
        assert "NO BASELINE:" in first and "KOMPAS (BROKEN)" in first
        assert "no change" not in first

    def test_all_green_no_change(self):
        results = [_r("A", cc.STATUS_OK), _r("B", cc.STATUS_OK)]
        first = cc.summary_line(results, cc.compute_delta(results, {"A": _prev(cc.STATUS_OK), "B": _prev(cc.STATUS_OK)})).split("\n")[0]
        assert "no change since" in first and "all 2 OK" in first

    def test_legacy_format_without_delta_is_unchanged(self):
        results = [_r("KOMPAS", cc.STATUS_OK), _r("DETIK", cc.STATUS_PARTIAL)]
        line = cc.summary_line(results)
        assert line == "Crawler health: OK=1, FALLBACK=0, PARTIAL=1, BROKEN=0, ERROR=0 (of 2) | needs attention: DETIK"

    def test_payload_carries_delta_and_summary_for_the_wrapper(self):
        results = [_r("KOMPAS", cc.STATUS_BROKEN)]
        delta = cc.compute_delta(results, {"KOMPAS": _prev(cc.STATUS_OK)})
        payload = cc.build_payload(results, delta)
        assert payload["delta"]["new"][0]["website"] == "KOMPAS"
        assert payload["summary"] == cc.summary_line(results, delta)
        json.dumps(payload, default=cc._json_default)  # must round-trip (compared_to is a datetime)


class TestSoftBranchCounters:
    """SRC-35 (#128): the health line carries how many branches a source lists
    and how many were dropped as soft verticals, so a site adding one is
    visible the day it appears."""

    def test_blank_result_has_the_counters(self):
        r = cc._blank_result("X")
        assert r["branches"] == 0 and r["soft_branches"] == 0

    def test_render_shows_branch_counts(self):
        r = cc._blank_result("DETIK")
        r.update({"branch": "berita", "branches": 242, "soft_branches": 62, "status": cc.STATUS_OK})
        out = cc.render_table([r])
        assert "242/62" in out

    def test_render_does_not_truncate_counts_behind_a_long_branch_name(self):
        """OPS-21 (#148): the counts used to share a 14-char cell with the
        branch name, so DETIK's real row ('berita-ekonomi-bisnis', 242, 62)
        printed as '242-6' -- 62 dropped branches read as 6. The name may be
        shortened; the two numbers may not."""
        r = cc._blank_result("MEDIAINDONESIA")
        r.update({"branch": "berita-ekonomi-bisnis", "branches": 283, "soft_branches": 62,
                  "status": cc.STATUS_OK})
        out = cc.render_table([r])
        assert "283/62" in out, out
        assert "283/6 " not in out and "283/-" not in out, out
        # the header names the column, so a reader knows what the pair means
        assert "LISTED/SOFT" in out


class TestPartialRunDoesNotOwnTheDatedReport:
    """OPS-10 (#66): the dated `<date>.json` is the only place `avg_chars`,
    `extractors`, `dto_count` and `note` are kept per outlet -- `crawl_log`
    carries none of them. It was opened in "w" mode and keyed on the date, so a
    `--website X` spot check replaced the scheduled 32-outlet run: on 2026-09-17
    a 32-outlet report written at 07:21 became a 1-outlet report at 13:23. And
    CLAUDE.md tells every contributor to run that spot check before closing an
    SRC ticket."""

    def test_a_full_run_owns_the_dated_report(self):
        from datetime import datetime as dt
        assert cc.report_filename(True, None, now=dt(2026, 9, 17)) == "2026-09-17.json"
        assert cc.report_filename(True, ["KOMPAS"], now=dt(2026, 9, 17)) == "2026-09-17.json"

    def test_a_partial_run_gets_its_own_file(self):
        from datetime import datetime as dt
        assert cc.report_filename(False, ["TRIBUN"], now=dt(2026, 9, 17)) == "2026-09-17-tribun.json"
        assert cc.report_filename(False, ["KOMPAS", "DETIK"], now=dt(2026, 9, 17)) == "2026-09-17-detik-kompas.json"

    def test_a_large_partial_run_gets_a_bounded_name(self):
        from datetime import datetime as dt
        name = cc.report_filename(False, ["A", "B", "C", "D", "E"], now=dt(2026, 9, 17))
        assert name == "2026-09-17-a-and-4-more.json" and len(name) < 40

    def test_the_full_report_survives_a_later_partial_run(self, tmp_path):
        full = {"total": 32, "results": [{"website": "KOMPAS"}]}
        partial = {"total": 1, "results": [{"website": "TRIBUN"}]}
        p_full = cc.write_report(full, str(tmp_path), full_run=True)
        p_part = cc.write_report(partial, str(tmp_path), full_run=False, websites=["TRIBUN"])
        assert p_full != p_part
        with open(p_full, encoding="utf-8") as f:
            assert json.load(f)["total"] == 32, "the scheduled run's report was overwritten"


class TestListingFreshnessAndFetchReason:
    """OPS-17 (#89): two blind spots in the one signal the operator reads daily."""

    def test_the_fetch_reason_reaches_the_note(self):
        crawler = MagicMock()
        crawler.page_loader.get_soup_with_reason.return_value = (None, "HTTP 403")
        r = cc.check_one("BISNIS", crawler, 2)
        assert r["note"] == "sitemap fetch failed: HTTP 403"
        assert r["status"] == cc.STATUS_BROKEN

    @pytest.mark.parametrize("reason,expected", [
        ("HTTP 404", "sitemap fetch failed: HTTP 404"),
        ("SSLError after 5 retries", "sitemap fetch failed: SSLError after 5 retries"),
        ("soft-404: redirected to /", "sitemap fetch failed: soft-404: redirected to /"),
        (None, "sitemap fetch failed: unknown reason"),
    ])
    def test_each_reason_is_distinguishable(self, reason, expected):
        crawler = MagicMock()
        crawler.page_loader.get_soup_with_reason.return_value = (None, reason)
        assert cc.check_one("X", crawler, 2)["note"] == expected

    def test_newest_listed_age_ignores_undated_entries(self):
        now = datetime(2026, 9, 25, tzinfo=timezone.utc)
        arts = [{"timestamp": None}, {"timestamp": datetime(2026, 9, 20, tzinfo=timezone.utc)},
                {"timestamp": datetime(2026, 9, 24, tzinfo=timezone.utc)}]
        newest, age = cc.newest_listed_age(arts, now=now)
        assert newest == datetime(2026, 9, 24, tzinfo=timezone.utc) and age == 1

    def test_a_listing_with_no_dates_is_not_stale(self):
        """SYS-32's lastmod-only shape: absent dates must not be read as old."""
        newest, age = cc.newest_listed_age([{"timestamp": None}, {}])
        assert newest is None and age is None
        assert cc.classify(150, 1, ["site"], listing_age_days=None) == cc.STATUS_OK

    def test_a_frozen_listing_is_stale_not_ok(self):
        """SUARA's regional sitemaps: 200, 150 links each, last updated 2022."""
        assert cc.classify(150, 1, ["site"], listing_age_days=1068) == cc.STATUS_STALE
        assert cc.classify(150, 1, ["site"], listing_age_days=3) == cc.STATUS_OK

    def test_stale_is_needs_attention_but_not_fatal(self):
        assert cc.STATUS_STALE in cc.NEEDS_ATTENTION
        assert cc.STATUS_STALE not in cc.UNHEALTHY

    def test_a_broken_extractor_outranks_staleness(self):
        """A dead selector is the more urgent finding."""
        assert cc.classify(150, 0, [], listing_age_days=999) == cc.STATUS_PARTIAL
        assert cc.classify(150, 1, ["trafilatura"], listing_age_days=999) == cc.STATUS_FALLBACK
