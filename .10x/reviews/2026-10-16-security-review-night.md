# Security review 2026-10-16 (night): SYS-169 rework, SYS-171..173

**Scope:** commit 1eff4b1 (`source_check.py`, `story_arc.py`, tests, `run_registry_mutants_in_copy.py`).

- **Input:** the new regexes read model output and article text that are already in the process. There is no new input path, I/O, network call or secret.
- **ReDoS:** the patterns are bounded: the gap is `(?:\s+\S+){0,8}?`, the words before N are `{0,2}`, and the window counts are alternations. QA's 140 tests run in 1.1 s, and the unit suite's time is unchanged (~100 s).
- **Tooling:** `run_registry_mutants_in_copy.py` refuses the live tree (`os.path.abspath(argv[1]) == REPO`) and restores each file byte for byte. QA's runner does the same.
- **Integrity** (false facts printed): SYS-171 is sent back, and SYS-174 is filed as P2 bugs, not security findings.

No security finding.
