"""QA #331 (SYS-146): "ditanya" (was asked) and "menanya" end in -nya but are no clitic;
possessive_root cuts them to "dita" / "mena".
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.web import keywords as kw  # noqa: E402


@pytest.mark.parametrize("question,word", [("Apa jawaban Menkeu saat ditanya soal utang?", "ditanya"),
                                           ("Siapa yang menanya soal utang?", "menanya")])
def test_a_non_clitic_word_is_kept_whole(question, word):
    words = [t.word for t in kw.terms(question)]
    assert word in words and word[:-3] not in words
