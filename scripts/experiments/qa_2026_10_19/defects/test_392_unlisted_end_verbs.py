"""QA #392 (SYS-191): end points opened by "dihentikan pada", "diakhiri pada" or "paling lambat"
are read by no pattern, so the MSCI false end (the source: the freeze runs past November 2026) is printed.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.core import source_check as sc  # noqa: E402

MSCI = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. "
        "Freeze MSCI berpotensi berlanjut hingga semester II-2027. Wilbert memperkirakan MSCI akan memperpanjang "
        "kebijakan pembekuan pada evaluasi November 2026.")


@pytest.mark.parametrize("prose", [
    "Pembekuan dihentikan pada November 2026.",
    "Pembekuan diakhiri pada November 2026.",
    "Pembekuan hanya bertahan paling lambat November 2026.",
])
def test_an_unstated_end_is_refused(prose):
    assert sc.unbacked_end_times(prose, MSCI) != []


def test_control_a_listed_opener_is_refused():
    assert sc.unbacked_end_times("Pembekuan berakhir pada November 2026.", MSCI) != []
