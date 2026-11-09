"""QA #328 (SYS-145): _OBJECT_PHRASE takes at most 4 words, so a name as the 5th word of the object
phrase reads as the follow-up's own subject and the Fed thread is dropped.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.web import followup as fu  # noqa: E402

ANTAM = ["Berapa harga emas Antam hari ini?"]
FED = ["Apa keputusan The Fed terbaru?"]


def test_a_name_late_in_the_object_phrase_keeps_the_thread():
    q = "Bagaimana dampaknya ke saham bank BUMN seperti BBRI?"
    assert fu.resolve(q, FED, q).how == fu.KEPT_THREAD


def test_control_a_short_object_phrase_keeps_the_thread():
    q = "Bagaimana dampaknya ke saham BBRI?"
    assert fu.resolve(q, FED, q).how == fu.KEPT_THREAD
