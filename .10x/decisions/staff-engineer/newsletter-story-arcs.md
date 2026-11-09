# Newsletter story arcs: staff-engineer standards (2026-10-13)

ADR-016 (arcs) + ADR-017 (core seams). Tracker #336. Source: the `/deepen` review, `memory/HANDOVER-2026-10-13-2137.md`.

## Cross-cutting rules for every ticket in #336
1. **One home per concern.** These are enforced by grep tests in DBT-72/73/75:
   - fact checks: `core/source_check.py` only;
   - LLM JSON + retry: `core/llm_json.py` only;
   - reader strings: `core/newsletter_copy.py` only (SYS-84);
   - no `ng.*`/`ne.*`/`ss.*` assignment in `scripts/`.
2. **A pure move is proven, not asserted.** A refactor ticket keeps the old output byte-identical on a fixture day (summarizer stubbed), or a replayed stat within ±2 points. Mutants that target moved functions are retargeted, never deleted.
3. **Keep the call shapes.** `unsupported_number(text, source)` survives as the wrapper, so the RAG and editor call sites change only their import. `ask_json`'s `check(data, attempt)` carries the existing retry leniency (`drop_long_poin`, `demote_strays`) through `attempt`.
4. **Side effects only in `generate()`** (DBT-75). `plan` and `build` never write files or rows; the replays use them directly.
5. **Read-only FAISS** (DBT-74, SYS-147): load through `index_generation.load_index`, never save. The script keeps `refused_by_run_lock`, and `test_run_lock` discovery must still pass.
6. **Feature flag exactness.** With `NEWSLETTER_ARCS=0` (`POLICY_TODAY`), the edition and the editor prompt are byte-identical to today's (SYS-149).
7. **Dates in prose.** `source_check.dates_in` is the only parser. Code renders reader dates from `newsletter_copy` tables, never `strftime("%B")` (SYS-81).

## Reuse map
| Need | Use | Not |
|---|---|---|
| number/date/subject check | `source_check.*` (DBT-72) | `story_summary` privates |
| content words / names | `story_words` (SYS-86) | a new tokenizer |
| LLM call + retry | `llm_json.ask_json` (DBT-73) | a local loop |
| summarizer + usage accounting | `summarizer.build_summarizer(usage=)` (ADR-001) | a direct HTTP client |
| NEWS_L1 search | DBT-74's read-only load + SYS-147's adapter | `init_crawler()` |
| headlines/dates of past items | `SQLAlchemyNewsletterDataSource.get_timeline_rows` | FAISS metadata (ADR-005, SYS-91) |

## 2026-10-18: standards for QA's 10-18 queue (ADR-020)
- **One definition of a verb-like word.** `source_check` keeps `_VERB` / `_PREFIXED_NOUNS` for SYS-158. ADR-020's
  purpose rule and SYS-177's "no verb in between" need the same idea, so it moves to `story_words.is_verb(word)` and
  both modules call it. No third copy.
- **One root function.** SYS-193 needs `causal_check._root` in `source_check`. It moves to `story_words.root` with
  the circumfix rule, and `causal_check` imports it. A dependency from `source_check` on the causal gate would be
  the wrong way round.
- **Registry hygiene.** Every registry entry whose old line this change rewrites is retargeted in the same commit
  (DBT-80's hygiene test fails on a stale one). Every new rule gets one mutant, named after its ticket.
- **Tables pinned to the prompt.** The causal table and PROMPT's list stay one set (SYS-184's test). The cue verbs
  and the end openers are docstring-listed beside their regex.
- **Copy rules.** Problem strings stay Indonesian and live where the other `parse` problems do. No reader string
  changes.
