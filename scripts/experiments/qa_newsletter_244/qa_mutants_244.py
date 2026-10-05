"""QA's own mutants for tracker #244, run against the dev's tests/unit in an isolated worktree
(never the main repo: the scheduled jobs import it). Each mutant re-introduces one thing a ticket
promises not to do. The unmutated baseline must pass first (checked).

    git worktree add <scratch>\\mutwt HEAD
    $env:QA_WORKTREE = "<scratch>\\mutwt"; $env:QA_TESTS = "tests/unit/test_newsletter_edition.py ..."
    venv\\Scripts\\python.exe scripts\\experiments\\qa_newsletter_244\\qa_mutants_244.py [NAME ...]
"""
import os
import subprocess
import sys

WT = os.environ["QA_WORKTREE"]
# The real venv interpreter by its own short path: through a junction under the scratchpad, site-packages
# paths pass MAX_PATH and every test file importing transformers dies at collection (EXPERIMENTS.md trap).
PY = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                  "venv", "Scripts", "python.exe")
TESTS = os.environ.get("QA_TESTS", "tests/unit").split()

SS, NE, NG, PDF, CP = ("newscrawler/core/story_summary.py", "newscrawler/core/newsletter_edition.py",
                       "newscrawler/core/newsletter_generator.py", "newscrawler/core/newsletter_pdf.py",
                       "newscrawler/core/newsletter_copy.py")
