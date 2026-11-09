
## 2026-10-16 (night): SYS-169 rework, SYS-171..173
- No security finding. Regex-only changes on model output and article text: no new input path, no I/O, no secrets. The new patterns are bounded (`{0,8}?`, `{0,2}`), and the 140 QA tests run in 1.1 s. Integrity gaps SYS-174..176 are filed as bugs.

## 2026-10-16 (evening): SYS-167..170, DBT-79, DBT-80
- No security finding (`.10x/reviews/2026-10-16-security-review-evening.md`).
- OPS-33's token redaction is mutation-guarded on all three Telegram send paths.
- Integrity gaps were filed as bugs: SYS-169 sent back, SYS-171 #370, SYS-172 #371.

## 2026-10-16 (late): SYS-171 rework, SYS-174..176
- No security finding (`.10x/reviews/2026-10-16-security-review-late.md`). Regex and backing-set changes on in-process text only; bounded patterns (179 QA tests in 1.4 s). QA's probes open the DB read-only. Integrity gaps were filed as bugs: SYS-174 sent back, SYS-177..179.

## 2026-10-18: ADR-019 causal gate, SYS-186, SYS-174/177/178/179
- No security finding. The changes are regex and set logic on model output and article text: no new input path, no I/O, no secrets.
- The patterns are bounded (`_END_GAP {0,2}?`, the negation window of 3 words). QA's 104 tests run in 1.3 s, and no pathological backtracking was seen on 150,482 corpus sentences.
- QA's corpus probe opened the DB with `SET TRANSACTION READ ONLY`.
- The integrity gaps (false causal facts and schedules) are filed as bugs: SYS-188..193, plus the send-backs.
