"""QA #390 (SYS-189): causal forms outside _KINDS (terimbas, dipacu, terdorong, buntut) need no
quote, so an invented link is accepted against a source that names no reason.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.core import causal_check as cc  # noqa: E402


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


NO_REASON = "Rupiah melemah 0,5 persen ke Rp16.500 per dolar AS pada Senin."


@pytest.mark.parametrize("prose", [
    "Rupiah melemah, terimbas data tenaga kerja AS yang kuat.",
    "Rupiah melemah, dipacu data tenaga kerja AS yang kuat.",
    "Rupiah melemah, terdorong data tenaga kerja AS yang kuat.",
    "Rupiah melemah, buntut data tenaga kerja AS yang kuat.",
])
def test_an_invented_link_is_refused(prose):
    assert not kept(prose, NO_REASON)


def test_control_a_listed_form_is_refused():
    assert not kept("Rupiah melemah, didorong data tenaga kerja AS yang kuat.", NO_REASON)
