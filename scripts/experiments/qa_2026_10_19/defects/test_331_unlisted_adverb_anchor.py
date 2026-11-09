"""QA #331 (SYS-146): an adverb in -nya that is not on nya_words.ADVERBS is cut to a "root" and
becomes a rare required keyword anchor ("mestinya" -> "mesti"). Live: "Apa yang mestinya terjadi pada Sritex?" fts=0.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.web import keywords as kw  # noqa: E402


@pytest.mark.parametrize("question,plain", [
    ("Apa yang mestinya terjadi pada Sritex?", "Apa yang terjadi pada Sritex?"),
    ("Apa yang harusnya dilakukan Garuda?", "Apa yang dilakukan Garuda?"),
    ("Apa yang aslinya terjadi pada Garuda?", "Apa yang terjadi pada Garuda?"),
])
def test_an_adverb_adds_no_keyword(question, plain):
    assert [t.word for t in kw.terms(question)] == [t.word for t in kw.terms(plain)]
