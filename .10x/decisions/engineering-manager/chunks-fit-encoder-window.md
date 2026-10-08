# Chunks fit the encoder window (SYS-109) -- plan

Owner: "design it and fix it directly after the design is finished" (2026-10-08 ~18:20 WIB).

| # | Task | Done when |
|---|---|---|
| 1 | DBT-64 ticket; migration + migrate.py; apply to the test DB (suite) | integration green; `migrate.py` shows it pending on prod |
| 2 | Chunk constants 80/20/40; chunker tests | unit green; windows ≤ 80, overlap 20, trailing merge kept |
| 3 | `rechunk_stale_chunks.py` L2-only, `--all`, `--resume`, ANALYZE; unit + integration tests | L1/mentions untouched in the live test |
| 4 | Mutants for 2-3; full suites | killed; unit + integration green |
| 5 | Docs (CLAUDE, OPERATIONS, EXPERIMENTS), state, commit | clean diffs |
| 6 | Production: dump → migration → `--all --apply --until 06:15` after the 19:00 crawl | SUMMARY failed 0 |
| 7 | Verify: store check, L2 > 80 words = 0, replay probe, latency | numbers on SYS-109 |

**Window:** the 19:00 crawl holds the lock until about 20:15. The rebuild (~6-8 h) runs overnight; the 21:00 extraction yields (the key is blocked anyway); it stops at 06:15 before the 07:00 crawl and resumes in the next free window if needed.
