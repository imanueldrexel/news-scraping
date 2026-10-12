# Senior-engineer code-quality audit, 2026-10-12

**Scope:** production code in `c69d34d..f7f8672` (SYS-103 keyword search, SYS-104..110 retrieval fixes, SRC-60/61 KUMPARAN, SYS-105/109 re-chunk, SYS-111 deadlines): 16 files, about 1,100 lines, plus the scripts' tests.
**Baseline:** `tests/unit` 2,770 passed, 5 skipped.

## Findings (filed, most severe first)

| Ticket | Sev | Where | What |
|---|---|---|---|
| SYS-140 #322 | P2 web | `web/keywords.py:77` via `query_processor.retrieval_text` | The joined thread makes the first word of each earlier question a "name". Names anchor up to 10% df and are required in every keyword hit. Probe: `kebijakan` (4.8%) becomes a mandatory term in a follow-up. Fix inside the SYS-104 rework. |
| SYS-141 #323 | P3 web | `chunk_faiss_data_source.py:401-433` | `similarity()` maps positions from one `vs_l2` and reconstructs from a re-read `self.vs_l2`. A concurrent `refresh_stale` gives wrong vectors (positions renumber). Its docstring also still states SYS-110's removed `1 - d^2/2`. |
| SYS-142 #324 | P3 pipeline | `core/chunker.py:13-23` | The last overlap window can be almost all overlap (81 words → [80, 21], 1 new word). Measure on the store before fixing; the fix rides the next re-chunk. |
| DBT-67 #325 | tech debt | `scripts/rechunk_stale_chunks.py`, `settle_out_of_scope_links.py` → `repair_boilerplate_bodies.py` | The scripts import each other's private helpers (`sys73._crawl_running`, `_faiss_dirs`); the backup guard is copy-pasted, and one script calls another's `main([])`. The copies have drifted already: SYS-111 was sent back for a deadline resolved twice in one copy and once in the other. Extract `newscrawler/tools/store_repair.py` after SYS-111 lands. |

## What holds up (checked, no action)

- **Dynamic SQL:** `_fts_sql`, `_word_tests`, `_coverage` and `DocFrequency._count` build only fixed fragments. Every word and weight is a bind value, and `lexeme` strips quotes and backslashes; `_TOKEN` cannot produce tsquery operators.
- **Group save retry:** `rechunk_articles` re-saves a failed group article by article. That is safe because `save_chunk_data` dedups on SQL (SYS-17) and FAISS re-finds vectors by key, so there are no duplicate vectors and no skipped rows.
- **Destructive order:** the destructive steps run vectors first, then one SQL transaction. A kill leaves rows without vectors, which the deferred block repairs (SYS-54's order). The deadline guard runs before any backup or delete.
- **KUMPARAN scope:** the rule lives on the crawler (`out_of_scope_reason`) and is applied once in the base `get_news_in_bulk`, and the settle script imports it rather than re-deriving it.
- **Chunker merge:** SYS-105's backward merge happens before the split, so the 80-word cap still holds.

## Standing observations (no ticket; principles in `decisions/senior-engineer/_index.md`)

- **History in comments.** Many comments narrate what the code *used to* do and which ticket changed it. SYS-141's docstring shows the cost: a comment left describing the bug after the fix. A comment should state the invariant, with the ticket ID as a pointer. The before/after story belongs in the commit message and EXPERIMENTS.md.
- **Names that outlived their meaning.** `RAG_BM25_WEIGHT` weighs an IDF coverage (ADR-006), and `import repair_boilerplate_bodies as sys73` names a module after a ticket. Rename them when the code is next touched: an env alias for the setting, and DBT-67 for the import.
- **Untested seams.** Each of the three defects sits where two pieces meet (thread joining × name detection, reload × read, split × short-tail rule). Each piece's own tests pass. Mutation testing finds a fix that nothing guards, but not a seam that nobody wrote a test for. When a change feeds new input into an existing function, add one test of the composed path.
