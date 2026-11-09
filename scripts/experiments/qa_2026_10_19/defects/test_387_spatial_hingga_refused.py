"""QA #387 (SYS-186 send-back): the widened gap reads a place after "hingga" as an end point:
"asap meluas hingga Riau pada akhir Oktober" (spatial: as far as Riau) is refused, a false refusal.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.core import source_check as sc  # noqa: E402

MSCI = ("Kebijakan pembekuan saham Indonesia diperkirakan masih berlanjut setelah evaluasi indeks pada November 2026. "
        "Freeze MSCI berpotensi berlanjut hingga semester II-2027. Wilbert memperkirakan MSCI akan memperpanjang "
        "kebijakan pembekuan pada evaluasi November 2026.")


SRC = "Asap meluas sejak Kamis (22/10). Rapat lanjutan belum dijadwalkan."


def test_a_spatial_hingga_is_no_end_point():
    assert sc.unbacked_end_times("Sebelumnya, asap meluas hingga Riau pada akhir Oktober.", SRC) == []


def test_control_a_time_end_point_is_still_read():
    assert sc.unbacked_end_times("Pembekuan berlanjut hingga akhir Oktober.", SRC) != []
