"""QA #381 (SYS-181): an anaphor whose subject shares one root with the previous sentence lends
that sentence's other subject.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.core import causal_check as cc  # noqa: E402


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


SRC = "IHSG turun 1 persen pada Senin. Penurunan saham BBRI tersebut dipicu aksi jual asing."


def test_another_subject_is_not_backed_through_the_anaphor():
    assert not kept("IHSG turun karena aksi jual asing.", SRC)


def test_control_the_anaphors_own_subject_stays_kept():
    assert kept("Saham BBRI turun karena aksi jual asing.", SRC)
