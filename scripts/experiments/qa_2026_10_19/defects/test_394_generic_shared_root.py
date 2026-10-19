"""QA #394 (SYS-193): one generic shared root ("saham") is taken for the subject, so retail stock
sales' period-to-date end backs the freeze's end.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.core import source_check as sc  # noqa: E402

MSCI = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. "
        "Freeze MSCI berpotensi berlanjut hingga semester II-2027. Wilbert memperkirakan MSCI akan memperpanjang "
        "kebijakan pembekuan pada evaluasi November 2026.")


def test_a_generic_shared_word_is_not_the_subject():
    src = ("Penjualan saham ritel hingga September 2026 naik 12 persen. Pembekuan saham berlanjut setelah evaluasi "
           "November 2026.")
    assert sc.unbacked_end_times("Pembekuan saham berlanjut hingga 2026.", src) != []
