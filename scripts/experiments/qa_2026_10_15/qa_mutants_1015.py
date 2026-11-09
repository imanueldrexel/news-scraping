"""QA 2026-10-15: mutation run for the rework of the arc guards (SYS-157/158 rework, SYS-162/163/164, DBT-77).

Two sets, both applied in a scratch copy, never the live tree (the 12:00 newsletter imports it):
- the dev's registry entries for this batch (`sys156..164_*`, `sys157r_*`, `sys158r_*`,
  `qa_metric_ge2_dates`), read from scripts/experiments/qa_mutation_runner.py without running it;
- QA's own mutants (`qa15_*`), on behaviour the tickets name that the registry does not mutate.

    git -c core.autocrlf=false archive HEAD newscrawler scripts tests __main__.py pytest.ini | tar -x -C <dir>
    venv\\Scripts\\python.exe scripts\\experiments\\qa_2026_10_15\\qa_mutants_1015.py <dir> [NAME ...]

QA_MUTANT_TESTS overrides the tests each mutant runs (default: the dev's four arc suites +
test_newsletter_arcs.py). KILLED = a test went red. The file is restored from memory after each.
"""
import ast
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PY = os.path.join(REPO, "venv", "Scripts", "python.exe")
SA, SC, AS = "newscrawler/core/story_arc.py", "newscrawler/core/source_check.py", "newscrawler/core/arc_style.py"

QA = [
    # SYS-162
    ("qa15_stated_today_all_articles", SA, 'stated_today = "\\n\\n".join(shown_texts[i] for i in terkait)',
     'stated_today = "\\n\\n".join(shown_texts)'),
    # SYS-163
    ("qa15_agenda_told_latar_only", SA, 'told = f"{latar} {hari_ini}"', "told = latar"),
    ("qa15_agenda_share_strict", SA, ">= AGENDA_REPEAT_SHARE * len(words)", "> AGENDA_REPEAT_SHARE * len(words)"),
    ("qa15_dropped_agenda_still_checked", SA, 'agenda, agenda_dropped = "", True', "agenda_dropped = True"),
    # SYS-164
    ("qa15_anchor_cap_ge", SA, "if len(anchors) > MAX_LATAR_ANCHORS:", "if len(anchors) >= MAX_LATAR_ANCHORS:"),
    ("qa15_sejak_anywhere_before", AS, "if not _SEJAK.search(text[:pos])]",
     'if not re.search(r"\\bsejak\\b", text[:pos], re.IGNORECASE)]'),
    ("qa15_anchors_relative_only", AS,
     "found = [(pos, written) for pos, _, _, written in date_mentions(text)] + _relative_anchors(text)",
     "found = _relative_anchors(text)"),
    ("qa15_time_led_opening_only", AS, "return date_led(sentence) or opens_on_time(sentence)",
     "return opens_on_time(sentence)"),
    # SYS-158 rework
    ("qa15_record_day_dropped", SC, 'parts = [m.group("day"), m.group("part"), m.group("month"), m.group("year")]',
     'parts = [m.group("part"), m.group("month"), m.group("year")]'),
    ("qa15_record_part_dropped", SC, 'parts = [m.group("day"), m.group("part"), m.group("month"), m.group("year")]',
     'parts = [m.group("day"), m.group("month"), m.group("year")]'),
    ("qa15_record_ini_kept", SC, 'None if (which or "").lower() == "ini" else which', "which"),
    ("qa15_dm_year_dropped", SC, 'parts = [m.group("dm"), m.group("dmyear")]', 'parts = [m.group("dm")]'),
    ("qa15_ber_not_a_verb", SC, '_VERB = re.compile(r"(?:me|di|ber)[a-z]{3,}")', '_VERB = re.compile(r"(?:me|di)[a-z]{3,}")'),
    # SYS-157 rework
    ("qa15_digit_count_unread", SC, "n = _COUNT.get(word) or (int(word) if word.isdigit() else None)",
     "n = _COUNT.get(word)"),
    ("qa15_weeks_slack_1", SC, "_days_back(today, 7 * n, 2 if n == 1 else 3)", "_days_back(today, 7 * n, 2 if n == 1 else 1)"),
    ("qa15_minggu_read_as_days", SC, 'return _days_back(today, n, 1) if unit == "hari" else',
     'return _days_back(today, n, 1) if unit in ("hari", "minggu") else'),
]

DEV_PREFIXES = ("sys156", "sys157", "sys158", "sys159", "sys160", "sys161", "sys162", "sys163", "sys164",
                "qa_metric_ge2_dates")


def dev_registry() -> list:
    """The dev's mutants for this batch, from qa_mutation_runner.py's `M` (parsed, not executed)."""
    tree = ast.parse(open(os.path.join(REPO, "scripts", "experiments", "qa_mutation_runner.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "M" for t in node.targets):
            return [m for m in ast.literal_eval(node.value) if m[0].startswith(DEV_PREFIXES)]
    raise SystemExit("M not found in qa_mutation_runner.py")


TESTS = os.environ.get("QA_MUTANT_TESTS", "tests/unit/test_story_arc.py tests/unit/test_source_check.py "
                       "tests/unit/test_arc_style.py tests/unit/test_replay_story_arcs.py "
                       "tests/unit/test_newsletter_arcs.py").split()

if __name__ == "__main__":
    root, only = sys.argv[1], sys.argv[2:]
    scratch = tempfile.mkdtemp(prefix="qa_mut1015_")
    env = dict(os.environ, VECTOR_DB_NAME_L1=os.path.join(scratch, "NOPE_L1"),
               VECTOR_DB_NAME_L2=os.path.join(scratch, "NOPE_L2"), POSTGRES_DB_PORT="1", TELEGRAM_BOT_TOKEN="",
               PYTHONDONTWRITEBYTECODE="1")
    mutants = ([] if os.environ.get("QA_ONLY_OWN") else dev_registry()) + QA
    for name, path, old, new in mutants:
        if only and name not in only:
            continue
        p = os.path.join(root, path)
        original = open(p, "rb").read()
        src = original.decode("utf-8")
        o, n = (old, new) if src.count(old) == 1 else (old.replace("\n", "\r\n"), new.replace("\n", "\r\n"))
        if src.count(o) != 1:
            print(f"{name}: PATTERN NOT FOUND ({src.count(o)})", flush=True)
            continue
        open(p, "wb").write(src.replace(o, n).encode("utf-8"))
        try:
            r = subprocess.run([PY, "-m", "pytest", *TESTS, "-q", "-x", "-p", "no:cacheprovider", "--no-header",
                                "-rN", "--tb=no", "-W", "ignore"], capture_output=True, text=True, env=env, cwd=root,
                               timeout=600)
            tail = [line for line in r.stdout.splitlines() if line.strip()][-1:]
            verdict = "KILLED" if r.returncode == 1 else "SURVIVED" if r.returncode == 0 else f"RC{r.returncode}"
            print(f"{name}: {verdict} :: {' | '.join(tail)[:160]}", flush=True)
        finally:
            open(p, "wb").write(original)
