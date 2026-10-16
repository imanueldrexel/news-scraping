# Security review 2026-10-16: SYS-164 rework, SYS-165, SYS-166, DBT-78, SYS-161

**Scope:**
- `arc_style._is_frame` / `_SEJAK_OPENS`;
- `story_arc._FUTURE` / `future_times` / `agenda_repeats` / `_agenda_kept`;
- `source_check._CHANGE_CLAIM` / `_TOTAL_OR_CHANGE` / `unbacked_changes` (SYS-161);
- registry entries in `scripts/experiments/qa_mutation_runner.py`.

**Verdict:** no security finding.

- **Input:** these read model output and article text only, the same trust level as the SYS-148 guards. There are no DB writes, network calls or new files.
- **Regex cost:**
  - `_FUTURE` is a bounded alternation of fixed words.
  - `_SEJAK_OPENS` is anchored by `.match`.
  - `_CHANGE_CLAIM`'s `(?:\s+\S+){0,8}?` is bounded and runs per sentence.
  - QA's 55 tests and the four arc suites (313 tests) run in about 2 s.
- **Prompt injection:** the arc text a manipulated article could steer is held to the sources by these guards. Two gaps were found, and both are integrity rather than security:
  - SYS-169 #366: an agenda's relative future time is not held to the sources;
  - SYS-170 #367: "bertambah hingga N" passes the change guard.

  Filed as P2 bugs.
- **Secrets:** none touched. The read-only DB counts used `.env` credentials in-process (`set_session(readonly=True)`) and printed no secret.
