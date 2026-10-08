"""Which stored rows the SYS-105 and SRC-60 repairs touch (their pure selection; the writes are
covered live in tests/integration/test_rechunk_stale_chunks_live.py and
test_settle_out_of_scope_links_live.py)."""
import importlib.util
import os
import sys
from types import SimpleNamespace

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")


def _load(name):
    sys.path.insert(0, SCRIPTS)
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rechunk = _load("rechunk_stale_chunks")
settle = _load("settle_out_of_scope_links")


def _words(prefix, n):
    return " ".join(f"{prefix}{i}" for i in range(n))


class TestRechunkTargets:
    """SYS-105 (#275): the articles whose stored L2 layout the chunker no longer gives."""

    def _chunker(self):
        from newscrawler.core.chunker import HierarchicalChunker
        return HierarchicalChunker(min_tokens=80, max_tokens=450, overlap_tokens=50)

    def test_a_trailing_sign_off_layout_is_a_target(self):
        body = "\n\n".join([_words("a", 120), _words("b", 100), "(jon)"])
        targets = rechunk.select_targets([(1, "DETIK", body, [120, 100, 1])], self._chunker())
        assert targets == {"DETIK": [(1, [120, 100, 1], [120, 101])]}

    def test_a_layout_the_chunker_still_gives_is_not(self):
        body = "\n\n".join([_words("a", 120), _words("b", 100)])
        assert rechunk.select_targets([(1, "DETIK", body, [120, 100])], self._chunker()) == {}

    def test_an_empty_body_is_not_rechunked(self):
        assert rechunk.select_targets([(1, "DETIK", "", [3])], self._chunker()) == {}

    def test_the_report_counts_fragments_before_and_after(self):
        out = rechunk.report({"DETIK": [(1, [120, 100, 1], [120, 101])]}, {"DETIK": 4})
        assert "DETIK                    1           4          1 -> 0" in out


class TestSettleTargets:
    """SRC-60 (#279): stored sitemaps the crawler calls out of scope, unless already settled."""

    @staticmethod
    def _row(sid, link, status="saved", article=True, chunks=True):
        return SimpleNamespace(sitemap_id=sid, link=link, crawl_status=status, has_article=article, has_chunks=chunks,
                               headline="h", has_disclaimer=False)

    def test_reader_posts_in_any_unsettled_state_are_targets(self):
        from newscrawler.infrastructure.datasource.scrapers.kumparan.kumparan_crawler import KumparanCrawler
        rows = [self._row(1, "https://kumparan.com/kumparannews/a"),
                self._row(2, "https://kumparan.com/tyasafira031/b"),
                self._row(3, "https://kumparan.com/halizasalda24/c", status="pending", article=False, chunks=False),
                self._row(4, "https://kumparan.com/rudi-yahya/d", status="rejected_filter", article=False, chunks=False),
                self._row(5, "https://kumparan.com/TDA/e", status="rejected_filter", article=False, chunks=True)]
        targets = settle.select_targets(rows, KumparanCrawler().out_of_scope_reason)
        assert [r.sitemap_id for r, _ in targets] == [2, 3, 5], "a settled row without chunks is left alone"
