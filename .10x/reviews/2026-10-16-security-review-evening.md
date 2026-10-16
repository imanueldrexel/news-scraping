# Security review 2026-10-16 (evening): SYS-167..170, DBT-79, DBT-80

**Scope:**
- `source_check._FUTURE` / `future_key` / `unstated_future_times` and `_RELATIVE`'s new week phrases;
- `_CHANGE_TO` / `_CHANGE_CLAIM`;
- `story_arc.parse`'s new check and prompt line;
- `tests/unit/test_repo_hygiene.py`;
- the registry retargets in `scripts/experiments/qa_mutation_runner.py`.

**Verdict:** no security finding.

- **Input:** model output and article text only, the same trust level as the earlier arc guards. No DB writes, network calls or files.
- **Regex cost:**
  - `_FUTURE` is a fixed alternation.
  - The week phrases are fixed alternations.
  - `_CHANGE_CLAIM`'s new negative lookaheads are bounded.
  - QA's 68 tests run in 0.6 s; the four arc suites in about 3 s.
- **Hygiene test:** it parses the registry with `ast.literal_eval` and never executes it.
- **Prompt injection / integrity:** the arc text a manipulated article could steer is held to the sources. The gaps found are integrity, not security:
  - SYS-169 (sent back: "akhir bulan ini" late in the month);
  - SYS-171 #370 (weekday future times);
  - SYS-172 #371 (change-claim forms).
- **Secrets:** OPS-33's token redaction is mutation-guarded on all three Telegram send paths. DBT-80 retargeted `_post`; QA's 4 mutants on `_post_document` / `_post_html` are KILLED. The read-only corpus counts used `.env` credentials in-process (`set_session(readonly=True)`) and printed none.
