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

import pytest

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


def _row(chunk_id, sitemap_id=1, chunk_level=1, chunk_index=0, embedding_id="e", referenced=False,
         text_content="same text"):
    data = dict(chunk_id=chunk_id, sitemap_id=sitemap_id, chunk_level=chunk_level,
                chunk_index=chunk_index, embedding_id=embedding_id, referenced=referenced,
                text_content=text_content, fts_vector="'same':1 'text':2", article_id=None, chunk_total=1, is_first_chunk=True,
                is_last_chunk=True, token_count=2, chunk_status="embedded", created_at="2026-09-17 15:57:14")
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
        faiss_instance.vs_l1.docstore._dict = {"uuid-loser": object(), "uuid-keeper": object()}

        with patch.object(dedupe, "SQLAlchemyClient", return_value=client), \
             patch.object(dedupe, "ChunkFAISSDatasource", return_value=faiss_instance), \
             patch.object(dedupe, "BACKUP_DIR", str(tmp_path)), \
             patch.object(sys, "argv", ["dedupe_chunks.py"]):
            rc = dedupe.main()

        assert rc == 0
        faiss_instance.vs_l1.delete.assert_called_once_with(["uuid-loser"])
        # DBT-10: goes through the crash-safe swap now, not vs_l1.save_local directly.
        faiss_instance._atomic_save_local.assert_called_once_with(faiss_instance.vs_l1, dedupe.VECTOR_DB_NAME_L1)
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


def _run(rows, tmp_path, argv=(), faiss_instance=None, order=None):
    session = MagicMock()
    results = iter([MagicMock(fetchall=MagicMock(return_value=rows)), MagicMock()])

    def execute(stmt, *args):
        if order is not None and stmt is dedupe._DELETE_SQL:
            order.append("sql")
        return next(results)
    session.execute.side_effect = execute
    client = MagicMock()
    client.get_session.return_value.__enter__.return_value = session
    faiss_instance = faiss_instance or MagicMock()
    with patch.object(dedupe, "SQLAlchemyClient", return_value=client), \
         patch.object(dedupe, "ChunkFAISSDatasource", return_value=faiss_instance) as ctor, \
         patch.object(dedupe, "BACKUP_DIR", str(tmp_path)), \
         patch.object(sys, "argv", ["dedupe_chunks.py", *argv]):
        rc = dedupe.main()
    return rc, session, faiss_instance, ctor


def _store(docs, fail=False, order=None):
    """A vector store double that behaves like LangChain's FAISS.delete: it
    raises on an id it does not hold."""
    vs = MagicMock()
    vs.docstore._dict = docs

    def delete(ids):
        if fail:
            raise RuntimeError("killed")
        missing = [i for i in ids if i not in docs]
        if missing:
            raise ValueError(f"Some specified ids do not exist in the current store: {missing}")
        for i in ids:
            docs.pop(i)
        if order is not None:
            order.append("faiss")
    vs.delete.side_effect = delete
    return vs


class TestDbt21:
    """DBT-21 (#72): a restorable backup, a refusal on divergent text, and a
    re-run that converges after an interrupted one."""

    def test_the_backup_holds_every_selected_column(self, tmp_path):
        faiss_instance = MagicMock(vs_l1=_store({"uuid-loser": object()}))
        rows = [_row(2, embedding_id="uuid-loser"), _row(1, embedding_id="uuid-keeper")]

        rc, _, _, _ = _run(rows, tmp_path, faiss_instance=faiss_instance)

        assert rc == 0
        (backup,) = list(tmp_path.iterdir())
        entry = json.loads(backup.read_text())[0]
        # Every column the SELECT returned (c.*: see the live test), minus the
        # computed `referenced` flag.
        assert entry == {k: v for k, v in rows[0]._mapping.items() if k not in ("referenced", "fts_vector")}
        assert "fts_vector" not in entry
        assert entry["text_content"] == "same text"

    def test_divergent_text_is_refused_without_the_flag(self, tmp_path):
        rows = [_row(2, text_content="extraction B"), _row(1, text_content="extraction A")]

        rc, session, _, ctor = _run(rows, tmp_path)

        assert rc == 1
        ctor.assert_not_called()
        assert session.execute.call_count == 1
        assert list(tmp_path.iterdir()) == []

    def test_divergent_text_is_deleted_with_the_flag_and_kept_in_the_backup(self, tmp_path):
        faiss_instance = MagicMock(vs_l1=_store({"e2": object()}))
        rows = [_row(2, embedding_id="e2", text_content="extraction B"),
                _row(1, embedding_id="e1", text_content="extraction A")]

        rc, session, _, _ = _run(rows, tmp_path, argv=["--allow-divergent"], faiss_instance=faiss_instance)

        assert rc == 0
        assert session.execute.call_args_list[1].args[1] == {"ids": [2]}
        (backup,) = list(tmp_path.iterdir())
        assert json.loads(backup.read_text())[0]["text_content"] == "extraction B"

    def test_dry_run_reports_divergent_groups(self, tmp_path, caplog):
        rows = [_row(2, text_content="B"), _row(1, text_content="A")]
        with caplog.at_level("WARNING"):
            rc, _, _, ctor = _run(rows, tmp_path, argv=["--dry-run"])
        assert rc == 0
        ctor.assert_not_called()
        assert any("DIFFERENT text_content" in r.getMessage() for r in caplog.records)

    def test_vectors_go_before_rows(self, tmp_path):
        order = []
        faiss_instance = MagicMock(vs_l1=_store({"uuid-loser": object()}, order=order))
        rc, _, _, _ = _run([_row(2, embedding_id="uuid-loser"), _row(1)], tmp_path,
                           faiss_instance=faiss_instance, order=order)
        assert rc == 0
        assert order == ["faiss", "sql"]

    def test_a_rerun_after_an_interrupted_run_converges(self, tmp_path):
        """First run: L1 saved, then the L2 delete dies -> rows untouched.
        Re-run: the same losers; the L1 id already gone is skipped rather than
        raising, L2 and the rows are deleted. Same end state as one clean run."""
        rows = [_row(2, chunk_level=1, embedding_id="l1-loser"), _row(1, chunk_level=1, embedding_id="l1-keeper"),
                _row(4, chunk_level=2, embedding_id="l2-loser"), _row(3, chunk_level=2, embedding_id="l2-keeper")]
        l1 = {"l1-loser": object(), "l1-keeper": object()}
        l2 = {"l2-loser": object(), "l2-keeper": object()}

        with pytest.raises(RuntimeError):
            _run(rows, tmp_path, faiss_instance=MagicMock(vs_l1=_store(l1), vs_l2=_store(l2, fail=True)))
        assert "l1-loser" not in l1 and "l2-loser" in l2

        rc, session, _, _ = _run(rows, tmp_path, faiss_instance=MagicMock(vs_l1=_store(l1), vs_l2=_store(l2)))

        assert rc == 0
        assert set(l1) == {"l1-keeper"} and set(l2) == {"l2-keeper"}
        assert session.execute.call_args_list[1].args[1] == {"ids": [2, 4]}
