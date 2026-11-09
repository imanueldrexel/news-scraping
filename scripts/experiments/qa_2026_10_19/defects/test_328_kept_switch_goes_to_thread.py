"""QA #328 (SYS-145): the same switch, kept unchanged by the model, goes kept-thread on the served
path (live: Garuda 0/5). Same root as the #327 defect (followup.refers_to_thread).
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
])
def test_a_kept_switch_stays_kept(question):
    assert fu.resolve(question, ANTAM, question).how == fu.KEPT


def test_control_a_kept_effect_question_uses_the_thread():
    q = "Bagaimana dampaknya ke rupiah?"
    assert fu.resolve(q, FED, q).how == fu.KEPT_THREAD
