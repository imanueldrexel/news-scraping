"""QA #394 (SYS-193): a fronted end point ("Hingga 2026, pembekuan saham berlanjut.") has no
content word before its opener, so it is matched by its time alone and backed by another subject's end.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.core import source_check as sc  # noqa: E402

MSCI = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. "
        "Freeze MSCI berpotensi berlanjut hingga semester II-2027. Wilbert memperkirakan MSCI akan memperpanjang "
        "kebijakan pembekuan pada evaluasi November 2026.")


SRC = ("Defisit APBN hingga September 2026 mencapai Rp319 triliun. Pembekuan saham berlanjut setelah evaluasi "
       "November 2026.")


def test_a_fronted_end_needs_its_subject():
    assert sc.unbacked_end_times("Hingga 2026, pembekuan saham berlanjut.", SRC) != []


def test_control_the_same_end_not_fronted_is_refused():
    assert sc.unbacked_end_times("Pembekuan saham berlanjut hingga 2026.", SRC) != []
