# Senior engineer: approach per ticket, 2026-10-12 list

- **SYS-111:** `deadline = parse_until(args.until)` once at the top of `_apply_locked`; pass it to `too_close` and `rechunk`. Port QA's fake-clock test into `tests/unit`. Mutant `sys111_resolved_twice`.
- **SYS-139:**
  - the deadline is a monotonic float, computed in the child from the job's `timeout_s`;
  - the loop keeps `longest_batch_s` and decides before each batch after the first;
  - unreached rows leave `attempted`, exactly as the throttle stop does (reuse that arithmetic, don't duplicate it);
  - mutants: never stop; stop ignores the batch estimate; the unreached rows still counted.
- **SYS-104/140:**
  - `followup.rewrite` returns `(text, how)`; `how` in {llm, kept, fallback-thread, fallback-own};
  - `terms(questions)` judges a name per question and merges follow-up first;
  - the cue is from the rewrite (llm/kept) or from the follow-up alone (fallback);
  - tests: topic-switch pair, elliptical pair, each failure mode → fallback, the cap, no sleep on 429;
  - mutants: thread always appended; cue from the joined text; name judged on the joined text.
- **SYS-141:** `vs = self.vs_l2` once; stub test whose position lookup swaps `vs_l2`.
- **SYS-137:**
  - `get_existing_sitemap_level_pairs` gets a sibling that returns the stale `(sitemap_id, 2)` pairs; `save_chunk_data` deletes those pairs' rows and vectors (reuse the SYS-54 delete path) before inserting;
  - integration test with a 200-word L2 row.
- **SYS-138/112:** offline candidate dumps first (`probe_rag_rank_breakdown.py`), then the smallest change that meets both Done-whens.
