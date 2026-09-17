"""
OPS-09 (#63): scripts/reset_extraction_attempts.py resets
knowledge_extract_attempts / last_extract_error so articles retired by SYS-19's
attempt cap re-enter get_articles_pending_extraction's queue. Nothing else does
this -- retirement is otherwise permanent.
"""
import argparse
import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "reset_extraction_attempts.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("reset_extraction_attempts", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["reset_extraction_attempts.py"]  # guard against any import-time parsing
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


reset_mod = _load_module()


class TestBuildWhere:
    def test_all_retired_uses_the_configured_max_attempts(self):
        args = argparse.Namespace(all_retired=True, like=None, sitemap_ids=None)
        where, params = reset_mod._build_where(args)
        assert "knowledge_extract_attempts >= :max_attempts" in where
        assert params["max_attempts"] == reset_mod.KNOWLEDGE_EXTRACT_MAX_ATTEMPTS

    def test_like_filters_on_last_extract_error(self):
        args = argparse.Namespace(all_retired=False, like="%503%", sitemap_ids=None)
        where, params = reset_mod._build_where(args)
        assert "last_extract_error LIKE :pattern" in where
        assert params["pattern"] == "%503%"

    def test_sitemap_ids_filters_by_id_list(self):
        args = argparse.Namespace(all_retired=False, like=None, sitemap_ids=[1, 2, 3])
        where, params = reset_mod._build_where(args)
        assert "sitemap_id = ANY(:sitemap_ids)" in where
        assert params["sitemap_ids"] == [1, 2, 3]

    def test_always_scoped_to_failed_pending_articles(self):
        """Never touches an article that hasn't failed at all (attempts=0) or one
        that already extracted successfully -- there is nothing to reset there."""
        args = argparse.Namespace(all_retired=True, like=None, sitemap_ids=None)
        where, _ = reset_mod._build_where(args)
        assert "knowledge_extracted = 0" in where
        assert "knowledge_extract_attempts > 0" in where

    def test_filters_combine_with_and(self):
        args = argparse.Namespace(all_retired=True, like="%503%", sitemap_ids=[7])
        where, params = reset_mod._build_where(args)
        assert where.count(" AND ") == 4  # 5 clauses joined
        assert params == {"max_attempts": reset_mod.KNOWLEDGE_EXTRACT_MAX_ATTEMPTS,
                           "pattern": "%503%", "sitemap_ids": [7]}


class TestMainRefusesNoFilter:
    def test_no_filter_flags_raises_argparse_error(self):
        """Refuses to reset every failed attempt in the table with no scoping --
        that would silently erase SYS-19's poison-pill protection wholesale."""
        with patch.object(sys, "argv", ["reset_extraction_attempts.py"]):
            with pytest.raises(SystemExit):
                reset_mod.main()


class TestMainDryRunVsWrite:
    def _mock_client(self, count):
        client = MagicMock()
        session = MagicMock()
        session.execute.return_value.scalar.return_value = count
        client.get_session.return_value.__enter__.return_value = session
        client.get_session.return_value.__exit__.return_value = False
        return client, session

    def test_dry_run_never_issues_the_update(self):
        client, session = self._mock_client(count=5)
        with patch.object(sys, "argv", ["reset_extraction_attempts.py", "--all-retired", "--dry-run"]), \
             patch.object(reset_mod, "SQLAlchemyClient", return_value=client):
            reset_mod.main()
        assert session.execute.call_count == 1  # only the COUNT(*)
        session.commit.assert_not_called()

    def test_write_mode_updates_and_commits(self):
        client, session = self._mock_client(count=5)
        with patch.object(sys, "argv", ["reset_extraction_attempts.py", "--all-retired"]), \
             patch.object(reset_mod, "SQLAlchemyClient", return_value=client):
            reset_mod.main()
        assert session.execute.call_count == 2  # COUNT(*) then UPDATE
        session.commit.assert_called_once()
        update_sql = str(session.execute.call_args_list[1][0][0])
        assert "UPDATE articles" in update_sql
        assert "knowledge_extract_attempts = 0" in update_sql
        assert "last_extract_error = NULL" in update_sql

    def test_zero_matches_skips_the_update(self):
        client, session = self._mock_client(count=0)
        with patch.object(sys, "argv", ["reset_extraction_attempts.py", "--all-retired"]), \
             patch.object(reset_mod, "SQLAlchemyClient", return_value=client):
            reset_mod.main()
        assert session.execute.call_count == 1
        session.commit.assert_not_called()
