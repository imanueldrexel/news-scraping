"""QA 2026-10-16 (night): QA's own mutants for the SYS-169 rework and SYS-171..173 (tracker #336).

Each mutates behaviour a ticket or the dev's comment names that the registry (`sys169_*` .. `sys173_*`) does not.
Applied in a copy of the tree only (the 12:00 newsletter imports the live one), restored byte for byte.

    git -c core.autocrlf=false archive HEAD newscrawler scripts tests __main__.py pytest.ini EXPERIMENTS.md | tar -x -C <dir>
    venv\Scripts\python.exe scripts\experiments\qa_2026_10_16_night\qa_mutants_1016_night.py <dir> [NAME ...]

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
    # SYS-169: the skip is for future phrases only
    ("qa16n_span_skips_every_phrase", SA, "if not future_phrases(phrase)\n", "if not relative_times(phrase, digest_date)\n"),
    ("qa16n_given_from_own_text", SC, "    given = future_times(stated)\n", "    given = future_times(stated) | future_times(text)\n"),
    # SYS-171: weekday and window pieces
    ("qa16n_day_ahead_no_mendatang", SC, r'{_WEEKDAY_BUT_SUNDAY})\s+(?:depan|mendatang)"', r'{_WEEKDAY_BUT_SUNDAY})\s+(?:depan)"'),
    ("qa16n_day_key_first_word", SC, 'return f"hari {key.split()[-2]} depan"', 'return f"hari {key.split()[0]} depan"'),
    ("qa16n_day_key_keeps_suffix", SC, 'return f"hari {key.split()[-2]} depan"', 'return "hari " + " ".join(key.split()[-2:])'),
    ("qa16n_window_no_vague", SC, r"(?:se|(?:{'|'.join(_COUNT)}|\d+|{_VAGUE_COUNT})\s+)", r"(?:se|(?:{'|'.join(_COUNT)}|\d+)\s+)"),
    ("qa16n_window_no_digits", SC, r"(?:se|(?:{'|'.join(_COUNT)}|\d+|{_VAGUE_COUNT})\s+)", r"(?:se|(?:{'|'.join(_COUNT)}|{_VAGUE_COUNT})\s+)"),
    ("qa16n_window_no_tahun", SC, r"(?:hari|pekan|minggu|bulan|tahun)\s+ke\s+depan", r"(?:hari|pekan|minggu|bulan)\s+ke\s+depan"),
    ("qa16n_window_no_hari", SC, r"(?:hari|pekan|minggu|bulan|tahun)\s+ke\s+depan", r"(?:pekan|minggu|bulan|tahun)\s+ke\s+depan"),
    ("qa16n_day_ahead_case_sensitive", SC, "_DAY_AHEAD_ONLY = re.compile(_DAY_AHEAD, re.IGNORECASE)", "_DAY_AHEAD_ONLY = re.compile(_DAY_AHEAD)"),
    # SYS-172: the list before N
    ("qa16n_no_level", SC, "|mencapai|total|angka|level|posisi\"", "|mencapai|total|angka|posisi\""),
    ("qa16n_no_sampai", SC, '_CHANGE_TO = r"(?:men)?jadi|hingga|sampai|ke"', '_CHANGE_TO = r"(?:men)?jadi|hingga|ke"'),
    # SYS-173: each boundary
    ("qa16n_awal_to_tuesday", SC, '{"awal": (0, 2),', '{"awal": (0, 1),'),
    ("qa16n_pertengahan_from_monday", SC, '"pertengahan": (1, 3),', '"pertengahan": (0, 3),'),
    ("qa16n_pertengahan_to_friday", SC, '"pertengahan": (1, 3),', '"pertengahan": (1, 4),'),
    ("qa16n_akhir_from_wednesday", SC, '"akhir": (3, 6)}', '"akhir": (2, 6)}'),
    ("qa16n_akhir_no_sunday", SC, '"akhir": (3, 6)}', '"akhir": (3, 5)}'),
    ("qa16n_part_this_week", SC, "    monday = _last_week(m, today)[0]\n    first, last",
     "    monday = today - timedelta(days=today.weekday())\n    first, last"),
]


def main(root, names):
    tests = os.environ.get("QA_TESTS", " ".join(ARC_TESTS)).split()
    scratch = tempfile.mkdtemp(prefix="qa16n_")
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
