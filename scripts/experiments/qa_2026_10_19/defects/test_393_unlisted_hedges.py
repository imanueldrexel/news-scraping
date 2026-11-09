"""QA #393 (SYS-192): hedges outside _HEDGE (diperkirakan, diyakini, disebut-sebut) are dropped
silently: the source's suspicion backs a claim that states the cause as fact.
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from newscrawler.core import causal_check as cc  # noqa: E402


def kept(prose, quote):
    return cc.unbacked_causes([("latar", prose)], [(0, quote)], {0: quote}) == []


FACT = "Kebakaran gudang itu dipicu korsleting listrik."


@pytest.mark.parametrize("src", [
    "Kebakaran gudang itu diperkirakan dipicu korsleting listrik.",
    "Kebakaran gudang itu diyakini dipicu korsleting listrik.",
    "Kebakaran gudang itu disebut-sebut dipicu korsleting listrik.",
])
def test_a_dropped_hedge_is_refused(src):
    assert not kept(FACT, src)


def test_control_a_listed_hedge_is_refused():
    assert not kept(FACT, "Kebakaran gudang itu diduga dipicu korsleting listrik.")
