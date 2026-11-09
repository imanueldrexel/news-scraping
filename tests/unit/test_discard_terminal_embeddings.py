"""SYS-54 (#185): the crawl settles sitemaps as terminal (rejected_filter, or a
fetch failure at the cap) and must remove any vectors and chunk rows they
already had. 5,292 queued VIVA sitemaps carry vectors from the June article-gap
era; before this, each one the crawl rejected became a terminal orphan and the
run's own store check said STORE DIVERGENT.

SYS-57 (#191): the sitemaps to clean up come from the store (this source's
terminal sitemaps that still have chunk rows), not from one run's settle
events, so a source killed before its end is cleaned up by its next run.

Service tests use a MagicMock repository (what is discarded, and when). The
repository tests use real FAISS indexes (FakeEmbeddings) in tmp_path and a fake
chunks table, and judge the end state with check_store_consistency's own
arithmetic. TestAKilledSourceIsCleanedUpByItsNextRun runs the real service over
the real repository.
"""
import importlib.util
import logging
import os
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from langchain_community.vectorstores import FAISS

from newscrawler.core.importance_filter import FilterDecision
from newscrawler.infrastructure.datasource.scrapers.crawler import NewsDetailsBatch
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource

from tests.unit.test_deferred_embeddings import EMB, FakeChunkTable, _chunk, _faiss, _repo, paths  # noqa: F401

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _csc():
    spec = importlib.util.spec_from_file_location(
        "check_store_consistency", os.path.join(REPO, "scripts", "check_store_consistency.py"))
    mod = importlib.util.module_from_spec(spec)
    saved, sys.argv = sys.argv, ["check_store_consistency.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


csc = _csc()


# ── the service: what it discards, and inside which block ────────────────────

def _sitemap(sid, category="news"):
    return SitemapDTO(sitemap_id=sid, headline="h%d" % sid, link="http://t/%d" % sid,
                      sources="TEST_SITE", category=category)


def _article(sid, text):
    return NewsDetailsDTO(sitemap_id=sid, extracted_text=text, meta_data={"title": "t"}, reporter=[])


@pytest.fixture
def service():
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.crawler_dict = {"TEST_SITE": MagicMock()}
    svc.data_flow_repo.get_saved_category_pairs.return_value = None
    svc.data_flow_repo.save_newsdetails_data.side_effect = lambda dtos: [d.sitemap_id for d in dtos]
    svc.data_flow_repo.save_chunk_data.side_effect = lambda chunks: sorted({c.sitemap_id for c in chunks})
    svc.data_flow_repo.discard_terminal_embeddings.return_value = 0
    events = []

    @contextmanager
    def deferred(website):
        events.append("block entered")
        yield svc.data_flow_repo
        events.append("block flushed")
    svc.data_flow_repo.deferred_embeddings.side_effect = deferred
    svc.data_flow_repo.discard_terminal_embeddings.side_effect = \
        lambda website: events.append(("discard", website)) or 0
    svc.data_flow_repo.increment_fetch_failures.side_effect = \
        lambda ids, error_msg=None: events.append(("fetch failures counted", tuple(sorted(ids))))
    svc.events = events
    return svc


def _crawl(service, queue, extracted, failures, verdicts):
    service.data_flow_repo.load_sitemap_data.return_value = queue
    by_id = {a.sitemap_id: a for a in extracted}

    def batch(news, website_name, throttle=None):
        mine = [by_id[s.sitemap_id] for s in news if s.sitemap_id in by_id]
        return NewsDetailsBatch(mine, failures={s.sitemap_id: failures[s.sitemap_id]
                                                for s in news if s.sitemap_id in failures})
    service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = batch
    service.semantic_filter.classify.side_effect = lambda text, category=None, source=None: verdicts[text]
    service.crawl_newsdetails("TEST_SITE")


def _keep(flag):
    return FilterDecision(is_important=flag, gate="score", score_passed=flag)


class TestTheServiceSweepsTheSource:
    def test_the_source_is_swept_when_its_block_opens_and_after_its_last_batch(self, service):
        queue = [_sitemap(1), _sitemap(2), _sitemap(3), _sitemap(4), _sitemap(5, "olahraga")]
        extracted = [_article(1, ["gosip selebriti"]), _article(2, ["berita ekonomi"]), _article(4, [])]
        with patch("newscrawler.domain.services.crawler_service_impl.build_check_text", lambda t, b: b):
            _crawl(service, queue, extracted, failures={3: "HTTP 404"},
                   verdicts={"gosip selebriti": _keep(False), "berita ekonomi": _keep(True)})
        assert service.events == [
            "block entered",
            ("discard", "TEST_SITE"),                 # SYS-57: what an earlier, killed run left
            ("fetch failures counted", (3,)),
            ("discard", "TEST_SITE"),                 # SYS-54: what this run settled, the cap included
            "block flushed",                          # both inside the block: the deletions reach disk
        ]

    def test_a_failed_discard_is_logged_and_the_source_still_completes(self, service, caplog):
        service.data_flow_repo.discard_terminal_embeddings.side_effect = OSError("db gone")
        with patch("newscrawler.domain.services.crawler_service_impl.build_check_text", lambda t, b: b):
            with caplog.at_level(logging.ERROR):
                _crawl(service, [_sitemap(1)], [_article(1, ["gosip"])], failures={},
                       verdicts={"gosip": _keep(False)})
        assert any("SYS-54" in r.message for r in caplog.records if r.levelno == logging.ERROR)
        service.data_flow_repo.log_crawl_complete.assert_called_once()

    def test_the_log_line_names_which_sweep_removed_vectors(self, service, caplog):
        """SYS-54 is closed on the end-of-run line; SYS-57's has its own."""
        service.data_flow_repo.discard_terminal_embeddings.side_effect = [4, 6]
        with patch("newscrawler.domain.services.crawler_service_impl.build_check_text", lambda t, b: b):
            with caplog.at_level(logging.INFO):
                _crawl(service, [_sitemap(1)], [_article(1, ["gosip"])], failures={},
                       verdicts={"gosip": _keep(False)})
        lines = [r.message for r in caplog.records if "removed" in r.message]
        assert lines == ["TEST_SITE: removed 4 vector(s) of sitemaps an earlier run settled terminal (SYS-57)",
                         "TEST_SITE: removed 6 vector(s) of sitemaps settled terminal this run (SYS-54)"]


# ── the repository: vectors and rows, in the repair's order ──────────────────

class ChunkTable(FakeChunkTable):
    def delete_for_sitemaps(self, sitemap_ids):
        doomed = [k for k in self.rows if k[0] in set(sitemap_ids)]
        for k in doomed:
            del self.rows[k]
        return len(doomed)


class Sitemaps:
    """terminal_with_chunks over a fixed set of terminal sitemap_ids: those of
    them that still have a row in the chunk table (the SQL's EXISTS chunks)."""

    def __init__(self, terminal, table):
        self.terminal, self.table = set(terminal), table

    def terminal_with_chunks(self, website):
        return {sid for sid in self.terminal if any(k[0] == sid for k in self.table.rows)}


def _with_existing_vectors(paths, table, sids):
    """The June state: vectors on disk and embedded chunk rows, no article."""
    with _repo(_faiss(paths), table).deferred_embeddings("VIVA") as repo:
        repo.save_chunk_data([c for sid in sids for c in (_chunk(sid, 1), _chunk(sid, 2, 0), _chunk(sid, 2, 1))])
    assert all(r["embedding_id"] for r in table.rows.values())


def _sids_on_disk(path):
    return csc._load_docstore_sitemap_ids(path)


def _store_check(paths, table, terminal, articles=frozenset()):
    rows = table.rows
    return csc.compute_divergence(
        _sids_on_disk(paths[0]), _sids_on_disk(paths[1]), set(articles),
        [k[0] for k in rows if k[1] == 1], [k[0] for k in rows if k[1] == 2],
        sum(1 for r in rows.values() if r["embedding_id"] is None), terminal_ids=terminal)


def _repo_over(paths, table, terminal):
    repo = _repo(_faiss(paths), table)
    repo.news_data_source = Sitemaps(terminal, table)
    return repo


class TestTheRepositoryRemovesVectorsThenRows:
    def test_a_rejected_sitemap_with_vectors_ends_with_neither_and_the_store_check_stays_zero(self, paths):
        """The ticket's Done-when: rejected by the filter, with existing chunks
        and vectors. Sitemap 8 is still queued and keeps everything."""
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7, 8])
        repo = _repo_over(paths, table, terminal={7})
        with repo.deferred_embeddings("VIVA"):
            assert repo.discard_terminal_embeddings("VIVA") == 3
        assert 7 not in _sids_on_disk(paths[0]) and 7 not in _sids_on_disk(paths[1])
        assert not [k for k in table.rows if k[0] == 7]
        assert 8 in _sids_on_disk(paths[0]) and len([k for k in table.rows if k[0] == 8]) == 3
        counts = _store_check(paths, table, terminal={7})
        assert csc.growing_checks(counts) == [], counts
        assert counts["l1_no_articles_queued"] == 1  # sitemap 8, which links up when crawled

    def test_before_the_fix_the_same_run_left_a_terminal_orphan(self, paths):
        """What the store check saw when nothing removed the vectors."""
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        counts = _store_check(paths, table, terminal={7})
        assert csc.growing_checks(counts) == ["l1_no_articles_terminal", "l2_no_articles_terminal"]

    def test_rows_outlive_their_vectors_only_after_the_flush(self, paths):
        """A kill inside the block (no flush) leaves vectors AND rows: the
        repair's state. Deleting rows first would leave vectors that no row
        points at and nothing on the crawl path would ever clean up."""
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        repo = _repo_over(paths, table, terminal={7})
        repo.chunk_faiss_datasource.begin_deferred()
        repo.discard_terminal_embeddings("VIVA")
        # ...killed: no end_deferred
        assert 7 in _sids_on_disk(paths[0]) and len(table.rows) == 3

    def test_a_refused_flush_deletes_no_rows(self, paths):
        """The flush can be refused (SYS-53) after the vectors left memory; the
        rows must stay with the vectors still on disk."""
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import StaleIndexError
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        repo = _repo_over(paths, table, terminal={7})
        with patch.object(ChunkFAISSDatasource, "_atomic_save_local", side_effect=StaleIndexError("x")):
            with pytest.raises(StaleIndexError):
                with repo.deferred_embeddings("VIVA"):
                    repo.discard_terminal_embeddings("VIVA")
        assert len(table.rows) == 3 and 7 in _sids_on_disk(paths[0])

    def test_outside_a_block_it_saves_and_deletes_at_once(self, paths):
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        repo = _repo_over(paths, table, terminal={7})
        repo.discard_terminal_embeddings("VIVA")
        assert 7 not in _sids_on_disk(paths[1]) and not table.rows

    def test_duplicate_vectors_of_one_key_all_go(self, paths):
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        ds = _faiss(paths)
        ds.vs_l1.add_texts(["dup"], metadatas=[{"sitemap_id": 7, "chunk_level": 1, "chunk_index": 0}])
        ChunkFAISSDatasource._atomic_save_local(ds.vs_l1, paths[0])
        assert _sids_on_disk(paths[0]).count(7) == 2
        repo = _repo_over(paths, table, terminal={7})
        with repo.deferred_embeddings("VIVA"):
            repo.discard_terminal_embeddings("VIVA")
        assert 7 not in _sids_on_disk(paths[0])

    def test_nothing_terminal_touches_nothing(self, paths):
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        repo = _repo_over(paths, table, terminal=set())
        with patch.object(ChunkFAISSDatasource, "_atomic_save_local") as save:
            with repo.deferred_embeddings("VIVA"):
                assert repo.discard_terminal_embeddings("VIVA") == 0
        save.assert_not_called()
        assert len(table.rows) == 3

    def test_rows_left_after_their_vectors_went_are_deleted_by_the_next_sweep(self, paths):
        """A kill between the flush (vectors gone from disk) and the row delete
        leaves rows pointing at nothing. The store still lists the sitemap as
        terminal with chunks, so the next sweep deletes the rows."""
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        repo = _repo_over(paths, table, terminal={7})
        with patch.object(type(repo), "_delete_discarded_chunk_rows", side_effect=SystemExit("killed")):
            with pytest.raises(SystemExit):
                with repo.deferred_embeddings("VIVA"):
                    repo.discard_terminal_embeddings("VIVA")
        assert 7 not in _sids_on_disk(paths[0]) and len(table.rows) == 3

        repo = _repo_over(paths, table, terminal={7})
        with repo.deferred_embeddings("VIVA"):
            assert repo.discard_terminal_embeddings("VIVA") == 0
        assert not table.rows
        assert csc.growing_checks(_store_check(paths, table, terminal={7})) == []


