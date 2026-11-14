# QA rules (binding; OPS-50, owner 2026-11-14)

QA checks a ticket against a fixed contract and stops. It does not hunt for
everything that could be better. Unbounded review never converges (story arcs:
SYS-152 open from 10-13 to 11-14, 56 qa-defects). Bounded review merges work
and turns the rest into tickets.

## The contract
1. **Oracle.** QA judges only against:
   (a) the ticket's acceptance criteria in `tickets/<ID>.md`;
   (b) its Verify command;
   (c) previously passing tests, i.e. regressions: `tests/unit`, plus `tests/integration` when DB code or a migration changed;
   (d) a crash, silent data loss, a security hole, or a secret in the diff.
2. **The contract is frozen at the red commit.** Only the owner changes an AC. The change is recorded in the ledger as `AC<k> changed (owner, <date>)`. QA never rewords one.

## Findings
3. **BLOCKER.** It cites (a)–(d) by ID (`AC2`, `REG`, `CRASH`, `LOSS`, `SEC`) **and** has a reproduction: a failing test, or an exact command with its actual output. No reproduction means no blocker.
   - File it as `[QA] #<parent>: <short>` with labels `qa-defect` + `sev:blocker`.
   - Body: Parent · Audited commit · Steps · Expected · Actual · Location (`file:line`) · Failing test (full, runnable).
   - **No "Fix" section.** QA describes the failure, dev chooses the fix.
4. **FOLLOW-UP.** A likely real defect outside the criteria. Example: an input class no AC names, such as an unlisted synonym (ADR-031, applied to every ticket).
   - File it as a normal ticket with the next ID (bug + P* + area). The body opens with "Found by QA of <ID>".
   - It **does not block** and does not mark the parent `qa-failed`.
5. **NIT.** Style, naming, refactors, "would be nice", or an edge case no AC names that is not a defect. One line in the ledger; never filed, never blocking.

## Rounds
6. **Round 1:** run every check, then review the diff against each AC and against Out of scope. **Round 2+:** re-run Verify and the suites, then re-check **only the open blockers**. A new concern in round 2+ is a FOLLOW-UP unless it is a regression or class (d).
7. **Never reopen** a finding marked `verified`, `rejected` or `deferred`.
8. **Cap.** Round 3 is the last. If blockers remain after round 3, the verdict is NEEDS-DECISION: label `status: needs-decision` and summarise the options for the owner (ship with follow-ups / rescope / owner takes over / close).

## Method
9. **Per AC:** state what it requires, then what the code does (run it, never infer from reading), then compare. For each fixed behaviour, re-introduce the bug as a mutant in a copy of the tree (never the live tree, `qa-mutation-testing`) and confirm the AC test goes red.
10. **Test tampering.** Run `git diff <red commit>..HEAD -- <acceptance test file>`.
    - Additions are allowed: dev adds a blocker's reproduction test.
    - A changed or deleted red test without a Dev-log note is a BLOCKER (`REG`).
11. **No edits.** QA does not modify source or tests. It edits only `tickets/<ID>.md`, plus QA-owned files under `tests/qa/` and `scripts/experiments/qa_<date>/`.
12. **Unverifiable now.** An AC of kind `run: N` (scheduled runs) or `owner` that cannot be checked yet gives HELD. The round is not consumed, and the ticket stays `status: ready-for-qa`.

## Verdict (the final line, exactly one)
    VERDICT: PASS
    VERDICT: HELD (<AC ids>)
    VERDICT: BLOCKED (<k>)
    VERDICT: NEEDS-DECISION

| Verdict | Labels | Issue |
|---|---|---|
| PASS | remove `status: ready-for-qa`, add `status: qa-passed` | close it, commenting one line per AC (check → result) |
| HELD | keep `status: ready-for-qa` | comment which AC waits for what |
| BLOCKED | remove `status: ready-for-qa`, add `status: qa-failed` | comment listing the `[QA]` blocker numbers |
| NEEDS-DECISION | remove the status labels, add `status: needs-decision` | comment with the options |
