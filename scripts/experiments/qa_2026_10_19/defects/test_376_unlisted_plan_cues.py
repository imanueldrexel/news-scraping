"""QA #376 (SYS-177 send-back): plan words outside _FUTURE_VERB ("dipastikan", "dijanjikan") do
not cue a latar schedule, so on 26/10 a source's past 22/10 backs an invented "terbit akhir Oktober".
Run from the repo root: venv\\Scripts\\python.exe -m pytest <this file> -q -p no:cacheprovider"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())  # run from the repo root

from datetime import date  # noqa: E402

import newscrawler.core.story_arc as sa  # noqa: E402
from newscrawler.core.llm_json import Rejected  # noqa: E402
from tests.unit.test_story_arc import FRAME, TEXTS, TIMELINE, _answer  # noqa: E402

D26 = date(2026, 10, 26)
LATAR = FRAME + "Pada 23/9 Seskab melaporkan 209 hektare lahan masih terbakar. "
PAST = [TEXTS[0].replace("Rapat lanjutan dijadwalkan Kamis (15/10).",
                         "Rapat lanjutan belum dijadwalkan. Asap meluas sejak Kamis (22/10)."), *TEXTS[1:]]


def reason(latar):
    try:
        sa.parse(_answer(latar=LATAR + latar, agenda=""), PAST, TIMELINE, D26)
    except Rejected as e:
        return e.reason
    return "kept"


@pytest.mark.parametrize("latar", ["Aturan barunya dipastikan terbit akhir Oktober.",
                                   "Aturan barunya dijanjikan terbit akhir Oktober."])
def test_an_invented_schedule_is_refused(latar):
    assert reason(latar) == "date"


def test_control_a_listed_cue_is_refused():
    assert reason("Aturan barunya diperkirakan terbit akhir Oktober.") == "date"
