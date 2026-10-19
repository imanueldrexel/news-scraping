"""QA #327 (SYS-144): a topic switch whose only name stands in an object phrase ("terjadi pada
Garuda Indonesia") and that holds an adverb not on nya_words.ADVERBS goes to the old thread on the fallback
path. Live (read-only): Garuda 3/5 -> 0/5 and 5/5 -> 0/5.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.web import followup as fu  # noqa: E402

ANTAM = ["Berapa harga emas Antam hari ini?"]
FED = ["Apa keputusan The Fed terbaru?"]


@pytest.mark.parametrize("question", [
    "Apa yang harusnya dilakukan pemerintah terhadap Garuda Indonesia?",
    "Apa yang aslinya terjadi pada Garuda Indonesia?",
    "Apa yang mestinya terjadi pada Sritex?",
    "Kayaknya ada masalah di Waskita Karya, apa itu?",
])
def test_a_switch_stays_alone_on_the_fallback(question):
    assert fu.resolve(question, ANTAM, None).how == fu.FALLBACK_OWN


def test_control_a_listed_adverb_stays_alone():
    assert fu.resolve("Apa yang sebenarnya terjadi pada Garuda Indonesia?", ANTAM, None).how == fu.FALLBACK_OWN
