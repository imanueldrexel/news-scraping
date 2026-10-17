"""Byte-level repo hygiene the rest of the suite depends on."""
import os
import re
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tracked(pattern):
    out = subprocess.run(["git", "ls-files", pattern], cwd=REPO, capture_output=True, text=True, check=True)
    # One path per line: a path may hold spaces ("reports/In prompt causal claim checking.md", DBT-81).
    return [os.path.join(REPO, p) for p in out.stdout.splitlines() if p]


def test_tracked_keeps_a_path_with_a_space_whole():
    """DBT-81 (#380): split() opened the fragment "reports/In" and failed the markdown hygiene tests."""
    paths = _tracked("reports/*.md")
    assert paths and all(os.path.exists(p) for p in paths)
    assert any(" " in os.path.basename(p) for p in paths)


def test_hashed_gold_fixtures_are_lf_on_disk():
    """DBT-41 (#171): the gold set's identity is the sha256 of the bytes on disk.
    CRLF here (a checkout with core.autocrlf=true) changes it."""
    for path in _tracked("tests/fixtures/*.jsonl"):
        assert b"\r\n" not in open(path, "rb").read(), "%s has CRLF; see .gitattributes" % path


def test_gitattributes_pins_the_fixture_line_endings():
    out = subprocess.run(["git", "check-attr", "eol", "--", "tests/fixtures/filter_gold.jsonl"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    assert out.strip().endswith("eol: lf")


def test_no_bare_carriage_return_in_tracked_markdown():
    r"""DBT-42 (#172): OPERATIONS.md carried scripts<CR>un_scheduled_crawl.py -- a
    Windows path written through a non-raw string, where "\r" is a carriage return."""
    offenders = {}
    for path in _tracked("*.md"):
        hits = [m.start() for m in re.finditer(rb"\r(?!\n)", open(path, "rb").read())]
        if hits:
            offenders[os.path.relpath(path, REPO)] = hits
    assert offenders == {}


def test_no_control_characters_in_tracked_markdown():
    r"""DBT-65 (#318): EXPERIMENTS.md's OPS-47 trap line read `rmdir <wt>?env`: the `\v` of
    `<wt>\venv` was written through a string that made it a vertical tab (0x0B). The one instruction
    for the incident that deleted the venv named the wrong directory. Tab, LF and CR are text;
    no other C0 control character belongs in a document."""
    offenders = {}
    for path in _tracked("*.md"):
        data = open(path, "rb").read()
        hits = [(m.start(), m.group(0)) for m in re.finditer(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", data)]
        if hits:
            offenders[os.path.relpath(path, REPO)] = hits
    assert offenders == {}


def _shadowed_names(source):
    """Names a module defines twice at the top level, or a class defines twice in its body: the
    second silently replaces the first, so pytest collects one and an edit to the other never runs."""
    import ast
    import warnings
    from collections import Counter

    def repeated(body, where):
        names = Counter(n.name for n in body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)))
        return ["%s%s x%d" % (where, name, count) for name, count in names.items() if count > 1]

    with warnings.catch_warnings():     # an escape warning in some docstring is not this check's business
        warnings.simplefilter("ignore")
        tree = ast.parse(source)
    found = repeated(tree.body, "")
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            found += repeated(node.body, node.name + ".")
    return found


def test_no_test_module_shadows_a_test_name():
    """DBT-68 (#329): test_source_worker.py defined `class TestSoftDeadline` twice (SYS-139's commit).
    flake8's F811 would catch it, but pre-commit is not wired up."""
    offenders = {}
    for path in _tracked("tests/*test_*.py"):
        with open(path, encoding="utf-8") as f:
            found = _shadowed_names(f.read())
        if found:
            offenders[os.path.relpath(path, REPO)] = found
    assert offenders == {}


def test_the_shadow_check_finds_a_repeated_class_and_method():
    source = "class A:\n    def t(self): pass\n    def t(self): pass\n\nclass A:\n    pass\n\ndef f(): pass\n"
    assert sorted(_shadowed_names(source)) == ["A x2", "A.t x2"]


MUTATION_RUNNER = os.path.join(REPO, "scripts", "experiments", "qa_mutation_runner.py")


def _registered_mutants(source):
    """The mutation registry `M` of qa_mutation_runner.py: (name, path, old, new), parsed, never run."""
    import ast
    import warnings

    with warnings.catch_warnings():     # an escape warning in some entry is not this check's business
        warnings.simplefilter("ignore")
        tree = ast.parse(source)
    node = next(n for n in tree.body
                if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "M" for t in n.targets))
    return ast.literal_eval(node.value)


def _matches(src, old):
    """How often the runner finds `old` in `src`: as written, else in its CRLF form (the runner's own rule)."""
    count = src.count(old)
    if count != 1 and "\r\n" in src:
        count = src.count(old.replace("\n", "\r\n"))
    return count


def _orphaned(mutants, read):
    return ["%s (%s): %d matches" % (name, path, _matches(read(path), old))
            for name, path, old, _ in mutants if _matches(read(path), old) != 1]


def _read(path):
    with open(os.path.join(REPO, path), "rb") as f:
        return f.read().decode("utf-8")


def test_every_registered_mutant_matches_once():
    """DBT-80 (#369): a refactor that moves the code a mutant targets leaves the mutant matching 0 or 2+ times;
    the runner prints PATTERN NOT FOUND, skips it, and the fix it guarded runs unguarded while the run still looks
    green (27 such entries at e125470). Retarget the entry to the code that now carries the fix, or retire it with
    a comment naming its replacement -- never delete one silently."""
    with open(MUTATION_RUNNER, encoding="utf-8") as f:
        mutants = _registered_mutants(f.read())
    assert len({name for name, *_ in mutants}) == len(mutants), "two registry entries share a name"
    assert [name for name, _, old, new in mutants if old == new] == []
    assert _orphaned(mutants, _read) == []


def test_the_registry_check_finds_a_stale_and_a_doubled_pattern():
    files = {"a.py": "x = 1\ny = 2\n", "b.py": "z = 3\r\nz = 3\r\n", "c.py": "if a:\r\n    b()\r\n"}
    mutants = [("ok", "a.py", "x = 1\n", "x = 2\n"), ("crlf_ok", "c.py", "if a:\n    b()", "if 0:\n    b()"),
               ("stale", "a.py", "w = 9", "w = 0"), ("doubled", "b.py", "z = 3", "z = 4")]
    assert _orphaned(mutants, files.__getitem__) == ["stale (a.py): 0 matches", "doubled (b.py): 2 matches"]
