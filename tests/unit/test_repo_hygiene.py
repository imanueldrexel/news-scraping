"""Byte-level repo hygiene the rest of the suite depends on."""
import os
import re
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tracked(pattern):
    out = subprocess.run(["git", "ls-files", pattern], cwd=REPO, capture_output=True, text=True, check=True)
    return [os.path.join(REPO, p) for p in out.stdout.split()]


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
