"""SYS-54 (#185): the crawl settles sitemaps as terminal (rejected_filter, or a
fetch failure at the cap) and must remove any vectors and chunk rows they
already had. 5,292 queued VIVA sitemaps carry vectors from the June article-gap
era; before this, each one the crawl rejected became a terminal orphan and the
run's own store check said STORE DIVERGENT.

Service tests use a MagicMock repository (what is discarded, and when). The
repository tests use real FAISS indexes (FakeEmbeddings) in tmp_path and a fake
chunks table, and judge the end state with check_store_consistency's own
arithmetic.
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
    svc.data_flow_repo.discard_terminal_embeddings.side_effect = lambda ids: events.append(("discard", ids)) or 0
    svc.events = events
    return svc


def _crawl(service, queue, extracted, failures, verdicts):
    service.data_flow_repo.load_sitemap_data.return_value = queue
    by_id = {a.sitemap_id: a for a in extracted}

    def batch(news, website_name):
        mine = [by_id[s.sitemap_id] for s in news if s.sitemap_id in by_id]
        return NewsDetailsBatch(mine, failures={s.sitemap_id: failures[s.sitemap_id]
                                                for s in news if s.sitemap_id in failures})
    service.crawler_dict["TEST_SITE"].batch_crawling_details.side_effect = batch
    service.semantic_filter.classify.side_effect = lambda text, category=None, source=None: verdicts[text]
    service.crawl_newsdetails("TEST_SITE")


def _keep(flag):
    return FilterDecision(is_important=flag, gate="score", score_passed=flag)


class TestTheServiceDiscardsWhatItSettled:
    def test_rejected_pre_denied_and_failed_sitemaps_are_candidates_inside_the_block(self, service):
        queue = [_sitemap(1), _sitemap(2), _sitemap(3), _sitemap(4), _sitemap(5, "olahraga")]
        extracted = [_article(1, ["gosip selebriti"]), _article(2, ["berita ekonomi"]), _article(4, [])]
        with patch("newscrawler.domain.services.crawler_service_impl.build_check_text", lambda t, b: b):
            _crawl(service, queue, extracted, failures={3: "HTTP 404"},
                   verdicts={"gosip selebriti": _keep(False), "berita ekonomi": _keep(True)})
        discards = [e for e in service.events if isinstance(e, tuple)]
        assert discards == [("discard", {1, 3, 5})], "rejected 1, failed 3, pre-denied 5; not saved 2 or empty 4"
        assert service.events.index(discards[0]) < service.events.index("block flushed"), \
            "discarded after the flush: the deletions would never reach disk"

    def test_a_failed_discard_is_logged_and_the_source_still_completes(self, service, caplog):
        service.data_flow_repo.discard_terminal_embeddings.side_effect = OSError("db gone")
        with patch("newscrawler.domain.services.crawler_service_impl.build_check_text", lambda t, b: b):
            with caplog.at_level(logging.ERROR):
                _crawl(service, [_sitemap(1)], [_article(1, ["gosip"])], failures={},
                       verdicts={"gosip": _keep(False)})
        assert any("SYS-54" in r.message for r in caplog.records if r.levelno == logging.ERROR)
        service.data_flow_repo.log_crawl_complete.assert_called_once()


# ── the repository: vectors and rows, in the repair's order ──────────────────

class ChunkTable(FakeChunkTable):
    def delete_for_sitemaps(self, sitemap_ids):
        doomed = [k for k in self.rows if k[0] in set(sitemap_ids)]
        for k in doomed:
            del self.rows[k]
        return len(doomed)


class Sitemaps:
    """terminal_without_article over a fixed set of terminal sitemap_ids."""

    def __init__(self, terminal):
        self.terminal = set(terminal)

    def terminal_without_article(self, sitemap_ids):
        return self.terminal & set(sitemap_ids)


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
    repo.news_data_source = Sitemaps(terminal)
    return repo


class TestTheRepositoryRemovesVectorsThenRows:
    def test_a_rejected_sitemap_with_vectors_ends_with_neither_and_the_store_check_stays_zero(self, paths):
        """The ticket's Done-when: rejected by the filter, with existing chunks
        and vectors. Sitemap 8 is still queued and keeps everything."""
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7, 8])
        repo = _repo_over(paths, table, terminal={7})
        with repo.deferred_embeddings("VIVA"):
            assert repo.discard_terminal_embeddings({7, 8}) == 3
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
        repo.discard_terminal_embeddings({7})
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
                    repo.discard_terminal_embeddings({7})
        assert len(table.rows) == 3 and 7 in _sids_on_disk(paths[0])

    def test_outside_a_block_it_saves_and_deletes_at_once(self, paths):
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        repo = _repo_over(paths, table, terminal={7})
        repo.discard_terminal_embeddings({7})
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
            repo.discard_terminal_embeddings({7})
        assert 7 not in _sids_on_disk(paths[0])

    def test_nothing_terminal_touches_nothing(self, paths):
        table = ChunkTable()
        _with_existing_vectors(paths, table, [7])
        repo = _repo_over(paths, table, terminal=set())
        with patch.object(ChunkFAISSDatasource, "_atomic_save_local") as save:
            with repo.deferred_embeddings("VIVA"):
                assert repo.discard_terminal_embeddings({7}) == 0
        save.assert_not_called()
        assert len(table.rows) == 3