class TestAFailedFlushKeepsItsDiscards:
    """SYS-58 (#192): the worker keeps one repository for every source. A flush
    that fails used to forget which rows to delete while the deletions it
    carried were saved by the next source's flush (case 1), or half-saved
    (case 2): rows left pointing at vectors that are gone."""

    def test_a_failed_save_is_finished_by_the_next_block(self, paths):
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7, 8])
        repo = _repo_over(paths, table, terminal={7})
        with patch.object(ChunkFAISSDatasource, "_atomic_save_local", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                with repo.deferred_embeddings("VIVA"):
                    repo.discard_terminal_embeddings("VIVA")
        assert 7 in _sids_on_disk(paths[0]) and len(table.rows) == 6, "nothing reached disk, nothing deleted"

        repo.news_data_source = Sitemaps(set(), table)   # the next source has nothing of its own
        with repo.deferred_embeddings("KOMPAS"):
            repo.discard_terminal_embeddings("KOMPAS")
        assert 7 not in _sids_on_disk(paths[0]) and 7 not in _sids_on_disk(paths[1])
        assert sorted({k[0] for k in table.rows}) == [8]
        assert csc.growing_checks(_store_check(paths, table, terminal={7})) == []

    def test_a_level_refused_after_the_other_was_saved_is_finished_by_the_next_block(self, paths):
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import StaleIndexError
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        repo = _repo_over(paths, table, terminal={7})
        real_save = ChunkFAISSDatasource._atomic_save_local

        def l2_refused(vs, db_name, **kwargs):
            if db_name == paths[1]:
                raise StaleIndexError("another process saved NEWS_L2")
            return real_save(vs, db_name, **kwargs)

        with patch.object(ChunkFAISSDatasource, "_atomic_save_local", side_effect=l2_refused):
            with pytest.raises(StaleIndexError):
                with repo.deferred_embeddings("VIVA"):
                    repo.discard_terminal_embeddings("VIVA")
        assert 7 not in _sids_on_disk(paths[0]) and 7 in _sids_on_disk(paths[1]), "L1 saved, L2 reloaded"
        assert len(table.rows) == 3, "rows kept while L2 still holds the vectors"

        repo.news_data_source = Sitemaps(set(), table)
        with repo.deferred_embeddings("KOMPAS"):
            pass
        assert 7 not in _sids_on_disk(paths[1]) and not table.rows
        assert csc.growing_checks(_store_check(paths, table, terminal={7})) == []

    def test_rows_are_not_deleted_while_the_next_flush_fails_too(self, paths):
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        repo = _repo_over(paths, table, terminal={7})
        with patch.object(ChunkFAISSDatasource, "_atomic_save_local", side_effect=OSError("disk full")):
            for website in ("VIVA", "KOMPAS"):
                with pytest.raises(OSError):
                    with repo.deferred_embeddings(website):
                        repo.discard_terminal_embeddings(website)
        assert len(table.rows) == 3 and 7 in _sids_on_disk(paths[0])


# ── SYS-57: the real service over the real repository, killed mid-source ─────

class SitemapStore:
    """The sitemaps table as the service and the repository see it: status per
    sitemap_id, no articles (the June rows never got one)."""

    def __init__(self, queue, table):
        self.status = {s.sitemap_id: "pending" for s in queue}
        self.queue, self.table = list(queue), table

    def load(self, website, n_limit):
        return [s for s in self.queue if self.status[s.sitemap_id] == "pending"]

    def mark(self, ids, status):
        self.status.update({i: status for i in ids})

    def terminal_with_chunks(self, website):
        return {sid for sid, st in self.status.items()
                if st == "rejected_filter" and any(k[0] == sid for k in self.table.rows)}


class TestAKilledSourceIsCleanedUpByItsNextRun:
    """SYS-57's Done-when: batch 1 settles sitemap 7 (June vectors, chunk rows)
    as rejected_filter, batch 2 kills the worker, so the end-of-source sweep
    never runs. The next run of the source must still remove 7's vectors and
    rows, although 7 is terminal and never offered again."""

    def _service(self, repo, store):
        with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
            svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
        mock = svc.data_flow_repo
        mock.get_saved_category_pairs.return_value = None
        mock.load_sitemap_data.side_effect = store.load
        mock.mark_sitemaps_status.side_effect = store.mark
        mock.deferred_embeddings.side_effect = repo.deferred_embeddings
        mock.discard_terminal_embeddings.side_effect = repo.discard_terminal_embeddings
        svc.crawler_dict = {"VIVA": MagicMock()}
        svc.semantic_filter.classify.side_effect = lambda text, category=None, source=None: _keep(False)
        return svc

    def test_the_next_run_removes_the_vectors_and_rows_the_killed_run_settled(self, paths):
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        store = SitemapStore([_sitemap(7), _sitemap(8)], table)
        repo = _repo(_faiss(paths), table)
        repo.news_data_source = store
        svc = self._service(repo, store)

        def batch(news, website_name, throttle=None):
            if news[0].sitemap_id == 8:
                raise SystemExit("OPS-22 timeout kill")
            return NewsDetailsBatch([_article(7, ["gosip"])], failures={})
        svc.crawler_dict["VIVA"].batch_crawling_details.side_effect = batch

        with patch("newscrawler.domain.services.crawler_service_impl.build_check_text", lambda t, b: b):
            with pytest.raises(SystemExit):
                svc.crawl_newsdetails("VIVA")
            assert store.status[7] == "rejected_filter", "settled in SQL by batch 1"
            assert 7 in _sids_on_disk(paths[0]) and len(table.rows) == 3, "the killed run cleaned nothing up"

            repo = _repo(_faiss(paths), table)       # the respawned worker
            repo.news_data_source = store
            svc = self._service(repo, store)
            svc.crawler_dict["VIVA"].batch_crawling_details.side_effect = \
                lambda news, website_name, throttle=None: NewsDetailsBatch([], failures={})
            svc.crawl_newsdetails("VIVA")

        assert 7 not in _sids_on_disk(paths[0]) and 7 not in _sids_on_disk(paths[1])
        assert not table.rows
        assert csc.growing_checks(_store_check(paths, table, terminal={7})) == []
