# ADR-015: Shared store-repair steps live in `newscrawler/tools/store_repair.py`; scripts never import scripts

**Status:** Accepted 2026-10-12 (owner approved the design)
**Date:** 2026-10-12
**Feature:** qa-second-pass-fixes-2026-10-12 (DBT-67 #325)
**Author:** 10x-Team (Architect + Staff Engineer)

## Context
Four production-write scripts share one repair sequence. They put `scripts/` on `sys.path` and call each other's private helpers:
- `rechunk_stale_chunks`;
- `settle_out_of_scope_links`;
- `drop_oversized_queued_chunks`;
- `repair_boilerplate_bodies`.

The sequence is: refuse while the crawl runs → resolve the deadline once → backup → delete vectors → one SQL transaction → re-chunk per block → recount. The copies have already drifted, which is how SYS-111 happened (a deadline resolved twice).

## Decision
1. Move the shared steps, with public names and unchanged behaviour, to `newscrawler/tools/store_repair.py`, next to `run_lock.py`:
   - `crawl_running`, `faiss_dirs`;
   - `parse_until`, `too_close`;
   - `backup`, `delete_vectors`, `rechunk`;
   - the constants `BACKUP_DIR`, `MIN_FREE_GB_FOR_BACKUP`, `MIN_RUN_MINUTES`, `DEFAULT_BLOCK`.
2. `rechunk_stale_chunks.backup_l2` uses the module's free-disk guard instead of its copy.
3. Entity-mention recounting gets a callable function. `settle_out_of_scope_links` stops running another script's CLI.
4. Scripts keep their CLI, dry run, target selection and report. No script imports another script; a unit test enforces this.
5. `repair_boilerplate_bodies` re-exports nothing. Its tests and the mutant registry are pointed at the module.

## Alternatives Considered
| Alternative | Pros | Cons | Why not |
|---|---|---|---|
| Keep importing `repair_boilerplate_bodies` but make its helpers public | Smallest diff | Scripts still import scripts; `sys.path` hacks remain | Leaves the toolkit without a home; the next script is a fifth copy |
| A base class / template method for "a repair run" | Enforces the order | Four scripts differ in their middle steps; inheritance hides the sequence | Functions are enough; the order stays readable in each `_apply_locked` |

## Consequences
- **Positive:** one implementation per step; the next repair script imports a module, not a script.
- **Negative:** a wide but mechanical diff; the mutant registry and test patch targets move.
- **Risk:** `test_run_lock`'s writer discovery must still see every write path. It is re-run, and the scripts keep calling `refused_by_run_lock` themselves.
