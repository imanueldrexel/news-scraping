# Design: story-arc fact gates measured by coverage (SYS-196 #426)

**Date:** 2026-10-21 · **Status:** approved in brainstorming (owner, 2026-10-20/21); awaiting spec review
**Feature slug:** `gate-lexicon`

## 1. Problem
The arc fact gates decide *whether* to check a sentence from closed, hand-typed word lists:

| Gate | Where | What it triggers |
|---|---|---|
| cause | `causal_check._KINDS` (`CAUSAL`) | a causal link needs a quote that states it, same direction |
| hedge | `causal_check._HEDGE` | a hedged source link backs no flat claim |
| denial | `causal_check._DENIAL` | a denied source link backs no flat claim |
| end | `source_check._END_OPEN`, `_DEADLINE`, `_SPREAD` | a prose end point must be stated as an end by a source |
| plan | `story_arc._FUTURE_VERB` | a running time span in the latar is judged as a schedule |

A form that is not listed passes unchecked. Each send-back added the forms QA tested, and the next held-out set failed again (QA 2026-10-19 and 2026-10-20). The forms left out are more frequent than the ones added: tertekan 1,320 articles vs dipacu 87; rampung pada 401 vs dihentikan pada 56. The owner agreed on 2026-10-20 that this fixes tickets, not the class.

