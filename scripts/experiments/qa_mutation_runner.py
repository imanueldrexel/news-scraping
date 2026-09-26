"""QA mutation runner (2026-09-26 audit of HANDOFF_2026-09-26_evening.md).

Applies one textual mutant at a time to the working tree, runs tests/unit with
`-x`, prints KILLED / SURVIVED, and restores the file with `git checkout --`.
Run it on a CLEAN tree only (it restores by checkout, so any uncommitted edit
to a mutated file is lost), and do not import repo code from another process
while it runs -- that process would load the mutant.

Safety: a surviving mutant runs real code paths. The child env points
VECTOR_DB_NAME_L1/L2 at a nonexistent scratch path, POSTGRES_DB_PORT at 1 and
blanks TELEGRAM_BOT_TOKEN, so a survivor cannot touch NEWS_L1/L2, the DB or
Telegram (EXPERIMENTS.md: a mutant once copied the live indexes to backups/).
Scripts that hard-code BACKUP_DIR are not covered by this -- check `backups/`
before and after.

    venv\Scripts\python.exe scripts\experiments\qa_mutation_runner.py            # all mutants
    venv\Scripts\python.exe scripts\experiments\qa_mutation_runner.py NAME ...   # a subset

A pattern is applied only when it occurs exactly once (some files have mixed
line endings; the CRLF form is tried when the LF form is not found).
"""
import os, subprocess, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile
SCRATCH = tempfile.mkdtemp(prefix="qa_mutants_")
M = [
 ("starvation_order_by_name", "scripts/run_scheduled_crawl.py",
  "    return sorted(sources, key=key)\n\n\ndef projected_seconds", "    return sorted(sources)\n\n\ndef projected_seconds"),
 ("timeout_for_no_max", "scripts/run_scheduled_crawl.py",
  "return max(default, SOURCE_TIMEOUTS.get(website, 0))", "return SOURCE_TIMEOUTS.get(website, default)"),
 ("timeout_for_ignore_table", "scripts/run_scheduled_crawl.py",
  "return max(default, SOURCE_TIMEOUTS.get(website, 0))", "return default"),
 ("store_note_no_exemption", "scripts/run_scheduled_crawl.py",
  'and not (k == "chunks_not_in_faiss" and counts.get(k, 0) <= pending_sitemaps)]', ']'),
 ("store_note_exempt_all", "scripts/run_scheduled_crawl.py",
  'and not (k == "chunks_not_in_faiss" and counts.get(k, 0) <= pending_sitemaps)]', 'and not (k == "chunks_not_in_faiss")]'),
 ("sample_order_identity", "scripts/check_crawlers.py",
  "    return settled + rest\n", "    return list(articles or [])\n"),
 ("abandon_reason_always_killed", "scripts/run_scheduled_crawl.py",
  '    if status == "timeout":\n        return "killed by', '    if True:\n        return "killed by'),
 ("cascade_min_0", "newscrawler/core/utils/utils.py",
  "CASCADE_MIN_SUFFIX_CHARS = 20", "CASCADE_MIN_SUFFIX_CHARS = 0"),
 ("cascade_min_200", "newscrawler/core/utils/utils.py",
  "CASCADE_MIN_SUFFIX_CHARS = 20", "CASCADE_MIN_SUFFIX_CHARS = 200"),
 ("is_cascaded_ge1", "newscrawler/core/utils/utils.py",
  "return cascaded_pairs(paragraphs) >= 2", "return cascaded_pairs(paragraphs) >= 1"),
 ("is_cascaded_ge3", "newscrawler/core/utils/utils.py",
  "return cascaded_pairs(paragraphs) >= 2", "return cascaded_pairs(paragraphs) >= 3"),
 ("inews_soft_leaves_empty", "newscrawler/core/importance_filter.py",
  '    "INEWS": frozenset({\n        "inews-tv/talkshow",\n    }),', '    "INEWS": frozenset(),'),
 ("url_category_sql_never", "scripts/check_store_consistency.py",
  "WHERE category LIKE 'http%'\")).scalar()", "WHERE false\")).scalar()"),
 ("url_category_not_passed", "scripts/check_store_consistency.py",
  "                              url_category_rows=url_categories)", "                              url_category_rows=0)"),
 ("release_unconditional", "newscrawler/tools/run_lock.py",
  "        if mine:\n            try:\n                os.remove(self.path)", "        if True:\n            try:\n                os.remove(self.path)"),
 ("own_paragraph_is_get_text", "newscrawler/core/utils/utils.py",
  "    parts = []\n    for string in p_tag.strings:", "    return p_tag.get_text(separator).strip()\n    parts = []\n    for string in p_tag.strings:"),
 ("newspaper_parse_unlocked", "newscrawler/infrastructure/datasource/scrapers/crawler.py",
  "            with LXML_PARSE_LOCK:  # SYS-52: newspaper parses with lxml", "            if True:  # SYS-52: newspaper parses with lxml"),
 ("inews_branch_name_returns_url", "newscrawler/infrastructure/datasource/scrapers/inews/inews_crawler.py",
  "        return match.group(1) if match else None", "        return match.group(1) if match else link"),
 ("worker_not_allowed", "newscrawler/tools/run_lock.py",
  "allow_pids=(os.getpid(), os.getppid())", "allow_pids=(os.getpid(),)"),
 ("stale_lock_is_live", "newscrawler/tools/run_lock.py",
  "    return info if _pid_alive(info.get(\"pid\")) else None", "    return info"),
 ("over_budget_uses_default_timeout", "scripts/run_scheduled_crawl.py",
  "                    timeout = timeout_for(website, args.timeout)", "                    timeout = args.timeout"),
 ("log_prune_keeps_all", "scripts/run_scheduled_crawl.py",
  "    for old in (logs[:-keep] if keep > 0 else []):", "    for old in []:"),
 ("null_embedding_ignored", "scripts/run_scheduled_crawl.py",
  "            pending = null_embedding_by_source(session)", "            pending = {}"),
]
only = sys.argv[1:]
env = dict(os.environ, VECTOR_DB_NAME_L1=os.path.join(SCRATCH, "NOPE_L1"),
           VECTOR_DB_NAME_L2=os.path.join(SCRATCH, "NOPE_L2"), POSTGRES_DB_PORT="1",
           TELEGRAM_BOT_TOKEN="", PYTHONDONTWRITEBYTECODE="1")
for name, path, old, new in M:
    if only and name not in only: continue
    p = os.path.join(ROOT, path)
    src = open(p, "rb").read().decode("utf-8")
    crlf = "\r\n" in src
    o, n = (old.replace("\n", "\r\n"), new.replace("\n", "\r\n")) if crlf and src.count(old) != 1 else (old, new)
    if src.count(o) != 1:
        print(f"{name}: PATTERN NOT FOUND ({src.count(o)})", flush=True); continue
    open(p, "wb").write(src.replace(o, n).encode("utf-8"))
    try:
        r = subprocess.run([r"venv\Scripts\python.exe", "-m", "pytest", "tests/unit", "-q", "-x", "-p", "no:cacheprovider",
                            "--no-header", "-rN", "--tb=no", "-W", "ignore"], capture_output=True, text=True, env=env, cwd=ROOT)
        tail = [l for l in r.stdout.splitlines() if l.strip()][-2:]
        print(f"{name}: {'KILLED' if r.returncode else 'SURVIVED'} rc={r.returncode} :: {' | '.join(tail)[:300]}", flush=True)
    finally:
        subprocess.run(["git", "checkout", "--", path], cwd=ROOT)
