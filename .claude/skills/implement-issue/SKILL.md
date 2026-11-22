---
name: implement-issue
description: Dev role. Implement one ticket against its frozen acceptance criteria. Commit red tests first, make the smallest change that turns them green, verify, then hand off to QA with status ready-for-qa. Use whenever a session is asked to fix, build or work a ticket.
argument-hint: "<ticket ID or #number>"
---

## Ticket and ledger
!`venv/Scripts/python.exe scripts/ticket.py show $ARGUMENTS`

You are **dev** for $ARGUMENTS. Follow CLAUDE.md "Definition of done". Work one ticket at a time.

## Steps
1. **Queue check.** If the ready-for-qa queue above is **≥ 6** and the owner did not ask for a burn-down, say so and stop: reviews, not code, are the bottleneck.
2. **Contract.**
   - If there is no ledger, run `venv/Scripts/python.exe scripts/ticket.py init $ARGUMENTS`.
   - If the issue has neither AC lines nor a Done-when, stop: draft AC1..ACn in the `/write-ticket` form and ask the owner to approve them.
   - If the criteria were *derived* from a Done-when, give each one a kind (`unit`/`integration`/`live`/`run: N`/`owner`) and a Check, and add a Verify command. Then post them to the issue as a comment headed **"Contract (frozen)"**. Never reword the criterion text.
3. **Arm the hook:** `venv/Scripts/python.exe scripts/ticket.py dev-start $ARGUMENTS`. While armed, a turn cannot end with the Verify red.
4. **Red, first round only** (the ledger's "Red commit" is `(none yet)`):
   - write one failing test per `unit`/`integration` AC in `tests/unit/test_<id lower, no dash>_acceptance.py` (e.g. `test_sys152_acceptance.py`), named `test_ac<k>_<what>`;
   - run them and show that each fails **on its assertion**, not on a typo or an import error of the test itself;
   - commit only that file: `test(<ID>): acceptance tests (red)` with footer `Refs #N`;
   - record the SHA as "Red commit" in the ledger.
5. **Later rounds.** Fix only the ledger's `open` BLOCKERs. Add each blocker's reproduction test to the acceptance file. You may add tests to it, but never change or delete the red ones. If one looks wrong, stop and say why. Ignore FOLLOW-UPs and NITs.
6. **Implement.** Make the smallest change that turns the tests green (see the code rules below).
7. **Verify.** Run `venv/Scripts/python.exe scripts/ticket.py verify $ARGUMENTS`, then `venv\Scripts\python.exe -m pytest tests/unit -q` (about 2 minutes). Add `tests/integration` when DB code or a `scripts/migrate_*.sql` changed (DBT-22). Read the real output; never claim green.
8. **Commit** `fix|feat(<area>): [<ID>] <what>` with footer `Refs #N`. Never use `Fixes`/`Closes`: the commit-msg hook rejects them.
9. **Ledger.** Set the Passes flags, add a Dev log line (newest first, 1–3 lines) and `Status: in-qa`. Commit it with the work.
10. **Hand off.**
    - Comment on the issue with one line per AC (`AC2 → tests/unit/…::test_ac2_x → passed`), the suite counts, and the commit SHAs.
    - Remove `status: qa-failed` if present, then add `status: ready-for-qa`. Never close the ticket.
11. **Disarm the hook** (`ticket.py dev-stop`) and stop. Do not review your own work: QA does that in a fresh session.

## Code rules
- **Scope:** touch only what the ACs need. Nothing in Out of scope, no drive-by refactors, no reformatting of untouched lines.
- **No speculative design:** no new env var, config knob, abstraction, fallback or parameter unless an AC requires it. Three similar lines beat a premature helper.
- **Match the surrounding code:** naming, comment density, idiom, error handling. A comment says *why* in one line, tagged `(SYS-NN)` where this repo already does that. No ticket narrative in code.
- **Fail loudly:** a guard raises or returns a named reason, never a silent default. Every reader-facing string stays in `core/newsletter_copy.py` / `core/web_copy.py`.
- **New bugs get their own ticket:** a bug found on the way is filed with `/write-ticket` (issue first) and reported. Don't fix it here unless it blocks an AC.
- **Log experiments:** a probe, benchmark or comparison gets an `EXPERIMENTS.md` entry in the same commit.
