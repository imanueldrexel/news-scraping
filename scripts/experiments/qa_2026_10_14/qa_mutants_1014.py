"""QA 2026-10-14: QA's own mutants for SYS-154..160 -- ones the dev's registry does not list.

Run in a scratch copy, never the live tree (the 12:00 newsletter imports it):

    git -c core.autocrlf=false archive HEAD newscrawler scripts tests __main__.py pytest.ini | tar -x -C <dir>
    venv\\Scripts\\python.exe scripts\\experiments\\qa_2026_10_14\\qa_mutants_1014.py <dir> [NAME ...]

Each mutant is applied in <dir>, the dev's suites for this batch run there (QA_MUTANT_TESTS
overrides), and the file is restored from memory. KILLED = a test went red.
"""
import os
import subprocess
import sys
import tempfile

PY = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                  "venv", "Scripts", "python.exe")
SA, SC, AS, RP = ("newscrawler/core/story_arc.py", "newscrawler/core/source_check.py", "newscrawler/core/arc_style.py",
                  "scripts/experiments/replay_story_arcs.py")
M = [
    # SYS-156
    ("qa_max_dates_3", SA, "MAX_LATAR_DATES = 2", "MAX_LATAR_DATES = 3"),
    ("qa_max_openings_2", SA, "MAX_DATE_OPENINGS = 1\n", "MAX_DATE_OPENINGS = 2\n"),
    ("qa_opening_case_sensitive", AS, "return match.group(0).lower() if match", "return match.group(0) if match"),
    ("qa_style_skipped_on_retry", SA, "    style = chronicle(latar, judul, hari_ini, bool(chosen))",
     "    style = [] if lenient else chronicle(latar, judul, hari_ini, bool(chosen))"),
    ("qa_number_before_style", SA, 'reason = ("style" if style else "number" if numbers else',
     'reason = ("number" if numbers else "style" if style else'),
    ("qa_length_drops_style", SA,
     "raise Rejected(\"length\", \"; \".join(problems + ([f\"{'; '.join(style)} -- {STYLE_ASK}\"] if style else [])))",
     "raise Rejected(\"length\", \"; \".join(problems))"),
    ("qa_style_detail_no_ask", SA, "    problems = ([f\"{'; '.join(style)} -- {STYLE_ASK}\"] if style else [])",
     "    problems = ([f\"{'; '.join(style)}\"] if style else [])"),
    # SYS-159
    ("qa_tie_ignores_date_opening", AS, "return not opens_on_date(first) and bool(", "return bool("),
    ("qa_tie_exact_words", AS, "bool(_families(today) & _families(story_words.content_words(first)))",
     "bool(set(today) & set(story_words.content_words(first)))"),
    ("qa_tie_asked_without_alur", SA, "if has_alur and not arc_style.tied_to_today", "if not arc_style.tied_to_today"),
    ("qa_nasal_not_restored", AS, "out.add(_NASAL[prefix] + rest)", "pass"),
    ("qa_min_stem_3", AS, "MIN_STEM = 4", "MIN_STEM = 3"),
    # SYS-157
    ("qa_pertengahan_to_25", SC, '"pertengahan": (11, 20)', '"pertengahan": (11, 25)'),
    ("qa_dua_pekan_lalu_any", SC, "_days_ago(14, slack=3)", "_days_ago(14, slack=10)"),
    ("qa_kemarin_two_days", SC, '(r"kemarin", lambda m, today: (today - timedelta(days=1),',
     '(r"kemarin", lambda m, today: (today - timedelta(days=2),'),
    ("qa_n_hari_no_slack", SC, "slack=1)(m, today)", "slack=0)(m, today)"),
    ("qa_last_days_include_today", SC,
     "return lambda m, today: (today - timedelta(days=n), today - timedelta(days=1))",
     "return lambda m, today: (today - timedelta(days=n), today)"),
    ("qa_bulan_lalu_this_month", SC, '(r"bulan\\s+lalu", lambda m, today: _whole_month(*_previous_month(today)))',
     '(r"bulan\\s+lalu", lambda m, today: _whole_month(today.month, today.year))'),
    ("qa_stated_verbatim_ignored", SA, ' and " ".join(phrase.lower().split()) not in stated]', "]"),
    ("qa_source_dates_dont_back", SA, "            | {resolve(d, m, digest_date) for d, m in dates_in(source)}) - {None}",
     "            ) - {None}"),
    ("qa_relative_name_awal_15", SC, 'part = "awal" if day.day <= 10', 'part = "awal" if day.day <= 15'),
    ("qa_timeline_text_no_phrase", SA, " ({relative_name(d, digest_date)}) · ", " · "),
    ("qa_relative_dates_not_blanked", SC, "    text = without_dates(text)\n    matches", "    matches"),
    # SYS-158
    ("qa_kesekian_is_2", SC, '(m.group(0), 3, "kesekian")', '(m.group(0), 2, "kesekian")'),
    ("qa_series_unread", SC, "            for m in _SERIES.finditer(text)]", "            for m in []]"),
    ("qa_kalinya_not_normalised", SC, '.replace("kalinya", "kali")', '.replace("kalinya", "kalinya")'),
    ("qa_ke_n_unread", SC, "        elif m.group(\"n\"):\n            key = f\"ke-{n}\"", "        elif False:\n            pass"),
    # SYS-160
    ("qa_metric_ge2_dates", RP, '"with_3_dates_or_more": sum(d >= 3', '"with_3_dates_or_more": sum(d >= 2'),
    ("qa_metric_no_non_events", RP, '"non_events": sum(len(arc_style.non_events(r["back"])) for r in backs)',
     '"non_events": 0'),
    ("qa_date_led_opening_only", AS, "    return opens_on_date(sentence) or any(", "    return opens_on_date(sentence) and any("),
    ("qa_non_events_disebut_only", AS, r'NON_EVENTS = re.compile(r"\b(?:dibahas|disebut|dikabarkan|ditanggapi)\b"',
     r'NON_EVENTS = re.compile(r"\b(?:disebut)\b"'),
    # SYS-154 / 155
    ("qa_prompt_dated_fact_back", SA, '"- Setiap fakta dari LINI MASA harus berasal dari cuplikannya.\\n"',
     '"- Setiap fakta dari LINI MASA ditulis dengan tanggalnya, mis. \\"Pada 24/9, ...\\".\\n"'),
    ("qa_example_chronicle", SA, '"  \\"latar\\": \\"Ini pekan kedua beruntun IHSG ditutup merah. Pekan sebelumnya',
     '"  \\"latar\\": \\"Pada 27/9 IHSG ditutup merah. Pada 30/9'),
    ("qa_rule2_dropped", SA, '"    2. Pilih paling banyak dua titik balik,', '"    2. Pilih titik balik,'),
]

TESTS = os.environ.get("QA_MUTANT_TESTS", "tests/unit/test_story_arc.py tests/unit/test_source_check.py "
                       "tests/unit/test_arc_style.py tests/unit/test_replay_story_arcs.py "
                       "tests/unit/test_newsletter_arcs.py").split()

if __name__ == "__main__":
    root, only = sys.argv[1], sys.argv[2:]
    scratch = tempfile.mkdtemp(prefix="qa_mut1014_")
    env = dict(os.environ, VECTOR_DB_NAME_L1=os.path.join(scratch, "NOPE_L1"),
               VECTOR_DB_NAME_L2=os.path.join(scratch, "NOPE_L2"), POSTGRES_DB_PORT="1", TELEGRAM_BOT_TOKEN="",
               PYTHONDONTWRITEBYTECODE="1")
    for name, path, old, new in M:
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
