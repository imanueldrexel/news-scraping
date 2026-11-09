"""
DBT-17: scripts/backfill_pending_embeddings.py repairs `chunks` rows stuck at
embedding_id IS NULL by embedding their existing text_content and UPDATE-ing
the row in place -- it must never INSERT a new row (that would duplicate the
chunk), and a --dry-run must never touch FAISS, the backup file, or the DB.
"""
import importlib.util
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "backfill_pending_embeddings.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("backfill_pending_embeddings", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["backfill_pending_embeddings.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


backfill = _load_module()


def _row(chunk_id, sitemap_id=1, chunk_level=2, chunk_index=0, sources="WARTAEKONOMI"):
    data = dict(
        chunk_id=chunk_id, sitemap_id=sitemap_id, chunk_level=chunk_level, chunk_index=chunk_index,
        chunk_total=1, is_first_chunk=True, is_last_chunk=True, text_content="text", token_count=10,
        headline="Headline", sources=sources, category="finansial", posted_at=20260601,
    )
    row = SimpleNamespace(**data)
    row._mapping = data
    return row


class TestRowToDto:
    def test_maps_row_fields_and_preserves_chunk_id(self):
        dto = backfill._row_to_dto(_row(chunk_id=81, sitemap_id=7008, chunk_level=1))

        assert dto.chunk_id == 81
        assert dto.sitemap_id == 7008
        assert dto.chunk_level == 1
        assert dto.title == "Headline"
        assert dto.source == "WARTAEKONOMI"
        assert dto.embedding_id is None  # not yet embedded


class TestMainDryRun:
    def test_dry_run_never_touches_faiss_backup_or_db(self, tmp_path):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [_row(81), _row(82)]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        with patch.object(backfill, "SQLAlchemyClient", return_value=client), \
             patch.object(backfill, "ChunkFAISSDatasource") as mock_faiss, \
             patch.object(backfill, "BACKUP_DIR", str(tmp_path)), \
             patch.object(sys, "argv", ["backfill_pending_embeddings.py", "--dry-run"]):
            backfill.main()

        mock_faiss.assert_not_called()
        assert session.execute.call_count == 1  # the SELECT only, no UPDATE
        assert list(tmp_path.iterdir()) == []  # no backup written


class TestMainRealRun:
    def test_updates_existing_rows_in_place_and_writes_backup(self, tmp_path):
        rows = [_row(chunk_id=81, sitemap_id=7008, chunk_level=1), _row(chunk_id=87, sitemap_id=7008, chunk_level=2)]
        session = MagicMock()
        session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=rows)),  # SELECT
            MagicMock(),  # UPDATE
        ]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        embedded = [
            SimpleNamespace(chunk_id=81, embedding_id="uuid-l1", chunk_status="embedded"),
            SimpleNamespace(chunk_id=87, embedding_id="uuid-l2", chunk_status="embedded"),
        ]
        faiss_instance = MagicMock()
        faiss_instance.save.return_value = embedded

        with patch.object(backfill, "SQLAlchemyClient", return_value=client), \
             patch.object(backfill, "ChunkFAISSDatasource", return_value=faiss_instance), \
             patch.object(backfill, "BACKUP_DIR", str(tmp_path)), \
             patch.object(sys, "argv", ["backfill_pending_embeddings.py"]):
            backfill.main()

        # Backup written before the update, with the original (pre-repair) rows.
        backup_files = list(tmp_path.iterdir())
        assert len(backup_files) == 1
        backed_up = json.loads(backup_files[0].read_text())
        assert {r["chunk_id"] for r in backed_up} == {81, 87}

        # Second execute call is the UPDATE, keyed by chunk_id -- never an INSERT.
        update_call = session.execute.call_args_list[1]
        update_params = update_call.args[1]
        assert {p["chunk_id"]: p["embedding_id"] for p in update_params} == {81: "uuid-l1", 87: "uuid-l2"}
        assert all(p["chunk_status"] == "embedded" for p in update_params)
        assert "UPDATE chunks" in str(update_call.args[0])

    def test_chunk_missing_embedding_id_after_save_is_not_updated(self, tmp_path):
        """A defensive guard: if ChunkFAISSDatasource ever returns a chunk without an
        embedding_id, it must be skipped, never written with a NULL update."""
        rows = [_row(chunk_id=81)]
        session = MagicMock()
        session.execute.side_effect = [MagicMock(fetchall=MagicMock(return_value=rows)), MagicMock()]
        client = MagicMock()
        client.get_session.return_value.__enter__.return_value = session

        faiss_instance = MagicMock()
        faiss_instance.save.return_value = [SimpleNamespace(chunk_id=81, embedding_id=None, chunk_status="pending_embedding")]

        with patch.object(backfill, "SQLAlchemyClient", return_value=client), \
             patch.object(backfill, "ChunkFAISSDatasource", return_value=faiss_instance), \
             patch.object(backfill, "BACKUP_DIR", str(tmp_path)), \
             patch.object(sys, "argv", ["backfill_pending_embeddings.py"]):
            backfill.main()

        update_call = session.execute.call_args_list[1]
        assert update_call.args[1] == []
