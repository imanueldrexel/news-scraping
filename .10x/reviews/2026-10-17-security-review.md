# Security review 2026-10-17: SYS-152 (causal gate), DBT-81

**Scope:** commit 9928aa1 (`core/causal_check.py`, `story_arc.py`, tests, `qa_mutation_runner.py`, `run_registry_mutants_in_copy.py`, `scripts/experiments/sys152/*`).

- **Input.** The `sebab` entries are model output. `_sebab` type-checks them: a list of dicts with an int `artikel` (not bool) and a str `kutipan`, else a `json` refusal. An `artikel` outside the quotable set is refused. There is no new I/O, network path or secret.
- **ReDoS.**
  - `CAUSAL` and `_BOUNDARY` are fixed alternations.
  - `_ATTRIBUTION` (`menurut\s+[^,;]*`) is linear.
  - `quote_in` uses `str.find`, never a regex built from model text.
  - QA's 34 tests run in 0.6 s.
- **Prompt feedback.** The retry detail quotes the arc's own sentence back to the same model. That sentence is model output, not new article text, so no new injection surface.
- **Tooling.**
  - The dev's registry runner and QA's `qa_mutants.py` work on a copy of the tree and restore each file byte for byte.
  - The DBT-81 mutant was run on `tests/unit/test_repo_hygiene.py`, a test-only file no job imports, and restored. `git status` was clean after.
- **Integrity** (false facts printed): the findings are filed as bugs, SYS-181..185, not as security findings.

No security finding.
