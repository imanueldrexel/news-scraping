"""QA 2026-10-16 (evening): mutation run for SYS-167..170, DBT-79 and DBT-80 (tracker #336).

Three sets, all applied in a scratch copy, never the live tree (the 12:00 newsletter imports it):
- `arc`: the dev's registry entries for this batch (`sys167_*` .. `sys170_*`, DBT-79's four `qa16_*`, the two
  retargeted `sys165_synonyms_not_keyed` / `sys166_future_not_scheduled`), run by the four arc suites;
- `dbt80`: the 25 entries DBT-80 retargeted, run by the whole of tests/unit (`-x`: a kill stops at the first red);
- `qa`: QA's own mutants (`qa16e_*`) on behaviour the tickets or the dev's comments name that the registry does
  not mutate, run by the four arc suites.

    git -c core.autocrlf=false archive HEAD newscrawler scripts tests __main__.py pytest.ini | tar -x -C <dir>
    venv\\Scripts\\python.exe scripts\\experiments\\qa_2026_10_16_eve\\qa_mutants_1016_eve.py <dir> arc|dbt80|qa|tg [NAME ...]

QA_TESTS overrides the tests (e.g. QA's own file). KILLED = a test went red. The file is restored after each.
"""
import ast
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
    # SYS-169: "on every prose field"
    ("qa16e_future_latar_unchecked", SA, "for phrase in unstated_future_times(value, stated_today)]",
     'for phrase in (unstated_future_times(value, stated_today) if key in ("agenda", "hari_ini") else [])]'),
    ("qa16e_future_agenda_only", SA, "for phrase in unstated_future_times(value, stated_today)]",
     'for phrase in (unstated_future_times(value, stated_today) if key == "agenda" else [])]'),
    ("qa16e_prompt_agenda_rule_removed", SA,
     '"  Jangan menebak. Tulis waktunya seperti tertulis di artikel HARI INI (\\"Kamis (15/10)\\", \\"pekan\\n"\n'
     '    "  depan\\"); jangan mengubah tanggal menjadi \\"besok\\" atau \\"pekan ini\\".\\n"',
     '"  Jangan menebak.\\n"'),
    # SYS-168: keying
    ("qa16e_future_case_kept", SC, 'key = " ".join(phrase.lower().split())', 'key = " ".join(phrase.split())'),
    ("qa16e_no_ini_week", SC, r"(?:pekan|minggu)\s+(?:depan|mendatang|ini)", r"(?:pekan|minggu)\s+(?:depan|mendatang)"),
    ("qa16e_akhir_week_not_keyed", SC, r"lusa|(?:akhir\s+)?(?:pekan|minggu)\s+(?:depan", r"lusa|(?:pekan|minggu)\s+(?:depan"),
    ("qa16e_future_case_sensitive", SC, 'r"|(?:akhir\\s+)?(?:bulan|tahun)\\s+(?:depan|mendatang)|akhir\\s+(?:bulan|tahun)\\s+ini)\\b",\n'
     '                     re.IGNORECASE)',
     'r"|(?:akhir\\s+)?(?:bulan|tahun)\\s+(?:depan|mendatang)|akhir\\s+(?:bulan|tahun)\\s+ini)\\b")'),
    # SYS-170: the date lookahead, half at a time
    ("qa16e_slash_date_is_a_figure", SC, r"(?!\s*/|\s+(?:{_MONTH_NAME})\b)", r"(?!\s+(?:{_MONTH_NAME})\b)"),
    ("qa16e_month_date_is_a_figure", SC, r"(?!\s*/|\s+(?:{_MONTH_NAME})\b)", r"(?!\s*/)"),
    ("qa16e_change_no_posisi", SC, r'ke\s+(?:angka|level|posisi)"', r'ke\s+(?:angka|level)"'),
    # SYS-167: the weekday's day, and awal/pertengahan
    ("qa16e_weekday_off_by_one", SC, 'timedelta(days=copy.DAYS.index(m.group("day").capitalize()))\n    return day, day',
     'timedelta(days=copy.DAYS.index(m.group("day").capitalize()) + 1)\n    return day, day'),
    ("qa16e_only_akhir_week", SC, r'(r"(?:awal|pertengahan|akhir)\s+(?:pekan|(?-i:minggu))\s+lalu", _last_week)',
     r'(r"(?:akhir)\s+(?:pekan|(?-i:minggu))\s+lalu", _last_week)'),
]

# DBT-80 retargeted OPS-33's redaction mutants to the alert path `_post`; the dev notes two more copies of the
# block (`_post_document`, `_post_html`). Do the suites guard the redaction there? Run by the whole of tests/unit.
TG = "scripts/notify_telegram.py"
_DOC = '                timeout=DOCUMENT_TIMEOUT_S,\n            )\n    except Exception as e:  # noqa: BLE001\n'
_HTML = '                  "disable_web_page_preview": True},\n            timeout=10,\n        )\n    except Exception as e:  # noqa: BLE001\n'
_EXC, _EXC_RAW = '        return False, True, f"{type(e).__name__}: {redact(e)}"\n', '        return False, True, f"{type(e).__name__}: {e}"\n'
_TAIL = ('    if response.status_code == 200:\n        return True, False, ""\n'
         '    retryable = response.status_code == 429 or response.status_code >= 500\n'
         '    return False, retryable, f"Telegram API returned {response.status_code}: ')
