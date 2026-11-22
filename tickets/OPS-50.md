# OPS-50 (#465) -- Bounded dev/QA contract: acceptance criteria, QA rules, round cap, ledger, skills and hooks
Status: in-qa
Round: 0 / 3
Red commit: none -- bootstrap (this ticket builds the red-commit procedure; tests and code land in one commit)
Contract frozen: 2026-11-14

## Acceptance criteria (copied verbatim from the issue; never reword -- only the owner changes them)
| ID | Kind | Criterion | Check | Passes |
|----|------|-----------|-------|--------|
| AC1 | unit | Given an issue body with `AC<k> [kind]:` lines (or, for a legacy ticket, a Done-when), when `ticket.py init` runs, then `tickets/<ID>.md` holds each criterion verbatim with its kind, plus the Verify command and the Out-of-scope list. | tests/unit/test_dev_qa_hooks.py::test_parse_acceptance_reads_ids_kinds_and_text, test_init_writes_the_ledger, test_legacy_done_when_*, test_indented_lines_* | yes |
| AC2 | unit | Given the Stop hook with a `dev-start` marker and a red Verify, when the dev session's turn ends, then it is blocked with the last output lines, at most 3 forced continues in a row. With no marker, another session's marker, a marker older than 24 h, or a last message holding a `VERDICT:` line, it never blocks. | tests/unit/test_dev_qa_hooks.py::test_red_verify_blocks_*, test_qa_turn_*, test_another_session_*, test_forced_continues_*, test_stale_marker_*, test_no_marker_* | yes |
| AC3 | unit | Given the git commit-msg hook, when a message contains `Fixes #12`, `closes #12` or `Resolved: owner/repo#5`, then the commit is rejected. `Refs #12` and prose such as "closed, #458" are accepted. | tests/unit/test_dev_qa_hooks.py::test_closing_keywords_are_rejected, test_refs_and_prose_are_accepted, test_commit_msg_hook_calls_the_check | yes |
| AC4 | unit | `.claude/qa-rules.md` defines exactly the verdicts `PASS`, `HELD`, `BLOCKED`, `NEEDS-DECISION`, and `.claude/settings.json` registers `ticket.py stop-hook` as a Stop hook. | tests/unit/test_dev_qa_hooks.py::test_qa_rules_verdicts_match_the_hook, test_project_settings_register_the_stop_hook | yes |
| AC5 | live: `grep -n "Definition of done" CLAUDE.md; ls .claude/skills docs/TICKET_IDS.md` | CLAUDE.md has a "Definition of done" section. The skills `write-ticket`, `implement-issue` and `qa-issue` exist, and the ID map lives in `docs/TICKET_IDS.md`. | `grep -n "Definition of done" CLAUDE.md` -> line 53; `.claude/skills/{write-ticket,implement-issue,qa-issue}/SKILL.md`; `docs/TICKET_IDS.md` | yes |

## Verify
`venv\Scripts\python.exe -m pytest tests/unit/test_dev_qa_hooks.py -q`

## Out of scope
- Rewriting existing open tickets into AC form. A legacy ticket is converted by `/implement-issue` from its Done-when, starting at round 1.
- The headless `claude -p` loop and parallel agents (report Stage 3).
- Trimming CLAUDE.md's architecture section.

## QA findings
| ID | Round | Kind | Cites | Reproduction | Status |
|----|-------|------|-------|--------------|--------|

## Dev log (newest first, 1-3 lines per session)
- R0 dev 2026-11-14: built ticket.py, qa-rules, 3 skills, Stop + commit-msg hooks, CLAUDE.md DoD, templates. Verify 24 passed; tests/unit 4379 passed / 5 skipped; 5/5 own mutants killed. Live: show/init via gh, Stop hook via its settings.json command (unarmed 0 / red block / VERDICT 0 / green 4.9s cached), commit-msg via sh.
