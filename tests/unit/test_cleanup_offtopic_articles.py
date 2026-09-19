"""SYS-31: scripts/cleanup_offtopic_articles.py deletes the articles/chunks
already saved under a category is_offtopic_category() now rejects, skipping
anything entity_mentions already references (hard FK, no ON DELETE CASCADE)."""
import importlib.util
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "cleanup_offtopic_articles.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("cleanup_offtopic_articles", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["cleanup_offtopic_articles.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


cleanup = _load_module()


def _row(sitemap_id, category, sources="TEST", referenced=False):
    return SimpleNamespace(sitemap_id=sitemap_id, category=category, sources=sources, referenced=referenced)


def _backup_row(**data):
    row = SimpleNamespace(**data)
    row._mapping = data
    return row


class TestFindOfftopicSitemapIds:
    def test_offtopic_category_is_a_target(self):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [_row(1, "hiburan")]
        targets, skipped, by_category = cleanup.find_offtopic_sitemap_ids(session)
        assert targets == [1]
        assert skipped == []
        assert by_category == {("TEST", "hiburan"): 1}

    def test_finance_category_is_not_a_target(self):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [_row(1, "ekonomi")]
        targets, skipped, by_category = cleanup.find_offtopic_sitemap_ids(session)
        assert targets == []
        assert by_category == {}

    def test_referenced_row_is_skipped_not_deleted(self):
        """A hard FK from entity_mentions with no ON DELETE CASCADE means
        deleting underneath it would violate a constraint -- must be excluded
        from targets, not attempted and caught."""
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [_row(1, "hiburan", referenced=True)]
        targets, skipped, by_category = cleanup.find_offtopic_sitemap_ids(session)
        assert targets == []
        assert skipped == [1]
        assert by_category == {}

    def test_mixed_batch_counts_correctly_by_source_and_category(self):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [
            _row(1, "hiburan", sources="SINDONEWS"),
            _row(2, "hiburan", sources="SINDONEWS"),
            _row(3, "lifestyle", sources="TVONENEWS"),
            _row(4, "ekonomi", sources="KOMPAS"),
            _row(5, "hiburan", sources="SINDONEWS", referenced=True),
        ]
        targets, skipped, by_category = cleanup.find_offtopic_sitemap_ids(session)
        assert sorted(targets) == [1, 2, 3]
        assert skipped == [5]
        assert by_category == {("SINDONEWS", "hiburan"): 2, ("TVONENEWS", "lifestyle"): 1}


class TestFaissIdsForSitemaps:
    def test_matches_only_wanted_sitemap_ids(self):
        vs = MagicMock()
        vs.docstore._dict = {
            "uuid-1": SimpleNamespace(metadata={"sitemap_id": 1}),
            "uuid-2": SimpleNamespace(metadata={"sitemap_id": 2}),
            "uuid-3": SimpleNamespace(metadata={"sitemap_id": 3}),
        }
        assert sorted(cleanup._faiss_ids_for_sitemaps(vs, [1, 3])) == ["uuid-1", "uuid-3"]

    def test_docs_missing_sitemap_id_metadata_are_ignored(self):
        vs = MagicMock()
        vs.docstore._dict = {"uuid-1": SimpleNamespace(metadata={"other": "x"})}
        assert cleanup._faiss_ids_for_sitemaps(vs, [1]) == []


class TestMainDryRun:
    def test_dry_run_makes_no_backup_and_no_sql_delete(self, tmp_path):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [_row(1, "hiburan")]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        with patch.object(cleanup, "SQLAlchemyClient", return_value=client), \
             patch.object(cleanup, "BACKUP_DIR", str(tmp_path)), \
             patch.object(sys, "argv", ["cleanup_offtopic_articles.py", "--dry-run"]):
            rc = cleanup.main(["--dry-run"])

        assert rc == 0
        assert session.execute.call_count == 1  # the SELECT only
        assert list(tmp_path.iterdir()) == []

    def test_nothing_to_delete_is_a_clean_noop(self, tmp_path):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [_row(1, "ekonomi")]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        with patch.object(cleanup, "SQLAlchemyClient", return_value=client), \
             patch.object(cleanup, "BACKUP_DIR", str(tmp_path)):
            rc = cleanup.main([])

        assert rc == 0
        assert list(tmp_path.iterdir()) == []


class TestMainRealRun:
    def test_deletes_chunks_articles_marks_rejected_and_removes_faiss_vectors(self, tmp_path):
        session = MagicMock()
        session.execute.return_value.fetchall.side_effect = [
            [_row(1, "hiburan", sources="SINDONEWS")],  # candidates SELECT
            [_backup_row(articles_id=10, sitemap_id=1)],  # backup: articles
            [_backup_row(chunk_id=100, sitemap_id=1)],     # backup: chunks
        ]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        faiss_instance = MagicMock()
        faiss_instance.vs_l1.docstore._dict = {"uuid-l1": SimpleNamespace(metadata={"sitemap_id": 1})}
        faiss_instance.vs_l2.docstore._dict = {}

        with patch.object(cleanup, "SQLAlchemyClient", return_value=client), \
             patch.object(cleanup, "BACKUP_DIR", str(tmp_path)), \
             patch(
                 "newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source.ChunkFAISSDatasource",
                 return_value=faiss_instance,
             ):
            rc = cleanup.main([])

        assert rc == 0
        # backup written before any delete
        backup_files = list(tmp_path.iterdir())
        assert len(backup_files) == 1

        # SQL: SELECT candidates, 2 backup SELECTs, then DELETE chunks, DELETE
        # articles, UPDATE sitemaps -- all inside client.get_session() calls.
        executed_sql = [str(c.args[0]) for c in session.execute.call_args_list]
        assert any("DELETE FROM chunks" in s for s in executed_sql)
        assert any("DELETE FROM articles" in s for s in executed_sql)
        assert any("UPDATE sitemaps SET crawl_status" in s for s in executed_sql)
        session.commit.assert_called_once()

        faiss_instance.vs_l1.delete.assert_called_once_with(["uuid-l1"])
        faiss_instance._atomic_save_local.assert_called_once()
        faiss_instance.vs_l2.delete.assert_not_called()

    def test_referenced_rows_are_never_sent_to_faiss_or_sql_delete(self, tmp_path):
        session = MagicMock()
        session.execute.return_value.fetchall.side_effect = [
            [_row(1, "hiburan", referenced=True)],  # candidates: only a referenced row
        ]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        with patch.object(cleanup, "SQLAlchemyClient", return_value=client), \
             patch.object(cleanup, "BACKUP_DIR", str(tmp_path)):
            rc = cleanup.main([])

        assert rc == 0
        assert session.execute.call_count == 1  # candidates SELECT only, nothing else
        assert list(tmp_path.iterdir()) == []


class TestFaissOnlyResume:
    def test_faiss_only_skips_the_database_entirely(self):
        with patch.object(cleanup, "delete_faiss_vectors", return_value={"NEWS_L1": 2, "NEWS_L2": 1}) as mock_del, \
             patch.object(cleanup, "SQLAlchemyClient") as mock_client:
            rc = cleanup.main(["--faiss-only", "1,2,3"])

        assert rc == 0
        mock_del.assert_called_once_with([1, 2, 3])
        mock_client.assert_not_called()