RUN = "scripts/run_scheduled_newsletter.py"
M = [
    # SYS-82
    ("ss_no_number_guard", SS, "        bad = unsupported_number(value, source)\n", "        bad = None\n"),
    ("ss_no_length_check", SS, "        if words(value) > limit:\n", "        if False:\n"),
    ("ss_judul_limit_14", SS, '"judul": 12,', '"judul": 14,'),
    ("ss_inti_limit_26", SS, '"inti": 25,', '"inti": 26,'),
    ("ss_sekilas_limit_16", SS, '"sekilas": 15}', '"sekilas": 16}'),
    ("ss_max_poin_3", SS, "MAX_POIN = 2", "MAX_POIN = 3"),
    ("ss_no_short_date_check", SS, "        if not _date_in(int(match.group(1)), int(match.group(2)), source):\n",
     "        if False:\n"),
    ("ss_missing_index_ok", SS, "    if set(terkait) & set(tidak) or len(terkait) + len(tidak) != n:\n",
     "    if set(terkait) & set(tidak):\n"),
    ("ss_empty_terkait_ok", SS, "    if not terkait:\n        raise", "    if False:\n        raise"),
    ("ss_retry_without_reason", SS, "summarizer.summarize(prompt + RETRY.format(detail=first.detail))",
     "summarizer.summarize(prompt)"),
    ("ss_no_retry_poin_drop", SS, "                         drop_long_poin=True)", "                         drop_long_poin=False)"),
    ("ss_poin_cut_not_dropped", SS, "    kept = [p for p in poin if words(p) <= LIMITS[\"poin\"]][:MAX_POIN] if drop_long_poin else poin",
     "    kept = [\" \".join(p.split()[:20]) for p in poin][:MAX_POIN] if drop_long_poin else poin"),
    # SYS-80
    ("ng_links_from_all", NG, '        cluster["links"] = self._top_links(related)', '        cluster["links"] = self._top_links(cluster["articles"])'),
    ("ng_headline_from_all", NG, '        cluster["headline"] = self._pick_cluster_headline(related)',
     '        cluster["headline"] = self._pick_cluster_headline(cluster["articles"])'),
    ("ng_sources_include_unrelated", NG, 'for a in cluster["articles"] if id(a) not in unrelated])',
     'for a in cluster["articles"]])'),
    # SYS-84 / SYS-81
    ("cp_wrong_weekday", CP, '    return f"{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}"',
     '    return f"{DAYS[d.weekday() - 1]}, {d.day} {MONTHS[d.month - 1]} {d.year}"'),
    ("cp_short_month_off", CP, '"Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu"', '"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Agu"'),
    ("cp_drop_tvone", CP, '    "TVONENEWS":      "tvOnenews",\n', ""),
    ("cp_no_ai_disclosure", CP, '"Ringkasan ditulis AI dan bisa keliru; cek artikel aslinya untuk detail."', '"Cek artikel aslinya."'),
    ("ng_no_degraded_notice", NG, "        if stats is not None and stats.fallback:\n", "        if False:\n"),
    ("ng_enum_in_source_line", NG, '        outlets = [copy.outlet(s) for s in cluster["sources"]]', '        outlets = list(cluster["sources"])'),
    ("ng_iso_dateline", NG, 'lines = [f"# {copy.TITLE}", "", f"> {copy.DATELINE_FULL.format(tanggal=copy.tanggal(target_date))}", ""]',
     'lines = [f"# {copy.TITLE}", "", f"> {copy.DATELINE_FULL.format(tanggal=target_date.isoformat())}", ""]'),
    ("ng_keep_stale_edition", NG, "        if os.path.exists(path):\n            os.remove(path)\n        return result, None",
     "        return result, None"),
    # SYS-83
    ("ne_max_per_section_3", NE, "MAX_PER_SECTION = 2", "MAX_PER_SECTION = 3"),
    ("ne_no_non_finance_rule", NE, "    if sum(not by_id[i].finance for i in utama) < needed:\n", "    if False:\n"),
    ("ne_no_duplicate_rule", NE, "    if len({_group_of(i, groups) for i in utama}) != len(utama):\n", "    if False:\n"),
    ("ne_no_repeat_id_rule", NE, "    if len(set(utama)) != len(utama):\n", "    if False:\n"),
    ("ne_sixty_max_8", NE, "SIXTY_MIN, SIXTY_MAX, SIXTY_WORDS = 3, 5, 18", "SIXTY_MIN, SIXTY_MAX, SIXTY_WORDS = 3, 8, 18"),
    ("ne_sixty_words_25", NE, "SIXTY_MIN, SIXTY_MAX, SIXTY_WORDS = 3, 5, 18", "SIXTY_MIN, SIXTY_MAX, SIXTY_WORDS = 3, 5, 25"),
    ("ne_sixty_no_number_guard", NE, '        bad = unsupported_number(sentence, by_id[cid].cluster.get("source_text", ""))',
     '        bad = None'),
    ("ne_budget_12000", NE, "WORD_BUDGET = 1200", "WORD_BUDGET = 12000"),
    ("ne_budget_trims_guaranteed", NE, "        droppable = [k for k, s in enumerate(sekilas) if not s.guaranteed]",
     "        droppable = [k for k, s in enumerate(sekilas)]"),
    ("ne_budget_trims_top_of_list", NE, "        sekilas = sekilas[:droppable[-1]] + sekilas[droppable[-1] + 1:]",
     "        sekilas = sekilas[:droppable[0]] + sekilas[droppable[0] + 1:]"),
    ("ne_sekilas_per_section_4", NE, "SEKILAS_PER_SECTION = 3", "SEKILAS_PER_SECTION = 4"),
    ("ne_no_echo_guard", NE, "        if any(echoes(c, top) for top in tops):\n", "        if False:\n"),
    ("ne_no_guarantee", NE, "GUARANTEED_TOP = 6", "GUARANTEED_TOP = 0"),
    ("ne_cands_per_section_2", NE, "CANDIDATES_PER_SECTION = 3", "CANDIDATES_PER_SECTION = 2"),
    ("ne_fallback_no_quota", NE, "    picked = _pick(pool, FALLBACK_UTAMA, required_non_finance(cands, groups), groups)",
     "    picked = pool[:FALLBACK_UTAMA]"),
    ("ne_unsummarized_in_sekilas", NE, "        if not c.summarized or c.id in choice.utama", "        if c.id in choice.utama"),
    ("ne_no_edition_notice", NE, "    if unsummarized:      #", "    if False:      #"),
    ("ne_md_no_escape", NE, '    return text.replace("[", "(").replace("]", ")")', "    return text"),
    # OPS-41 / OPS-42
    ("pdf_story_not_kept", PDF, "                    flowables.append(Paragraph(inline(value), s[\"meta\" if small else \"para\"]))\n            out.keep(flowables)",
     "                    flowables.append(Paragraph(inline(value), s[\"meta\" if small else \"para\"]))\n            out.free(flowables)"),
    ("pdf_section_not_held", PDF, '            out.hold([Paragraph(inline(block.text), s["section"])])',
     '            out.free([Paragraph(inline(block.text), s["section"])])'),
    ("pdf_body_9pt", PDF, "PHONE_BODY_SIZE = 11.5", "PHONE_BODY_SIZE = 9"),
    ("pdf_footer_777", PDF, 'FOOTER_COLOR = "#666666"', 'FOOTER_COLOR = "#777777"'),
    ("pdf_band_low_contrast", PDF, 'ACCENT = "#0b3d7a"', 'ACCENT = "#7a9cc6"'),
    ("pdf_phone_a4", PDF, "    return _render(markdown_path, pdf_path, build_edition_story, PHONE_PAGE,",
     "    return _render(markdown_path, pdf_path, build_edition_story, A4,"),
    ("pdf_no_escape", PDF, "    text = escape(_drawable(_EMOJI.sub(\"\", text)))", "    text = _drawable(_EMOJI.sub(\"\", text))"),
    ("pdf_footer_iso", PDF, "    return copy.caption(d) if d else copy.TITLE", "    return f\"{copy.TITLE} {d}\" if d else copy.TITLE"),
    ("pdf_link_alone", PDF, "    out.keep(flowables[:2])\n    out.free(flowables[2:-2])\n    out.keep(flowables[-2:])",
     "    out.keep(flowables[:2])\n    out.free(flowables[2:])"),
    # OPS-43
    ("run_no_html_escape", RUN, '["• %s" % escape(s, quote=False) for s in sentences]', '["• %s" % s for s in sentences]'),
    ("run_sends_digest", RUN, "        pdf_path = _render_pdf(target_date, edition_path, edition=True)",
     "        pdf_path = _render_pdf(target_date, digest_path, edition=False)"),
    ("run_pdf_ok_always", RUN, "pdf_ok=pdf_path is not None))", "pdf_ok=True))"),
    ("run_no_length_cap", RUN, "        if len(text) <= MESSAGE_MAX_CHARS or not sentences:", "        if True:"),
    ("run_no_degraded_in_no_edition", RUN, "    if missing > 0:\n        lines.append", "    if False:\n        lines.append"),
    ("run_message_skipped_on_fail", RUN, "    if pdf_path is not None:\n        _send_pdf_file", "    if pdf_path is not None and False:\n        _send_pdf_file"),
    # SYS-85
    ("sys85_old_key", "newscrawler/core/constants.py", '    "ANTARANEWS":   0.70,', '    "ANTARA":   0.70,'),
]


