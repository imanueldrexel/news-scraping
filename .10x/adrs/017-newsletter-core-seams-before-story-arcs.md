# ADR-017: Newsletter core seams before the story arcs: one source-check module, one ask_json helper, a plan/build split, and the newsletter's own composition root

**Status:** Accepted 2026-10-13 (owner: "make the prioritisation based on your suggestion"). Amends ADR-016 (premise of decision 1's "NEWS_L1 is already in memory").
**Date:** 2026-10-13
**Feature:** newsletter-story-arcs (tracker #336)
**Author:** 10x-Team (Architect + Staff Engineer)

## Context
A `/deepen` review of the newsletter path (`memory/HANDOVER-2026-10-13-2137.md`) found that ADR-016's arc stage would sit on four weak seams:
1. **Fact checks inside the summary module.** The number/date/subject checks (`story_summary.py:170-256`) are imported by the editor and the RAG answer. Written-out dates are unchecked (SYS-153 #343), yet the arcs' main safeguard is a prose-date rule.
2. **The LLM loop written per call site.** The ask → check → retry → fall-back loop exists twice, with different error policies; JSON extraction exists three times. The arc writer would be a fourth copy.
3. **No side-effect-free core.** `generate()` reads, calls the LLM, renders, writes files and saves the row in one method. The replays monkeypatch module globals to observe it. SYS-150's A/B needs one plan and two builds.
4. **The 12:00 job builds the whole crawler.** That loads NEWS_L2 (~7.6 GB) and e5-large (2.2 GB), which the newsletter never uses, and ADR-016's "NEWS_L1 already in memory" was a side effect of it.

## Decision
1. **`core/source_check.py`** (DBT-72 #344) is the only place generated text is compared with sources: numbers by value, dates in every form (`dates_in`), and subject anchors. The summary, editor, arc writer and `web/answer.py` import from it.
2. **`core/llm_json.ask_json(summarizer, prompt, check, retries=1, on_error=)`** (DBT-73 #345) is the only ask/check/retry loop in the newsletter. It returns `Outcome(value, reasons, calls, answers)`. Today's two error policies become an explicit argument.
3. **The newsletter gets its own composition root** (DBT-74 #346): SQL, MiniLM, NEWS_L1 via a read-only `load_index`, and the summarizer, keeping the `crawl_log` bracket and the run-lock refusal. NEWS_L1 is loaded explicitly (~1.4 s), not inherited from `init_crawler()`.
4. **`plan(date)` / `edition.build(plan, …)` split with a typed `Story`** (DBT-75 #347). `generate()` is the only method with side effects, and replays call `plan` once and `build` as often as needed.
5. **`EditorPolicy`** (inside SYS-149 #339): one record generates both the editor prompt's numbers and its rules, and `NEWSLETTER_ARCS` selects the policy.
6. **Order:** DBT-72 → DBT-73 → SYS-147 + DBT-74 → SYS-148 → DBT-75 → SYS-149 → SYS-150. The structured-edition model (Markdown re-parsed by the PDF and Telegram) is deferred.

## Alternatives Considered
| Alternative | Pros | Cons | Why not |
|---|---|---|---|
| Build the arcs first, refactor after | Arcs reach the owner sooner | A 4th guard/loop copy; the arc date rule built on the SYS-153 gap; the replay built on monkeypatching, then rewritten | The arcs' risk is trust, and SYS-150 is the gate; both sit on these seams |
| Refactor everything incl. a structured edition model | The cleanest end state | The highest effort; the PDF/Telegram renderers are stable today | Deferred until SYS-150's PDF check shows a need |
| Keep `init_crawler()` for the 12:00 job | No change | ~10 GB loaded for nothing on a memory-tight host; hidden dependency for the arcs | Cheap to fix while SYS-147 adds the NEWS_L1 dependency |

## Consequences
- **Positive:**
  - the arc writer is small: a prompt plus a check function;
  - the date gap is fixed for summaries, editor and web answers at once;
  - replays stop patching globals;
  - the 12:00 job's memory drops by ~10 GB (to be measured in DBT-74).
- **Negative:**
  - arcs reach the owner later, by 4 tech-debt tickets (~2-3 dev sessions);
  - wide but mechanical diffs; mutant registry targets move.
- **Risks:**
  - a behaviour change hidden in a "pure move". Every DBT ticket's Done-when requires byte-identical output on a fixture day, or a replayed stat within ±2 points.

## Dependencies
- Constrains SYS-147/148/149/150 (their re-scope sections, 2026-10-13).
- ADR-016 stands except for the "already in memory" premise.
