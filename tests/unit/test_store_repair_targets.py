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

    def test_the_report_counts_rows_fragments_and_overlong_chunks(self):
        out = rechunk.report({"DETIK": [(1, [120, 100, 1], [80, 80, 41])]}, 80)
        assert out.splitlines()[1].split() == ["DETIK", "1", "3", "->", "3", "1", "->", "0", "2", "->", "0"]

    def test_an_article_stored_without_l2_rows_is_a_target(self):
        """SYS-109: the layout of an article a stopped run left without L2 is None."""
        body = _words("a", 60)
        assert rechunk.select_targets([(1, "DETIK", body, None)], self._chunker()) == {"DETIK": [(1, [], [60])]}

    def test_the_default_chunker_splits_what_fit_the_old_one(self):
        """SYS-109: under the defaults (80/20/40) a 200-word paragraph stored whole is a target."""
        from newscrawler.core.chunker import HierarchicalChunker
        targets = rechunk.select_targets([(1, "DETIK", _words("a", 200), [200])], HierarchicalChunker())
        assert targets["DETIK"][0][2] == [80, 80, 80]


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


class TestGroupedRechunk:
    """SYS-109: the corpus re-chunk embeds many articles per save_chunk_data call; a failed group is
    saved again article by article, so one bad article fails alone."""

    @staticmethod
    def _rows(n):
        return [SimpleNamespace(sitemap_id=i, extracted_text=_words(f"a{i}x", 30), writer=[], headline="h",
                                sources="DETIK", category="ekonomi", posted_at=20261008) for i in range(1, n + 1)]

    @staticmethod
    def _repo(bad=()):
        calls = []

        def save(chunks):
            ids = sorted({c.sitemap_id for c in chunks})
            calls.append(ids)
            if set(ids) & set(bad):
                raise RuntimeError("bad article")
        return SimpleNamespace(save_chunk_data=save), calls

    def test_articles_are_saved_in_groups(self):
        from newscrawler.core.chunker import HierarchicalChunker
        backfill = _load("backfill_orphan_chunks")
        repo, calls = self._repo()
        assert backfill.rechunk_articles(repo, HierarchicalChunker(), self._rows(5), group_size=3) == (5, 0, 0)
        assert calls == [[1, 2, 3], [4, 5]]

    def test_a_failed_group_is_retried_one_by_one(self):
        from newscrawler.core.chunker import HierarchicalChunker
        backfill = _load("backfill_orphan_chunks")
        repo, calls = self._repo(bad={2})
        assert backfill.rechunk_articles(repo, HierarchicalChunker(), self._rows(3), group_size=3) == (2, 0, 1)
        assert calls == [[1, 2, 3], [1], [2], [3]]

    def test_the_default_saves_each_article_alone(self):
        from newscrawler.core.chunker import HierarchicalChunker
        backfill = _load("backfill_orphan_chunks")
        repo, calls = self._repo()
        backfill.rechunk_articles(repo, HierarchicalChunker(), self._rows(2))
        assert calls == [[1], [2]]
