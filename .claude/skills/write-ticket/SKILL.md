---
name: write-ticket
description: File a GitHub issue in this repo's bounded form (numbered acceptance criteria, one Verify command, Out of scope). Use for every new bug, requirement, QA follow-up or owner request before any code is written.
argument-hint: "<what the ticket is about>"
---

File one ticket for: $ARGUMENTS

A ticket is a contract that QA can check, not a design document. Short tickets
with precise expected behaviour converge (77% vs 46% merge rate for poorly
scoped ones).

## Rules
1. **One behaviour per ticket.** Split anything that needs two Verify commands.
2. **Prefix + next free number.** SYS pipeline · OPS tooling/observability · SRC per-source scraper · DBT tech debt:
   `gh issue list --state all --search "[SYS-" --limit 300 --json title -q ".[].title"`
   Title: `[SYS-NN] <what is wrong / what is wanted>`.
3. **2–5 acceptance criteria**, each `AC<k> [kind]: Given …, when …, then …`. Kinds:
   - `unit`: a test in `tests/unit/test_<id>_acceptance.py` (needs no DB or network);
   - `integration`: a test against `newsaggregator_test`;
   - `live: <command>`: QA runs the command read-only against prod and states the expected output;
   - `run: N`: the next N scheduled runs show `<observable>`;
   - `owner`: the owner reads or decides. Avoid it; prefer a measurable proxy.

   Each "then" is observable: a value, a count, a refusal reason, an exit code. "Works well", "reads naturally" and "handles synonyms" are not criteria.
4. **One Verify command** that exits 0 when every `unit`/`integration` AC holds, normally
   `venv\Scripts\python.exe -m pytest tests/unit/test_<id>_acceptance.py -q`.
5. **Out of scope is mandatory.** List the neighbouring cases this ticket deliberately does not cover. That list is what stops the next QA round from growing the ticket.
6. **The body stays under ~30 lines.** Design rationale goes in an ADR (`.10x/adrs/NNN-*.md`) that the ticket links. QA-filed tickets have no Fix section.
7. **Labels.** Bug: `bug` + one of `P0 - critical`/`P1 - high`/`P2 - medium`/`P3 - low` + one area. Requirement: `enhancement` + one area. Areas: `area: pipeline`, `area: observability`, `area: scraper`, `area: tech-debt`, `area: web`.

## Body
```
<bug: Where `file:line` · Symptom · Root cause (or "unknown yet") · Evidence. Requirement: Motivation, 2-4 lines>

## Acceptance criteria
- AC1 [unit]: Given …, when …, then …
- AC2 [unit]: Given …, when …, then …

## Verify
`venv\Scripts\python.exe -m pytest tests/unit/test_<id>_acceptance.py -q`

## Out of scope
- …
```

## Steps
1. Check for a duplicate: `gh issue list --state open --search "<keywords>"`.
2. Write the body to a scratchpad file and file it:
   `gh issue create --title "[XXX-NN] …" --label … --body-file <file>`
3. Report `XXX-NN (#N)` and its link. Do not start coding unless this session was asked to.
