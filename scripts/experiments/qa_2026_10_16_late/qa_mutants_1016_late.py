"""QA 2026-10-16 (late): QA's own mutants for the SYS-171 rework and SYS-174..176 (tracker #336).

Each mutates behaviour a ticket or the dev's comment names that the registry (`sys171_*` .. `sys176_*`) does not.
Applied in a copy of the tree only (the 12:00 newsletter imports the live one), restored byte for byte.

    git -c core.autocrlf=false archive HEAD newscrawler scripts tests __main__.py pytest.ini EXPERIMENTS.md | tar -x -C <dir>
    venv\Scripts\python.exe scripts\experiments\qa_2026_10_16_late\qa_mutants_1016_late.py <dir> [NAME ...]

QA_TESTS overrides the tests (default: the four arc suites). KILLED = a test went red.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PY = os.path.join(REPO, "venv", "Scripts", "python.exe")
SA, SC = "newscrawler/core/story_arc.py", "newscrawler/core/source_check.py"
ARC_TESTS = ["tests/unit/test_story_arc.py", "tests/unit/test_source_check.py", "tests/unit/test_arc_style.py",
             "tests/unit/test_replay_story_arcs.py"]

QA = [
    # SYS-174: a span that ends today
    ("qa16l_span_ending_today_runs", SA, "    if last <= digest_date:\n", "    if last < digest_date:\n"),
    # SYS-171: each piece of the weekday of a week
    ("qa16l_dow_no_minggu_week", SC, r"(?:{'|'.join(copy.DAYS)})\s+(?:pekan|minggu)\s+(?:depan|mendatang|ini)",
     r"(?:{'|'.join(copy.DAYS)})\s+(?:pekan)\s+(?:depan|mendatang|ini)"),
    ("qa16l_dow_no_mendatang", SC, r"(?:{'|'.join(copy.DAYS)})\s+(?:pekan|minggu)\s+(?:depan|mendatang|ini)",
     r"(?:{'|'.join(copy.DAYS)})\s+(?:pekan|minggu)\s+(?:depan|ini)"),
    ("qa16l_dow_no_ini", SC, r"(?:{'|'.join(copy.DAYS)})\s+(?:pekan|minggu)\s+(?:depan|mendatang|ini)",
     r"(?:{'|'.join(copy.DAYS)})\s+(?:pekan|minggu)\s+(?:depan|mendatang)"),
    ("qa16l_dow_no_hari", SC, r'_DAY_OF_WEEK = rf"(?:hari\s+)?(?:', r'_DAY_OF_WEEK = rf"(?:'),
    ("qa16l_week_implied_depan_only", SC, r'(?P<week>pekan (?:depan|ini))', r'(?P<week>pekan (?:depan))'),
    # SYS-175: the words before N after an adjacent "mencapai"
    ("qa16l_mencapai_then_digit_only", SC, r'|\s+mencapai"', r'|\s+mencapai(?=\s+\d)"'),
    # SYS-176: each piece of the weekday before a date
    ("qa16l_wd_date_no_hari", SC, r'_WEEKDAY_BEFORE_DATE = rf"(?:(?:hari\s+)?(?:', r'_WEEKDAY_BEFORE_DATE = rf"(?:(?:'),
    ("qa16l_wd_date_no_comma", SC, r"(?:{'|'.join(copy.DAYS)}),?\s*\(?(?=", r"(?:{'|'.join(copy.DAYS)})\s*\(?(?="),
    ("qa16l_wd_date_no_paren", SC, r"(?:{'|'.join(copy.DAYS)}),?\s*\(?(?=", r"(?:{'|'.join(copy.DAYS)}),?\s*(?="),
    ("qa16l_wd_date_no_long", SC, r"(?=\d{{1,2}}(?:/|\s+(?:{_MONTH_NAME})\b)))?", r"(?=\d{{1,2}}(?:/)))?"),
]


def main(root, names):
    tests = os.environ.get("QA_TESTS", " ".join(ARC_TESTS)).split()
    scratch = tempfile.mkdtemp(prefix="qa16l_")
    env = dict(os.environ, VECTOR_DB_NAME_L1=os.path.join(scratch, "L1"), VECTOR_DB_NAME_L2=os.path.join(scratch, "L2"),
               POSTGRES_DB_PORT="1", TELEGRAM_BOT_TOKEN="", PYTHONDONTWRITEBYTECODE="1")
    tally = {}
    for name, path, old, new in QA:
        if names and name not in names:
            continue
        p = os.path.join(root, path)
        original = open(p, "rb").read()
        src = original.decode("utf-8")
        if src.count(old) != 1:
            verdict, tail = "NOT FOUND", [f"{src.count(old)} matches"]
        else:
            try:
                open(p, "wb").write(src.replace(old, new).encode("utf-8"))
                r = subprocess.run([PY, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"], cwd=root, env=env,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                verdict = "SURVIVED" if r.returncode == 0 else "KILLED"
                tail = [line for line in r.stdout.splitlines() if " passed" in line or " failed" in line][-1:]
            finally:
                open(p, "wb").write(original)
        print(f"{name}: {verdict} {tail}", flush=True)
        tally[verdict] = tally.get(verdict, 0) + 1
    print(tally)


if __name__ == "__main__":
    if os.path.abspath(sys.argv[1]) == REPO:
        sys.exit("refusing to mutate the live tree: pass a copy")
    main(sys.argv[1], sys.argv[2:])
