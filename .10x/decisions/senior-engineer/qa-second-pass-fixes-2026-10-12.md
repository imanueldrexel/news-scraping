# Senior engineer: approach per ticket (2026-10-12, QA second pass)

- **SYS-144:**
  - add the adverbs to `_NOT_REFERENCES`: sebenarnya, sesungguhnya, selanjutnya, sebelumnya, biasanya, akhirnya, misalnya, khususnya, terutamanya, sepertinya, tampaknya, nampaknya, kelihatannya, rupanya, agaknya, seharusnya, semestinya, setidaknya, sekurangnya, umumnya, tentunya, katanya;
  - leave out sesudahnya, setelahnya, sebaliknya, lainnya (they point back).
- **SYS-143:**
  - `_REFUSAL = re.compile(r"^(?:maaf\b|mohon maaf\b|saya tidak (?:dapat|bisa|mampu)\b|sebagai (?:ai|asisten|model)\b|i'?m sorry\b|sorry\b|i can(?:not|'t)\b)", re.I)` on the checked text;
  - `_LIST_ITEM = re.compile(r"^(?:\d+[.)]|[-*•])\s")`;
  - both are applied after the label/quote strip.
- **SYS-145:** in `followup.resolve`, `if how == KEPT and refers_back(q): return _thread(q, previous, KEPT_THREAD)`. Factor `_thread` out of the fallback branch so the two cannot drift.
- **SYS-138:**
  - `KeywordQuery.subject` property;
  - `_holds_subject(kq, texts) -> List[bool]`: `SELECT x.i, (has[w1] + ... ) >= 1` over `unnest`, the same shape as `_coverage`;
  - in `candidates` the window path is: `inside = passes_floor`; `leaders = [h for h in inside if keyword-origin or holds]`; full iff `len(leaders) >= RAG_TOP_K`; else `leaders + everything minus leaders`.
  - Keep `counts["window"]` as `7d` / `7d+len(leaders)`.
- **DBT-69:** extend `tests/integration/test_drop_oversized_queued_chunks_live.py` with a second source and 80/81-word rows; add the unusable-reply test to `TestFollowUp`.
- **DBT-68:** delete lines 214-~243 of `test_source_worker.py` after diffing the two bodies. Add `TestNoShadowedTestNames` to `test_repo_hygiene.py`.
- **DBT-67:** move functions verbatim first (git shows a move), then switch the callers, then remove the copies. Patch targets in tests follow (`store_repair.X`).
