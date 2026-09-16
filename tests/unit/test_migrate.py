"""
OPS-05: scripts/migrate.py must apply only unrecorded migrations, record each as it
goes, and never treat --seed-existing and normal apply mode the same way (seeding
must never execute a migration's SQL).
"""
import importlib.util
import os
from unittest.mock import MagicMock, patch

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "migrate.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("migrate", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mock_conn(already_applied=(), files_on_disk=None):
    """A fake psycopg2 connection whose cursor tracks executed SQL and supports
    the two queries migrate.py issues (schema_migrations existence, SELECT name)."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False

    executed = []

    def fake_execute(sql, params=None):
        executed.append((sql, params))
        if "SELECT name FROM schema_migrations" in sql:
            cursor.fetchall.return_value = [(name,) for name in already_applied]

    cursor.execute.side_effect = fake_execute
    conn._executed = executed
    return conn, cursor


class TestMigrate:
    def test_dry_run_applies_nothing(self, tmp_path):
        mod = _load()
        conn, cursor = _mock_conn(already_applied=[])
        with patch.object(mod, "_connect", return_value=conn), \
             patch("sys.argv", ["migrate.py", "--dry-run"]):
            result = mod.main()
        assert result == 0
        # Only the schema_migrations bootstrap + SELECT ran -- no migration SQL, no INSERT.
        inserts = [c for c in conn._executed if c[0].strip().upper().startswith("INSERT")]
        assert inserts == []

    def test_nothing_pending_when_all_recorded(self):
        mod = _load()
        conn, cursor = _mock_conn(already_applied=mod.MIGRATIONS)
        with patch.object(mod, "_connect", return_value=conn), \
             patch("sys.argv", ["migrate.py"]):
            result = mod.main()
        assert result == 0
        inserts = [c for c in conn._executed if c[0].strip().upper().startswith("INSERT")]
        assert inserts == []

    def test_seed_existing_records_without_running_sql(self):
        mod = _load()
        conn, cursor = _mock_conn(already_applied=[])
        with patch.object(mod, "_connect", return_value=conn), \
             patch("sys.argv", ["migrate.py", "--seed-existing"]):
            result = mod.main()
        assert result == 0
        # Every migration gets recorded...
        inserts = [c for c in conn._executed if c[0].strip().upper().startswith("INSERT")]
        assert len(inserts) == len(mod.MIGRATIONS)
        # ...but no migration file's actual SQL content was executed (only the
        # schema_migrations bootstrap/SELECT/INSERT statements ran).
        executed_sql = " ".join(c[0] for c in conn._executed)
        assert "CREATE TABLE IF NOT EXISTS chunks" not in executed_sql

    def test_apply_mode_runs_the_real_sql_for_each_pending_file(self):
        mod = _load()
        conn, cursor = _mock_conn(already_applied=[m for m in mod.MIGRATIONS if m != "migrate_phase1.sql"])
        with patch.object(mod, "_connect", return_value=conn), \
             patch("sys.argv", ["migrate.py"]):
            result = mod.main()
        assert result == 0
        executed_sql = " ".join(c[0] for c in conn._executed)
        assert "CREATE TABLE IF NOT EXISTS chunks" in executed_sql
        inserts = [c for c in conn._executed if c[0].strip().upper().startswith("INSERT")]
        assert len(inserts) == 1
        assert inserts[0][1] == ("migrate_phase1.sql",)

    def test_migrations_applied_in_the_documented_order(self):
        mod = _load()
        conn, cursor = _mock_conn(already_applied=[])
        with patch.object(mod, "_connect", return_value=conn), \
             patch("sys.argv", ["migrate.py", "--seed-existing"]):
            mod.main()
        insert_order = [c[1][0] for c in conn._executed if c[0].strip().upper().startswith("INSERT")]
        assert insert_order == mod.MIGRATIONS

    def test_dead_migration_file_is_not_flagged_as_unknown(self, caplog):
        import logging
        mod = _load()
        conn, cursor = _mock_conn(already_applied=mod.MIGRATIONS)
        with patch.object(mod, "_connect", return_value=conn), \
             patch("sys.argv", ["migrate.py"]), \
             caplog.at_level(logging.WARNING):
            mod.main()
        assert not any("migrate_posted_at.sql" in r.message for r in caplog.records)
