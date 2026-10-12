"""DBT-67 (#325, ADR-015): the shared store-repair steps live in newscrawler/tools/store_repair.py.

The four repair scripts used to put scripts/ on sys.path and call each other's private helpers, and
the copies drifted (SYS-111: one script resolved its deadline twice). These tests keep the toolkit
in one place: no repair script imports another script for a step, the module imports no script,
and no script defines its own copy of a step again."""
import ast
import os

from newscrawler.tools import store_repair

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO, "scripts")
TOOLKIT = ("repair_boilerplate_bodies", "rechunk_stale_chunks", "settle_out_of_scope_links",
           "drop_oversized_queued_chunks", "backfill_orphan_chunks", "recount_entity_mentions",
           "repair_store_consistency", "requeue_cascaded_articles", "repair_faiss_posted_at")
# The OPS-01 Telegram notifier is shared by eight scripts (the scheduled jobs too); moving it is not
# DBT-67's change.
NOT_A_REPAIR_STEP = {"notify_telegram"}
STEPS = {"crawl_running", "_crawl_running", "parse_until", "too_close", "faiss_dirs", "_faiss_dirs",
         "delete_vectors", "rechunk", "rechunk_articles", "vector_ids_for", "_NoEmbeddings", "NoEmbeddings",
         "recount_entity_counts"}


def _script_names():
    return {f[:-3] for f in os.listdir(SCRIPTS) if f.endswith(".py")}


def _imported_modules(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module.split(".")[0]


def _definitions(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def test_no_repair_script_imports_another_script():
    scripts = _script_names()
    offenders = {}
    for name in TOOLKIT:
        found = sorted(set(_imported_modules(os.path.join(SCRIPTS, name + ".py"))) & scripts - NOT_A_REPAIR_STEP)
        if found:
            offenders[name] = found
    assert offenders == {}


def test_the_module_imports_no_script_and_leaves_sys_path_alone():
    path = store_repair.__file__
    assert not set(_imported_modules(path)) & _script_names()
    with open(path, encoding="utf-8") as f:
        assert "sys.path" not in f.read()


def test_no_script_keeps_its_own_copy_of_a_step():
    copies = {}
    for name in sorted(_script_names()):
        own = _definitions(os.path.join(SCRIPTS, name + ".py")) & STEPS
        if own:
            copies[name] = sorted(own)
    assert copies == {}


def test_the_scripts_call_the_modules_steps():
    """Imported by name: one object, so a test that patches the module's step or the script's name
    is patching the real thing, never a stale copy."""
    import importlib.util
    for name, step in (("repair_boilerplate_bodies", "delete_vectors"), ("rechunk_stale_chunks", "rechunk"),
                       ("settle_out_of_scope_links", "backup"), ("drop_oversized_queued_chunks", "crawl_running"),
                       ("backfill_orphan_chunks", "rechunk_articles")):
        spec = importlib.util.spec_from_file_location(f"dbt67_{name}", os.path.join(SCRIPTS, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert getattr(mod, step) is getattr(store_repair, step), (name, step)


def test_backup_dir_is_read_in_the_module_only():
    """A test redirects store_repair.BACKUP_DIR once for every caller. A copy in a script would be a
    second value, and a fixture that redirected the copy would leave the real backups/ in use."""
    for name in TOOLKIT:
        with open(os.path.join(SCRIPTS, name + ".py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        assigned = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
        imported = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                    and n.module == "newscrawler.tools.store_repair" for a in n.names}
        if name in ("repair_store_consistency", "requeue_cascaded_articles"):
            continue    # their own backups (OPS-04, SRC-54) predate the toolkit and are not its steps
        assert "BACKUP_DIR" not in assigned | imported, name
