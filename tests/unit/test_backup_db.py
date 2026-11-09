"""OPS-23 (#164): the database backup's decisions, offline.

Docker is replaced by a fake `run`. What is guarded: a dump that does not verify
is never kept and never triggers retention (so a broken backup cannot delete the
last good one), the container is never guessed, and a stale newest dump is
reported as stale.
"""
import importlib.util
import os
import subprocess
from types import SimpleNamespace

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "backup_db.py",
)
_spec = importlib.util.spec_from_file_location("backup_db", _SCRIPT)
bk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bk)

GOOD_TOC = "\n".join(
    "30%02d; 0 16390 TABLE DATA public %s postgres" % (i, t) for i, t in enumerate(bk.REQUIRED_TABLES)
).encode()


class FakeDocker:
    """Records calls; `ps` names the running containers, `dump_rc`/`toc` shape pg_dump
    and pg_restore --list."""

    def __init__(self, ps="pg-prod\n", dump_rc=0, toc=GOOD_TOC, list_rc=0):
        self.ps, self.dump_rc, self.toc, self.list_rc = ps, dump_rc, toc, list_rc
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "ps"]:
            return SimpleNamespace(returncode=0, stdout=self.ps, stderr="")
        if "pg_dump" in cmd:
            kw["stdout"].write(b"PGDMP fake archive bytes")
            return SimpleNamespace(returncode=self.dump_rc, stderr=b"pg_dump: boom" if self.dump_rc else b"")
        if "pg_restore" in cmd:
            return SimpleNamespace(returncode=self.list_rc, stdout=self.toc, stderr=b"bad archive")
        raise AssertionError("unexpected command %r" % (cmd,))


@pytest.fixture(autouse=True)
def _no_explicit_container(monkeypatch):
    monkeypatch.delenv("DB_CONTAINER", raising=False)


def _seed(tmp_path, n):
    """n old verified dumps, oldest first by name (the stamp sorts lexically)."""
    paths = []
    for i in range(n):
        p = tmp_path / ("%s_20260901T0000%02dZ.dump" % (bk.DB_NAME, i))
        p.write_bytes(b"old")
        paths.append(p)
    return paths


class TestBackup:
    def test_a_verified_dump_is_kept_and_old_ones_pruned_to_keep(self, tmp_path):
        old = _seed(tmp_path, 4)
        new = bk.backup(keep=3, backup_dir=str(tmp_path), run=FakeDocker())
        assert os.path.exists(new) and new.endswith(".dump")
        left = sorted(p.name for p in tmp_path.iterdir())
        assert len(left) == 3 and os.path.basename(new) in left
        assert not old[0].exists() and not old[1].exists()
        assert not any(n.endswith(".partial") for n in left)

    @pytest.mark.parametrize("docker", [
        FakeDocker(dump_rc=1),                                   # pg_dump failed
        FakeDocker(list_rc=1),                                   # archive unreadable
        FakeDocker(toc=GOOD_TOC.replace(b" sitemaps ", b" nope ")),  # a table's data missing
    ], ids=["pg_dump-fails", "archive-unreadable", "table-missing"])
    def test_a_bad_dump_is_discarded_and_deletes_nothing(self, tmp_path, docker):
        """Retention after a failed dump would be the incident this ticket is about:
        the one good backup pruned in favour of a broken one."""
        old = _seed(tmp_path, 3)
        with pytest.raises(bk.BackupError):
            bk.backup(keep=1, backup_dir=str(tmp_path), run=docker)
        assert sorted(p.name for p in tmp_path.iterdir()) == [p.name for p in old]

    def test_the_missing_table_is_named(self, tmp_path):
        with pytest.raises(bk.BackupError, match="sitemaps"):
            bk.backup(backup_dir=str(tmp_path), run=FakeDocker(toc=GOOD_TOC.replace(b" sitemaps ", b" x ")))

    def test_dump_runs_inside_the_found_container(self, tmp_path):
        docker = FakeDocker(ps="pg-prod\n")
        bk.backup(backup_dir=str(tmp_path), run=docker)
        dump = next(c for c in docker.calls if "pg_dump" in c)
        assert dump[:4] == ["docker", "exec", "-i", "pg-prod"] and "-Fc" in dump


class TestFindContainer:
    @pytest.mark.parametrize("ps", ["", "a\nb\n"], ids=["none", "two"])
    def test_zero_or_several_candidates_is_an_error_not_a_guess(self, ps):
        with pytest.raises(bk.BackupError, match="DB_CONTAINER"):
            bk.find_container(FakeDocker(ps=ps))

    def test_db_container_overrides_discovery(self, monkeypatch):
        monkeypatch.setenv("DB_CONTAINER", "explicit")
        docker = FakeDocker(ps="a\nb\n")
        assert bk.find_container(docker) == "explicit"
        assert docker.calls == []


class TestAge:
    def test_no_dump_is_none(self, tmp_path):
        assert bk.newest_dump_age_hours(str(tmp_path)) is None

    def test_partials_do_not_count_as_a_backup(self, tmp_path):
        (tmp_path / ("%s_20260925T000000Z.dump.partial" % bk.DB_NAME)).write_bytes(b"x")
        assert bk.newest_dump_age_hours(str(tmp_path)) is None

    def test_age_is_from_the_newest(self, tmp_path):
        a, b = _seed(tmp_path, 2)
        os.utime(a, (1000, 1000))
        os.utime(b, (1000 + 3600 * 5, 1000 + 3600 * 5))
        assert bk.newest_dump_age_hours(str(tmp_path), now=1000 + 3600 * 7) == pytest.approx(2.0)


def test_main_notifies_and_exits_1_on_failure(monkeypatch):
    sent = []
    monkeypatch.setattr(bk, "backup", lambda keep: (_ for _ in ()).throw(bk.BackupError("boom")))
    monkeypatch.setattr(bk, "_notify", sent.append)
    assert bk.main([]) == 1
    assert sent and "boom" in sent[0]


def test_real_subprocess_is_the_default():
    """The fake is injected, never the default -- a test double left as default would
    make the scheduled job a no-op."""
    assert bk.backup.__defaults__[-1] is subprocess.run
