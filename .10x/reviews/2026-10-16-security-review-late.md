# Security review 2026-10-16 (late): SYS-171 rework, SYS-174..176

**Scope:** commit eeb205c (`source_check.py`, `story_arc.py`, tests, `qa_mutation_runner.py`, `recheck_replays.py`).

- **Input:** the new regexes and `_backing_days` read model output and article text that are already in the process. There is no new input path, I/O, network call or secret.
- **ReDoS:** `_DAY_OF_WEEK` is fixed alternations. `_WEEKDAY_BEFORE_DATE` is optional pieces plus a fixed lookahead (`\s*` then a digit). `_CHANGE_TO_AFTER` adds one alternative, `\s+mencapai`, next to the bounded `{0,8}?` gap. QA's 179 tests run in 1.4 s, and the unit suite's time is unchanged (~131 s for 3,493).
- **Tooling:**
  - `recheck_replays.py --db` opens the connection with `set_session(readonly=True)`, and so do QA's two probes.
  - Both mutant runners refuse the live tree and restore each file byte for byte.
- **Integrity** (false facts printed): the SYS-174 send-back and SYS-177..179 are filed as bugs, not security findings.

No security finding.
