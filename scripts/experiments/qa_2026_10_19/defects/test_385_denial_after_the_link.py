"""QA #385 (SYS-185): a denial AFTER the causal word ("... dibantah maskapai") does not negate
the link.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.core import causal_check as cc  # noqa: E402


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


CLAIM = "Harga tiket pesawat domestik naik karena harga avtur melonjak."


def test_a_denial_after_the_link_backs_no_flat_claim():
    src = "Anggapan bahwa harga tiket pesawat domestik naik karena harga avtur melonjak dibantah maskapai."
    assert not kept(CLAIM, src)


def test_control_a_denial_before_the_link_is_read():
    assert not kept(CLAIM, "Maskapai membantah harga tiket pesawat domestik naik karena harga avtur melonjak.")
