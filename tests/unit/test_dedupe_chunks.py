"""
DBT-09: scripts/dedupe_chunks.py must delete the losing row of each duplicate
`chunks` group without ever deleting a row entity_mentions.chunk_id references
(a hard FK), and must abort instead of guessing when a group has two
referenced rows.
"""
import importlib.util
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "dedupe_chunks.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("dedupe_chunks", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["dedupe_chunks.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


dedupe = _load_module()


def _row(chunk_id, sitemap_id=1, chunk_level=1, chunk_index=0, embedding_id="e", referenced=False):
    data = dict(chunk_id=chunk_id, sitemap_id=sitemap_id, chunk_level=chunk_level,
                chunk_index=chunk_index, embedding_id=embedding_id, referenced=referenced)
    row = SimpleNamespace(**data)
    row._mapping = data
    return row


class TestPickLoserIds:
    def test_no_reference_keeps_lowest_chunk_id(self):
        losers, conflict = dedupe._pick_loser_ids([_row(35353), _row(34293)])
        assert not conflict
        assert {r.chunk_id for r in losers} == {35353}

    def test_referenced_row_is_always_kept_even_if_higher_id(self):
        losers, conflict = dedupe._pick_loser_ids([_row(34293), _row(35353, referenced=True)])
        assert not conflict
        assert {r.chunk_id for r in losers} == {34293}

    def test_two_referenced_rows_is_an_unresolvable_conflict(self):
        losers, conflict = dedupe._pick_loser_ids([_row(1, referenced=True), _row(2, referenced=True)])
        assert conflict
        assert losers == []


class TestMainDryRun:
    def test_dry_run_never_touches_faiss_backup_or_db(self, tmp_path):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [
            _row(35353, sitemap_id=1), _row(34293, sitemap_id=1),
        ]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        with patch.object(dedupe, "SQLAlchemyClient", return_value=client), \
             patch.object(dedupe, "ChunkFAISSDatasource") as mock_faiss, \
             patch.object(dedupe, "BACKUP_DIR", str(tmp_path)), \
             patch.object(sys, "argv", ["dedupe_chunks.py", "--dry-run"]):
            rc = dedupe.main()

        assert rc == 0
        mock_faiss.assert_not_called()
        assert session.execute.call_count == 1  # the SELECT only, no DELETE
        assert list(tmp_path.iterdir()) == []


class TestMainRealRun:
    def test_deletes_loser_row_and_its_faiss_vector(self, tmp_path):
        rows = [_row(35353, sitemap_id=1, chunk_level=1, embedding_id="uuid-loser"),
                _row(34293, sitemap_id=1, chunk_level=1, embedding_id="uuid-keeper")]
        session = MagicMock()
        session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=rows)),  # SELECT
            MagicMock(),  # DELETE
        ]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        faiss_instance = MagicMock()

        with patch.object(dedupe, "SQLAlchemyClient", return_value=client), \
             patch.object(dedupe, "ChunkFAISSDatasource", return_value=faiss_instance), \
             patch.object(dedupe, "BACKUP_DIR", str(tmp_path)), \
             patch.object(sys, "argv", ["dedupe_chunks.py"]):
            rc = dedupe.main()

        assert rc == 0
        faiss_instance.vs_l1.delete.assert_called_once_with(["uuid-loser"])
        faiss_instance.vs_l1.save_local.assert_called_once()
        faiss_instance.vs_l2.delete.assert_not_called()

        delete_call = session.execute.call_args_list[1]
        assert delete_call.args[1] == {"ids": [35353]}

        backup_files = list(tmp_path.iterdir())
        assert len(backup_files) == 1
        backed_up = json.loads(backup_files[0].read_text())
        assert {r["chunk_id"] for r in backed_up} == {35353}

    def test_conflict_aborts_without_deleting_anything(self, tmp_path):
        rows = [_row(1, sitemap_id=1, referenced=True), _row(2, sitemap_id=1, referenced=True)]
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = rows
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        with patch.object(dedupe, "SQLAlchemyClient", return_value=client), \
             patch.object(dedupe, "ChunkFAISSDatasource") as mock_faiss, \
             patch.object(dedupe, "BACKUP_DIR", str(tmp_path)), \
             patch.object(sys, "argv", ["dedupe_chunks.py"]):
            rc = dedupe.main()

        assert rc == 1
        mock_faiss.assert_not_called()
        assert session.execute.call_count == 1  # no DELETE issued
        assert list(tmp_path.iterdir()) == []
