"""QA 2026-10-16: mutation run for SYS-164 (rework), SYS-165, SYS-166 and DBT-78 (tracker #336).

Two sets, both applied in a scratch copy, never the live tree (the 12:00 newsletter imports it):
- the dev's registry entries for this batch (`sys164r_*`, `sys165_*`, `sys166_*`, the retargeted
  `sys163_no_shared_date_needed` / `sys164_sejak_counted`, and DBT-78's five `qa15_*`), read from
  scripts/experiments/qa_mutation_runner.py without running it;
- QA's own mutants (`qa16_*`), on behaviour the tickets or the dev's judgement calls name that the
  registry does not mutate.

    git -c core.autocrlf=false archive HEAD newscrawler scripts tests __main__.py pytest.ini | tar -x -C <dir>
    venv\\Scripts\\python.exe scripts\\experiments\\qa_2026_10_16\\qa_mutants_1016.py <dir> [NAME ...]

QA_MUTANT_TESTS overrides the tests each mutant runs (default: the four suites DBT-78 names).
QA_ONLY_OWN=1 runs only `qa16_*`. KILLED = a test went red. The file is restored after each.
"""
import ast
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PY = os.path.join(REPO, "venv", "Scripts", "python.exe")
SA, AS = "newscrawler/core/story_arc.py", "newscrawler/core/arc_style.py"
FUT = r'_FUTURE = re.compile(r"\b(?:besok|lusa|(?:akhir\s+)?(?:pekan|minggu)\s+(?:depan|ini)|(?:bulan|tahun)\s+depan)\b",'

QA = [
    # SYS-165: keying and the dev's two judgement calls
    ("qa16_future_case_kept", SA, '" ".join(m.group(0).lower().split())', '" ".join(m.group(0).split())'),
    ("qa16_future_spacing_kept", SA, '" ".join(m.group(0).lower().split())', "m.group(0).lower()"),
    ("qa16_akhir_not_keyed", SA, FUT,
     FUT.replace(r"(?:akhir\s+)?(?:pekan|minggu)", r"(?:pekan|minggu)")),
    ("qa16_future_latar_not_told", SA, "or future_times(agenda) & future_times(told))",
     "or future_times(agenda) & future_times(hari_ini))"),
    # SYS-166: the times moved out of _SCHEDULED into _FUTURE
    ("qa16_no_lusa", SA, FUT, FUT.replace("besok|lusa|", "besok|")),
    ("qa16_no_bulan_tahun_depan", SA, FUT, FUT.replace(r"|(?:bulan|tahun)\s+depan", "")),
    ("qa16_no_ini", SA, FUT, FUT.replace(r"(?:depan|ini)", "depan")),
    # SYS-164 rework: the frame on its own phrase only
    ("qa16_sejak_opens_anywhere", AS, '_SEJAK_OPENS = re.compile(r"sejak\\b", re.IGNORECASE)',
     '_SEJAK_OPENS = re.compile(r".*", re.IGNORECASE)'),
    ("qa16_sejak_opens_case", AS, '_SEJAK_OPENS = re.compile(r"sejak\\b", re.IGNORECASE)',
     '_SEJAK_OPENS = re.compile(r"sejak\\b")'),
]

DEV_PREFIXES = ("sys164r_", "sys165_", "sys166_", "sys163_no_shared_date_needed", "sys164_sejak_counted",
                "qa15_stated_today_all_articles", "qa15_agenda_told_latar_only", "qa15_agenda_share_strict",
                "qa15_time_led_opening_only", "qa15_dm_year_dropped")


def dev_registry() -> list:
    """The dev's mutants for this batch, from qa_mutation_runner.py's `M` (parsed, not executed)."""
    tree = ast.parse(open(os.path.join(REPO, "scripts", "experiments", "qa_mutation_runner.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "M" for t in node.targets):
            return [m for m in ast.literal_eval(node.value) if m[0].startswith(DEV_PREFIXES)]
    raise SystemExit("M not found in qa_mutation_runner.py")


TESTS = os.environ.get("QA_MUTANT_TESTS", "tests/unit/test_story_arc.py tests/unit/test_source_check.py "
                       "tests/unit/test_arc_style.py tests/unit/test_replay_story_arcs.py").split()

if __name__ == "__main__":
    root, only = sys.argv[1], sys.argv[2:]
    scratch = tempfile.mkdtemp(prefix="qa_mut1016_")
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
