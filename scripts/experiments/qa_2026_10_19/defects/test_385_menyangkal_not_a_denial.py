"""QA #385 (SYS-185): "menyangkal" / "disangkal" (to deny) is not in _DENIAL, so a denied link
backs the flat claim.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.core import causal_check as cc  # noqa: E402


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


CLAIM = "Harga tiket pesawat domestik naik karena harga avtur melonjak."


@pytest.mark.parametrize("src", [
    "Maskapai menyangkal harga tiket pesawat domestik naik karena harga avtur melonjak.",
    "Kabar harga tiket pesawat domestik naik karena harga avtur melonjak disangkal maskapai.",
])
def test_a_denied_link_backs_no_flat_claim(src):
    assert not kept(CLAIM, src)
