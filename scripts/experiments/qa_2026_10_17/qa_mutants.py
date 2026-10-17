import os, subprocess, sys
root = sys.argv[1]
PY = r"C:\Users\bdrex\Documents\Personal\news-scraping 2\venv\Scripts\python.exe"
TESTS = "tests/unit/test_story_arc.py tests/unit/test_source_check.py tests/unit/test_arc_style.py tests/unit/test_replay_story_arcs.py tests/unit/test_causal_check.py".split()
CC, SA = "newscrawler/core/causal_check.py", "newscrawler/core/story_arc.py"
M = [
 ("qa_no_imbas", CC, "imbas(?:nya)?|", ""),
 ("qa_no_lantaran", CC, "lantaran|", ""),
 ("qa_no_sebab_word", CC, "disebabkan|menyebabkan|sebab)", "disebabkan|menyebabkan)"),
 ("qa_min_half_words_1", CC, "MIN_HALF_WORDS = 2 ", "MIN_HALF_WORDS = 1 "),
 ("qa_three_sentences", CC, "MAX_QUOTE_SENTENCES = 2 ", "MAX_QUOTE_SENTENCES = 3 "),
 ("qa_agenda_unchecked", SA, '("agenda", agenda), ("sekilas", sekilas)], sebab', '("sekilas", sekilas)], sebab'),
 ("qa_judul_unchecked", SA, 'causal_check.unbacked_causes([("judul", judul), ("hari_ini"', 'causal_check.unbacked_causes([("hari_ini"'),
 ("qa_alur_not_quotable", SA, ", **{i: item_source(t) for i, t in chosen.items()}}", "}"),
 ("qa_bool_artikel_ok", SA, " or isinstance(e.get(\"artikel\"), bool)", ""),
 ("qa_sebab_after_subject", SA, '"sebab" if causes\n                  else "subject" if strays', '"subject" if strays else "sebab" if causes'),
 ("qa_threshold_055", CC, "MIN_HALF_OVERLAP = 0.6", "MIN_HALF_OVERLAP = 0.55"),
 ("qa_threshold_07", CC, "MIN_HALF_OVERLAP = 0.6", "MIN_HALF_OVERLAP = 0.7"),
 ("qa_nya_kept", CC, 'if w.endswith("nya") and len(w) > 6:', 'if False:'),
 ("qa_no_prefix_strip", CC, "    for prefix in _PREFIXES:\n", "    for prefix in ():\n"),
 ("qa_entry_problems_always", CC, "return problems + entry_problems if problems else []", "return problems + entry_problems"),
 ("qa_any_quote_fine_if_one_good", CC, "if not any(supports(q, span) for q in quotes):", "if not quotes:"),
 ("qa_boundary_no_comma", CC, '_BOUNDARY = re.compile(r",(?!\d)|', '_BOUNDARY = re.compile(r"'),
]
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", POSTGRES_DB_PORT="1", TELEGRAM_BOT_TOKEN="")
for name, path, old, new in M:
    p = os.path.join(root, path); src = open(p, encoding="utf-8", newline="").read()
    if src.count(old) != 1:
        print(name, "NOT FOUND", src.count(old)); continue
    open(p, "w", encoding="utf-8", newline="").write(src.replace(old, new))
    try:
        r = subprocess.run([PY, "-m", "pytest", *TESTS, "-q", "-x", "-p", "no:cacheprovider"], cwd=root, env=env, capture_output=True, text=True)
        print(name, "KILLED" if r.returncode else "SURVIVED", r.stdout.strip().splitlines()[-1])
    finally:
        open(p, "w", encoding="utf-8", newline="").write(src)
