# Design: dev fixes of QA's second pass (2026-10-12)

**Approved:** owner, 2026-10-12 ("Approve all").
**Tickets:** SYS-138 #317 (sent back), SYS-143 #326, SYS-144 #327, SYS-145 #328, DBT-69 #330, DBT-68 #329, DBT-67 #325.
**Inputs:** `.10x/reviews/2026-10-12-qa-report-2.md`, QA's `scripts/experiments/qa_2026_10_12b/`, the live probe below.

## Pre-design measurement (production, read-only, no model call)
`probe_week_window_lead.py`, 2026-10-12 afternoon. Keyword coverage of the window's cards:

| Question | Window cards' coverage | Off-topic lead |
|---|---|---|
| KPK minggu ini | 0.57-0.61 (on topic) | none |
| IHSG pekan ini | 0.55 (on topic) | none |
| Danantara | Primbon piece, 0.00 | yes (card 1) |
| Harvey Moeis | Pemko Medan piece, 0.00 | yes (card 1) |
| Pertamina | TNI/MBG motor case, 0.63 (no `pertamina`) | yes (card 1) |
| Garuda | BSA DKI 0.15, karhutla 0.47 | cards 2-5 |

Consequences:
- A coverage gate at `RAG_MIN_KEYWORD_COVERAGE` (0.6) drops KPK and IHSG, the ticket's own Done-when.
- A final-score margin cannot separate Danantara: Primbon is 0.402, near the 5th Danantara card.
- Whether the paragraph holds the question's **subject word** separates every case.

## Design
1. **SYS-138: a subject gate for the window's lead (ADR-013).**
   - A window hit leads only when it passes the floor **and** holds the question's subject in the same `to_tsvector('simple')` the keyword half uses.
   - The subject is one of `KeywordQuery.names` when the question has names, else one of its `anchors`.
   - A keyword-retrieved hit already satisfies this (the FTS rule demands a name / anchors), so the check runs only for semantic-only window hits that pass the floor: one round trip, only on the window path.
   - A question with no keyword query (`kq is None`) has no subject to test: the floor alone decides, as in ADR-012.
   - Hits that fail the gate are not dropped. They rank in the unwindowed list as before.
   - Only gated hits count toward a full week (`RAG_TOP_K`).
   - The fill, logging (`window=7d` / `7d+N`) and the reader-filter precedence are unchanged.
2. **SYS-143.** `followup.check` returns None for a refusal (starts with *maaf*; *saya tidak dapat/bisa*; *sebagai (AI|asisten|model)*; English *sorry / I cannot*) or a list (a leading `1.`, `-`, `*`, `•` item). It is still counted (decision 7 of ADR-010; DBT-69 adds the test).
3. **SYS-144.** `_NOT_REFERENCES` gains an explicit list of *-nya* adverbs without a referent. No `se-…-nya` pattern: *sesudahnya*, *setelahnya* and *sebaliknya* do point back. Accepted cost: "Apa langkah selanjutnya?" is retrieved on its own words when the rewrite cannot run. Checked against the 7 elliptical pairs' fallback (≥ 33/35).
4. **SYS-145 (ADR-014).** A rewrite equal to the follow-up (`kept`) for a follow-up that `refers_back` is retrieved like the fallback thread: own words + thread, terms per question, cue from its own words. Logged `rewrite=kept-thread`. It needs no call or prompt change, and it depends on (3).
5. **DBT-69.** Three tests: `--source` scope, the 80/81-word boundary (integration, test DB), and an unusable reply that is still counted (unit).
6. **DBT-68.** Delete the second `TestSoftDeadline`. Add an AST hygiene test: no repeated top-level name per test module, and no repeated method per class.
7. **DBT-67 (ADR-015).**
   - The shared repair steps move to `newscrawler/tools/store_repair.py` with public names: crawl-running refusal, FAISS dirs, deadline parse/too-close, backup, delete vectors, rechunk. `recount_entity_mentions` gets a callable entry point.
   - No behaviour change: the three scripts' tests pass apart from import paths, `test_run_lock` still finds every writer, and the affected mutants are retargeted and killed.
   - Done last, in its own commit.

## Verification
- Unit and integration suites, QA's `test_qa_fixes.py` (the expected failures should go; the Danantara fixture defect is explained to QA), and new mutants per ticket against a green baseline in a scratch worktree.
- Live, read-only: `probe_week_window_lead.py`, `probe_recency_tuning.py` / `probe_rag_rank_breakdown.py` replay; the follow-up probes with `--fallback` (the LLM-path ones only if the SumoPod key works, a few cents).

## Out of scope
- SYS-112 (abbreviations), SYS-142 (overlap tails), SYS-139 (scheduled evidence).
