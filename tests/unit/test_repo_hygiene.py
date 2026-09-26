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