## 2. Decisions taken in brainstorming
1. **Done means measured coverage.** At least 95% recall on a held-out labelled sample from our own corpus; the remaining misses are a stated, accepted risk. "Zero false facts" was not chosen: it needs a semantic check.
2. **Scope:** the five arc fact gates above. The web follow-up's -nya lists (SYS-144..146) are out of scope; their misses cost retrieval quality, not a printed fact.
3. **Labels:** DeepSeek (SumoPod, thinking off, as for SYS-36's gold set), plus the owner's spot-check of 50 per category.
4. **Approach C:** a data lexicon of roots with generated word forms now. A per-category trained classifier is added only if a category's live recall stays under target (section 7).

## 3. Components

### 3.1 `newscrawler/core/gate_lexicon/` (data + loader)
One UTF-8 file per category, rows of tab-separated fields; `#` starts a comment.
- `cause.tsv`: `root  forms  direction  flags`. For example:
  - `tekan  meN,di,ter  auto  purpose_exempt`;
  - `picu  meN,di,pe-noun  auto`;
  - `karena  literal  backward`;
  - `bermula dari  literal  backward`.
- `hedge.tsv`, `denial.tsv`, `plan.tsv`: `root  forms  flags`. Phrases are `literal` ("tidak benar", "paling lambat").
- `end.tsv`: `root  forms  kind`, where kind is `end` | `deadline` | `spread`. `spread` marks the verbs of extent before a place.
- `exempt.tsv`: surface forms that are never a claim of that category, each with its condition. Per the owner's #401 decision, bare "terdampak"/"terimbas"/"terpengaruh" are exempt only when no noun phrase follows them.
- `MANIFEST.json`: each file's sha256 and the lexicon version. `load()` raises `LexiconError` (service start fails, as `ProbeArtifactError` does) when a file is missing, malformed, or mismatched, or when a category is empty. An empty list is an open gate and must never be a silent default.

### 3.2 `gate_lexicon/morph.py`: the word-form generator (pure)
`forms(root, classes) -> {surface: form_class}`. The classes:

- **meN-**, with nasal assimilation:
  - me- before l/m/n/r/w/y/ng/ny;
  - mem- before b/f/v, and before p, which drops;
  - men- before d/c/j/z, and before t, which drops;
  - meng- before vowels/g/h/kh, and before k, which drops;
  - meny- before s, which drops;
  - menge- before a one-syllable root.
- The suffixed forms: **meN-…-kan**, **meN-…-i**, **di-**, **di-…-kan**, **di-…-i**.
- **ter-** (te- before r) and **ber-** (be- before r).
- **pe-noun**: pe(N)-, pe(N)-…-an, -an.

Rules:
- Each row opts into its classes. **Noun classes are off unless listed**, so bare "target", "janji" and "rencana" can no longer cue a schedule (#420).
- **Direction (cause) is `auto` by form.** di-/ter- forms are passive: effect <word> cause, BACKWARD ("IHSG tertekan aksi jual"). meN- forms are active: FORWARD ("aksi jual menekan IHSG"). An explicit direction on a row overrides.
- A generated form that collides with a common word of another meaning goes in `exempt.tsv` with a test. Each such form is found from the dev split's false triggers, never guessed.

### 3.3 The gates read the lexicon
- At import, `causal_check`, `source_check` and `story_arc` build their patterns from `gate_lexicon.load()`. The hand-typed `_KINDS`, `_HEDGE`, `_DENIAL`, `_FRAME_WORDS`, `_END_OPEN`, `_DEADLINE`, `_SPREAD` and `_FUTURE_VERB` are deleted. A test forbids a new hand-typed copy, on the model of DBT-72's single-source test.
- `story_arc.PROMPT`'s list of causal words is generated from the lexicon. The existing "prompt = table" test stays.
- **Unchanged:** sentence splitting, half matching, quotes, negation agreement, the anaphor rule, the purpose-verb exemption (now the `purpose_exempt` flag), the end-point subject check, and the agenda/latar time logic. Only *which words trigger* moves to data.

## 4. The gold sample

### 4.1 Pools
- **Arc prose:** every sentence of the hari_ini/latar/agenda/sekilas fields in the stored arcs (`digests/preview/arcs*/`, the arc trace of each live edition since 2026-10-13). All are labelled.
- **Source:** 10,000 sentences drawn uniformly at random from `articles.extracted_text` of the 60 days before the draw date, split by `causal_check.sentences`. The draw uses a fixed seed and is not selected by any word list.

### 4.2 What each category is measured on
Each gate only acts in a context:
- **cause:** all sentences of both pools.
- **hedge, denial:** the sentences labelled cause=yes. A hedge or denial word outside a causal link changes nothing.
- **end:** all sentences. Spatial "hingga X" is labelled end=no.
- **plan:** the clauses that hold a running time span (`awal / pertengahan / akhir <month>`, `<month>`, "pekan ini", ...), found by `source_check`'s existing time patterns.
  - The gate itself runs on the latar only. The arc pool's latar clauses are enforced when not `thin`.
  - The source pool's clauses are the same language, used for more positives.

### 4.3 Labels
- One DeepSeek call per batch of 50 sentences. JSON per sentence: for each category, `{"yes": bool, "trigger": "<the words, as written>"}`, with the category definitions above.
- Cost estimate: under $0.50. Hard cap: $1, through `api_usage_log` like any call.
- **Thin categories:** a category with fewer than 50 positives in a pool draws further random batches of that pool until 50 positives or the cap. If still under 50, the category is marked `thin` for that pool: reported, not enforced.

### 4.4 Spot-check
- `tests/fixtures/gate_gold/handcheck_<category>.csv` holds 50 random labelled sentences per category, half of them positives.
- The owner marks agree/disagree, and `scripts/gate_gold.py score-handcheck` scores it. Under 90% agreement for a category means its definition is rewritten and that category relabelled before use.

### 4.5 Storage
- `tests/fixtures/gate_gold/<category>.jsonl` rows: `id, pool, text, origin (sitemap_id or arc file + field), label, trigger, split`. Plus `MANIFEST.json` (sha256, seed, draw date, model, prompt hash).
- Split: 70% `dev`, 30% `heldout`, by a hash of the id. QA owns `heldout`. Dev tooling may print dev-split misses only. The heldout misses are printed only by QA's coverage report.

## 5. The coverage test (unit, offline)
`tests/unit/test_gate_coverage.py`, per category, on the held-out split:
- **What "fires" means:**

  | Category | Fires when |
  |---|---|
  | cause | `causal_spans` finds a span on the sentence |
  | hedge | the span is `hedged` |
  | denial | the span is `negated` by a denial |
  | end | `end_points` (prose) / `_stated_ends` (source) is non-empty |
  | plan | the clause's span is judged a schedule |

- **Recall** = fires on positives / positives. It must be >= 0.95 on the two pools pooled, and >= 0.95 per pool for each pool that is not `thin`.
- **False triggers** = fires on negatives / negatives. The rate must be <= the rate measured on the ported lexicon (step 1) + 0.01 absolute. This keeps coverage from being bought with arc refusals (#425).
- On failure, the message lists the missed trigger words with counts. Only the dev split's misses are shown to dev tooling.

## 6. Rollout
1. **Port, no behaviour change.**
   - Today's lists move into the lexicon files as `literal` rows.
   - The equivalence test: the compiled patterns accept exactly today's forms, the whole unit suite passes unchanged, and every gold sentence gets the same fires/not verdict as on the code before.
   - The baseline false-trigger rates are recorded in the MANIFEST.
2. **Word forms on.** `literal` rows that are a root plus affix become root rows with classes. Re-measure on the dev split; collisions found go to `exempt.tsv` with tests.
3. **Grow from the dev split.** The dev adds roots (never single forms) that the dev split's misses show, until the held-out recall and the false-trigger budget hold.
4. **Before merge:**
   - `scripts/experiments/sys152/recheck_causes.py` on the stored replays shows no new false refusal beyond the budget;
   - QA watches 3 live editions (NEWSLETTER_ARCS=1): the refusal counts per reason are not above their last-week mean + 1 sd.

The open defects:
- **Instances of this work:** #413, #414, #415, #417, #419, #420. QA closes each when its own failing test passes *and* the coverage test passes.
- **#418 is split.** Its verbs of extent ("mengular", "merendam") become `spread` rows here. Its "dari X hingga Y" range is code, an ordinary fix.
- **Ordinary tickets, outside this design:** #416 (anaphor `_lent`), #424 (the year check). #401 is implemented inside step 3 as an `exempt.tsv` condition plus the gated forms. #425 stays separate.

## 7. Monitoring and the classifier trigger
- `scripts/gate_gold.py measure --month YYYY-MM` labels the month's new arc prose (all of it, ~150-250 sentences, < $0.10) and prints recall per category against the lexicon of that day. QA runs it in the first week of each month and records the numbers in EXPERIMENTS.md.
- A category under 0.95 recall in **two consecutive months** gets a ticket for its classifier. The classifier: an embedding head trained on the gold set; when it says "claim" and no lexicon form fired, the arc is refused, then retried. Not built until triggered.
- Each edition already logs refusals per reason (`_edition.arcs.refusals`); a rise is the first signal of new false triggers.

## 8. Out of scope
- The web -nya lists (`nya_words`, SYS-144..146).
- The end-point subject check (#405, an accepted lexical limit).
- The quote/half matching itself.
- Gates outside the arcs: the summary's number guard and `off_subject`.

## 9. Done when
- [ ] ADR written. The lexicon is ported with the equivalence test green.
- [ ] Gold sample built:
  - both pools labelled;
  - spot-check >= 90% per category;
  - MANIFEST + sha256 in place.
- [ ] `test_gate_coverage.py` green: held-out recall >= 0.95 per category pooled, and per non-thin pool; false triggers within budget.
- [ ] #413, #414, #415, #417, #419, #420: their failing tests pass.
- [ ] The replay check and 3 watched live editions show no refusal rise beyond the budget.
- [ ] The `measure --month` command documented in OPERATIONS.md; the first monthly figure recorded.

## 10. Risks
| Risk | Mitigation |
|---|---|
| Model labels share a blind spot with the lists | Random pool (not list-selected); trigger words written by the labeller; owner spot-check >= 90% |
| Word forms over-trigger (e.g. "dorongan" as a noun, "tekanan" as "pressure") | Noun classes opt-in; false-trigger budget; collisions in `exempt.tsv` with tests |
| Dev overfits the held-out set | QA owns the held-out split; dev tooling prints dev misses only |
| Thin categories (denial in arc prose) | Pooled enforcement; enrichment by more random draws; `thin` reported, not hidden |
| Lexicon file corrupted or edited by hand | MANIFEST sha256; `LexiconError` at start; the list may never be empty |
