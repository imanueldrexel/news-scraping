"""QA 2026-10-18: QA's own mutants for the SYS-152 send-back queue (ADR-019), SYS-186 and SYS-174/177/178/179.

None of these is in the dev's registry (`qa_mutation_runner.M`, sys152_* .. sys179_*): each breaks a line the dev's
closing comments do not name. Run in a COPY of the tree, never the live one (the 12:00 job imports it):

    git -c core.autocrlf=false archive HEAD newscrawler scripts tests __main__.py pytest.ini | tar -x -C <copy>
    venv\\Scripts\\python.exe scripts\\experiments\\qa_2026_10_18\\qa_mutants_1018.py <copy>

Single-line patterns only, so CRLF files (causal_check.py) need no conversion. rc 4/5 (no tests ran) is reported
as ERROR, never as KILLED.
"""
import os
import subprocess
import sys

PY = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                  "venv", "Scripts", "python.exe")
TESTS = ("tests/unit/test_story_arc.py tests/unit/test_source_check.py tests/unit/test_arc_style.py "
         "tests/unit/test_replay_story_arcs.py tests/unit/test_causal_check.py").split()
CC, SA, SC = "newscrawler/core/causal_check.py", "newscrawler/core/story_arc.py", "newscrawler/core/source_check.py"
M = [
    # causal_check (ADR-019)
    ("qa18_causal_word_outside_quote", CC, "if first <= spans[j][0] + m.start() < last]", "if True]"),
    ("qa18_side_runs_past_tetapi", CC, '_SIDE_END = re.compile(r";|" + _CONJUNCTION, re.IGNORECASE)',
     '_SIDE_END = re.compile(r";", re.IGNORECASE)'),
    ("qa18_reference_side_not_widened", CC, "if previous and (not _roots(before) or _REFERENCE.match(before)):",
     "if previous and not _roots(before):"),
    ("qa18_negation_next_word_only", CC, "words[k + 1:k + 4]", "words[k + 1:k + 2]"),
    ("qa18_negated_link_anywhere", CC, r'_NEGATED_LINK = re.compile(r"\b(?:tidak|tak|bukan|belum)\s*$"',
     r'_NEGATED_LINK = re.compile(r"\b(?:tidak|tak|bukan|belum)\b"'),
    ("qa18_source_attribution_counted", CC,
     "side = _SIDE_END.split(_ATTRIBUTION.sub(\" \", text))[-1 if from_end else 0].strip()",
     "side = _SIDE_END.split(text)[-1 if from_end else 0].strip()"),
    ("qa18_events_anywhere_in_sentence", CC, "found = sum(_meets(r, on_side) for r in events)",
     "found = sum(_meets(r, in_sentence) for r in events)"),
    # source_check end points (SYS-186)
    ("qa18_end_part_dropped", SC, 'key = {("part", g["part"])} if g["part"] else set()', "key = set()"),
    ("qa18_semester_is_kuartal", SC, 'key.add((g["period"].replace("triwulan", "kuartal"), _ORDINAL_OF[g["ordinal"]]))',
     'key.add(("kuartal", _ORDINAL_OF[g["ordinal"]]))'),
    ("qa18_ordinal_ii_is_1", SC, '_ORDINAL_OF = {"i": 1, "ii": 2,', '_ORDINAL_OF = {"i": 1, "ii": 1,'),
    ("qa18_month_year_ignored", SC, 'year = g["month_year"] or g["period_year"]', 'year = g["period_year"]'),
    # source_check bare ends (SYS-178)
    ("qa18_bare_end_mendatang", SC, "(?:ini|lalu|depan|mendatang|kemarin|sebelumnya|berikutnya|ke\\s+depan)",
     "(?:ini|lalu|depan|kemarin|sebelumnya|berikutnya|ke\\s+depan)"),
    ("qa18_bare_end_ke_depan", SC, "(?:ini|lalu|depan|mendatang|kemarin|sebelumnya|berikutnya|ke\\s+depan)",
     "(?:ini|lalu|depan|mendatang|kemarin|sebelumnya|berikutnya)"),
    # story_arc schedules (SYS-177)
    ("qa18_cue_one_word", SA, "CUE_WORDS = 4", "CUE_WORDS = 1"),
    ("qa18_judul_not_present", SA, 'PRESENT_FIELDS = ("judul", "hari_ini", "sekilas")',
     'PRESENT_FIELDS = ("hari_ini", "sekilas")'),
    ("qa18_sekilas_not_present", SA, 'PRESENT_FIELDS = ("judul", "hari_ini", "sekilas")',
     'PRESENT_FIELDS = ("judul", "hari_ini")'),
]


def main(root: str) -> int:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", POSTGRES_DB_PORT="1", TELEGRAM_BOT_TOKEN="")
    survived = 0
    for name, path, old, new in M:
        p = os.path.join(root, path)
        src = open(p, encoding="utf-8", newline="").read()
        if src.count(old) != 1:
            print(f"{name:36s} NOT FOUND ({src.count(old)})")
            survived += 1
            continue
        open(p, "w", encoding="utf-8", newline="").write(src.replace(old, new))
        try:
            r = subprocess.run([PY, "-m", "pytest", *TESTS, "-q", "-x", "-p", "no:cacheprovider"], cwd=root, env=env,
                               capture_output=True, text=True, timeout=900)
            last = (r.stdout.strip().splitlines() or [""])[-1]
            verdict = "KILLED" if r.returncode == 1 else "SURVIVED" if r.returncode == 0 else f"ERROR rc={r.returncode}"
            survived += verdict != "KILLED"
            print(f"{name:36s} {verdict:9s} {last}")
        finally:
            open(p, "w", encoding="utf-8", newline="").write(src)
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