def main(names):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", POSTGRES_DB_PORT="1", TELEGRAM_BOT_TOKEN="",
               TELEGRAM_CHAT_ID="", VECTOR_DB_NAME_L1=os.path.join(WT, "_nope_L1"),
               VECTOR_DB_NAME_L2=os.path.join(WT, "_nope_L2"), OPENAI_API_KEY="", GEMINI_API_KEY="")
    survived = []
    base = subprocess.run([PY, "-m", "pytest", *TESTS, "-q", "-p", "no:cacheprovider", "-W", "ignore"], cwd=WT, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    print("BASELINE (unmutated):", base.stdout.strip().splitlines()[-1], flush=True)
    if base.returncode != 0:
        sys.exit("the unmutated tree fails: every 'kill' would be the environment")
    for name, path, old, new in M:
        if names and name not in names:
            continue
        full = os.path.join(WT, path)
        src = open(full, encoding="utf-8", newline="").read()
        if src.count(old) != 1 and src.count(old.replace("\n", "\r\n")) == 1:
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        if src.count(old) != 1:
            print(f"{name:34s} NOT APPLIED (pattern occurs {src.count(old)}x)")
            continue
        open(full, "w", encoding="utf-8", newline="").write(src.replace(old, new))
        try:
            r = subprocess.run([PY, "-m", "pytest", *TESTS, "-x", "-q", "-p", "no:cacheprovider", "-W", "ignore"],
                               cwd=WT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            killed = r.returncode != 0
            lines = r.stdout.splitlines()
            why = [l for l in lines if l.startswith(("FAILED", "ERROR"))][:1] or lines[-1:]
            print(f"{name:34s} {'KILLED' if killed else 'SURVIVED'} rc={r.returncode} {why[0][:110] if why else ''}",
                  flush=True)
            if not killed:
                survived.append(name)
        finally:
            open(full, "w", encoding="utf-8", newline="").write(src)
    print("SURVIVORS:", survived)


if __name__ == "__main__":
    main(sys.argv[1:])
