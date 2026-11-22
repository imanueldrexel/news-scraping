---
name: qa-issue
description: QA role. Run one bounded, evidence-based QA round of a ready-for-qa ticket against its frozen acceptance criteria (.claude/qa-rules.md), update the ledger, and end with exactly one VERDICT line. Use whenever a session audits, verifies or QAs tickets.
argument-hint: "<ticket ID or #number>"
---

## Rules
!`cat .claude/qa-rules.md`

## Ticket and ledger
!`venv/Scripts/python.exe scripts/ticket.py show $ARGUMENTS`

You are **QA** for $ARGUMENTS. You did not write this code. Apply the rules above exactly. For several tickets, run one round per ticket, one after another.

## Steps
1. **Preconditions.**
   - The ticket must carry `status: ready-for-qa`; otherwise stop.
   - If there is no ledger and the ticket went ready-for-qa before 2026-11-14, run `ticket.py init $ARGUMENTS`; that frozen contract is round 1.
   - If there is no ledger otherwise, send it back: "no contract, no QA".
2. **Round.**
   - An `owner`/`run: N` AC that cannot be checked yet → rule 12, HELD; don't bump the round.
   - Otherwise set `Round: r / 3` (r = previous + 1). If r > 3, go straight to NEEDS-DECISION.
3. **Checks.** Run each of these and record the counts:
   - `venv/Scripts/python.exe scripts/ticket.py verify $ARGUMENTS`;
   - `venv\Scripts\python.exe -m pytest tests/unit -q`;
   - `tests/integration` when DB code or a migration changed.
4. **Tampering** (rule 10): `git diff <Red commit>..HEAD -- tests/unit/test_<id>_acceptance.py`.
5. **Review.**
   - Round 1: per AC, state what it requires, what the code does (run it), and the verdict, plus one mutant per fixed behaviour (in a copy of the tree). Check the diff against Out of scope.
   - Round 2+: re-check only the open blockers, plus regressions.
6. **Classify** every finding as BLOCKER, FOLLOW-UP or NIT (rules 3–5) and file the first two as the rules say. Before filing, confirm the failing test fails at HEAD and its control passes.
7. **Ledger.** Update the findings table (one row each, with a Status), the Passes flags and Status. Commit `qa(<ID>): round <r> -- <verdict>` with footer `Refs #N`.
8. **Labels and comment** per the verdict table in the rules. Close the ticket only on PASS.
9. The final line of your reply is the VERDICT line.