TGM = [
    ("qa16e_document_exception_not_redacted", TG, _DOC + _EXC, _DOC + _EXC_RAW),
    ("qa16e_document_body_not_redacted", TG, _DOC + _EXC + _TAIL + '{redact(response.text[:500])}"',
     _DOC + _EXC + _TAIL + '{response.text[:500]}"'),
    ("qa16e_html_exception_not_redacted", TG, _HTML + _EXC, _HTML + _EXC_RAW),
    ("qa16e_html_body_not_redacted", TG, _HTML + _EXC + _TAIL + '{redact(response.text[:500])}"',
     _HTML + _EXC + _TAIL + '{response.text[:500]}"'),
]

DBT80 = ["sys54_failed_fetches_not_candidates", "ops32_no_retry", "ops32_refusal_queued_forever",
         "ops33_exception_not_redacted", "ops33_body_not_redacted", "dbt02_not_wired", "sys68_service_drops_note",
         "dbt74_l1_not_passed", "ops35_all_branches_check_dropped", "ops35_note_not_logged",
         "sys68_success_keeps_error_streak", "sys68_path_loses_note", "ops20_call_not_counted",
         "sys67_prompt_focus_removed", "sys88_page_title_escaped", "sys90_int_not_converted", "sys90_any_int_is_a_date",
         "sys98_provider_not_rag_setting", "qa1007_peak_price_ignored", "sys103_no_max_terms", "sys104_cue_from_thread",
         "sys104_fallback_always_thread", "sys104_no_length_cap", "sys138_thin_week_not_filled",
         "sys138_window_always_whole"]
ARC_PREFIXES = ("sys167_", "sys168_", "sys169_", "sys170_", "qa16_future_latar_not_told", "qa16_no_lusa",
                "qa16_no_bulan_tahun_depan", "qa16_future_spacing_kept", "sys165_synonyms_not_keyed",
                "sys166_future_not_scheduled")


def registry() -> list:
    import warnings
    warnings.simplefilter("ignore")
    tree = ast.parse(open(os.path.join(REPO, "scripts", "experiments", "qa_mutation_runner.py"), encoding="utf-8").read())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "M" for t in n.targets))
    return ast.literal_eval(node.value)


if __name__ == "__main__":
    root, which, only = sys.argv[1], sys.argv[2], sys.argv[3:]
    M = registry()
    if which == "arc":
        mutants, tests = [m for m in M if m[0].startswith(ARC_PREFIXES)], ARC_TESTS
    elif which == "dbt80":
        mutants, tests = [m for m in M if m[0] in DBT80], ["tests/unit", "-x"]
        assert len(mutants) == len(DBT80), sorted(set(DBT80) - {m[0] for m in mutants})
    elif which == "tg":
        mutants, tests = TGM, ["tests/unit", "-x"]
    else:
        mutants, tests = QA, ARC_TESTS
    tests = os.environ["QA_TESTS"].split() if os.environ.get("QA_TESTS") else tests
    scratch = tempfile.mkdtemp(prefix="qa_mut1016e_")
    env = dict(os.environ, VECTOR_DB_NAME_L1=os.path.join(scratch, "NOPE_L1"),
               VECTOR_DB_NAME_L2=os.path.join(scratch, "NOPE_L2"), POSTGRES_DB_PORT="1", TELEGRAM_BOT_TOKEN="",
               PYTHONDONTWRITEBYTECODE="1")
    tally = {}
    for name, path, old, new in mutants:
        if only and name not in only:
            continue
        p = os.path.join(root, path)
        original = open(p, "rb").read()
        src = original.decode("utf-8")
        o, n = (old, new) if src.count(old) == 1 else (old.replace("\n", "\r\n"), new.replace("\n", "\r\n"))
        if src.count(o) != 1:
            print(f"{name}: PATTERN NOT FOUND ({src.count(o)})", flush=True)
            tally["NOT FOUND"] = tally.get("NOT FOUND", 0) + 1
            continue
        try:
            open(p, "wb").write(src.replace(o, n).encode("utf-8"))
            r = subprocess.run([PY, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"], cwd=root, env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            verdict = "SURVIVED" if r.returncode == 0 else "KILLED"
            tail = [line for line in r.stdout.splitlines() if " passed" in line or " failed" in line][-1:]
            print(f"{name}: {verdict} {tail}", flush=True)
            tally[verdict] = tally.get(verdict, 0) + 1
        finally:
            open(p, "wb").write(original)
    print(tally)
