# Newsletter story arcs: architecture (2026-10-13)

Status: **Accepted 2026-10-13** (ADR-016). Tracker #336; P0 SYS-147 #337 thread finder, SYS-148 #338 arc writer, SYS-149 #339 edition stage, SYS-150 #340 replay + A/B (ship gate); P1 SYS-151 #341 story memory, SYS-152 #342 causal check. Requirements: `.10x/decisions/product-manager/newsletter-story-arcs.md`. Evidence: EXPERIMENTS.md "2026-10-13 — Newsletter story arcs".

## Requirements (from PM, owner-aligned)
**Functional**
- The edition's 3-4 top stories are written as pure prose (no labels):
  - today's change first;
  - the back-story from the past ≤ 30 days, with dates;
  - a closing look-ahead only when an article states it.
- A story with no history gets a "why it matters" paragraph instead.
- Every number, date and look-ahead is traceable to a source text. Causes are attributed.
- A replay harness produces blind A/B pairs (today's edition vs arcs) for the owner, plus a hand-check sheet.
- **Rollout (owner, 2026-10-13):** after the A/B passes, the arc edition replaces today's. `NEWSLETTER_ARCS=0` returns to today's format without a code change.

**Non-functional**
- Edition ≤ 1,200 words.
- Newsletter ≤ $0.05/day.
- The 12:00 job stays well inside its slot (today 7 min).
- No new production write path (no migration in P0).
- Reader strings in `newsletter_copy.py`.
- The archive digest is unchanged.

## Landscape (verified 2026-10-13)
- **NEWS_L1 is already in memory in the 12:00 job.** `run_scheduled_newsletter.py` → `init_crawler()` → `DataFlowRepositoryImpl` → `ChunkFAISSDatasource` loads L1 (1.4 s) and L2 (10 s) (log `scheduled_newsletter_2026-10-13_1200.log`). Thread search therefore costs no load and no extra memory. It is a read, so the run lock (OPS-26) and generation check (SYS-53) are not involved.
- **Today's L1 vectors are already in memory.** `NewsletterGenerator.generate` encodes every article's L1 text once (`vectors`) for clustering; each cluster's centroid is free.
- **Guards exist to reuse** in `story_summary.py`: `unsupported_number`, `_date_in`, `off_subject`, `words`, `_json_object`, plus `story_words` (SYS-86).
- **The editor's rule check falls back often.** `newsletter_edition.choose` fell back to the deterministic picker on 2 of the last 6 days (10-08, 10-12: `["rules","rules"]`), and its first try is refused on most days. Its rules are re-derived here for 3-4 picks anyway.
- **History lives on the DB side:**
  - headlines, sources and dates come from `sitemaps`, not FAISS metadata (the RAG rule, ADR-005/SYS-91);
  - the L1 text is `chunks.text_content` at `chunk_level = 1`;
  - some KONTAN L1 texts begin with a "Reporter: … | Editor: …" line, which is stripped before quoting.

## Options
| | **A. In-edition arc stage (recommended)** | B. Precomputed thread store | C. LLM-written search queries |
|---|---|---|---|
| Shape | After the editor picks the top stories: find the thread in NEWS_L1, then one arc-writer call per story; nothing persisted except the edition's own stats JSON | A nightly job links each day's clusters into persistent `story_threads` (table + migration); the newsletter reads threads | The model writes a search query per story; hybrid keyword (SYS-103 module) + vector retrieval |
| New infra | 2 modules, 0 tables | table, migration, job, thread maintenance (merges, splits) | an extra call per story, a keyword path in the newsletter |
| Recall on concept stories (daya beli) | weak (probe: loose at 0.70) | same, plus maintenance | better |
| Fits P1 story memory | yes: P1 reads past editions' `_edition.stories` JSON | natively | n/a |
| Failure surface | one stage, each failure falls back to today's summary in prose | a stale or wrong thread persists and repeats every day | nondeterministic retrieval, harder replay |
| Why / why not | Simplest; uses only what the 12:00 job already holds; reversible by a flag | Premature: owner put story memory at P1, and a thread store is a one-way door (schema + data) | Probe shows vectors suffice for 4/6; revisit for concept stories if the A/B's arc precision < 90% |

## Recommended design (A)

### Data flow
```
generate(date)
 ├─ articles + L1 vectors (as today) ─► sections ─► per-cluster summaries (unchanged)
 └─ newsletter_edition.build(...)
      ├─ candidates ─► editor choose(): utama 3-4   (rules re-derived, below)
      ├─ [NEWSLETTER_ARCS=1] for each utama:
      │     centroid(terkait L1 vectors)
      │       ─► thread_finder.find_thread(centroid, date, exclude=today's ids, search, lookup)
      │            NEWS_L1 search ─► window [date-30, date) ─► floor ─► 1 item/day ─► ≤ 12, chronological
      │       ─► story_arc.write_arc(summarizer, today's shown articles, timeline)  (≤ 2 calls)
      │            guards ─► StoryArc | None (fallback: today's StorySummary as prose)
      ├─ Sekilas (unchanged rules; the 6 largest stay guaranteed)
      └─ render: pure prose ─► budget trim (Sekilas first, then 4th arc) ─► markdown
```

### Components
1. **`newscrawler/core/thread_finder.py`** (new, pure, no I/O of its own)
   - `TimelineItem(sitemap_id, day: date, source, headline, opening, cosine, day_volume)`.
   - `find_thread(centroid, day, exclude_ids, search, lookup, *, days=ARC_LOOKBACK_DAYS(30), floor=ARC_FLOOR(0.70), fetch_k=ARC_FETCH_K(3000), max_items=ARC_MAX_ITEMS(12)) -> List[TimelineItem]`. Steps:
     1. `search(vec, k) -> [(sitemap_id, posted_at:int, cosine)]`;
     2. keep `day - days <= posted_at < day`, `cosine >= floor`, not in `exclude_ids`;
     3. group by day;
     4. for each day keep the best-cosine item, and its `day_volume` (items that day over the floor);
     5. keep the `max_items` days with the highest best cosine, **always including the earliest qualifying day** (the arc's start);
     6. `lookup(ids)` gives headline, source and opening from the DB (opening = L1 text with the byline line stripped, ≤ 300 chars);
     7. return in chronological order.
   - **No peeking:** the window ends before `day`, so a replay of a past date never sees later news even though the index holds it.
   - The adapters live with their owners:
     - `search` wraps `ChunkFAISSDatasource.vs_l1.similarity_search_with_score_by_vector` (cosine = `1 - d/2`, SYS-110) and reads `sitemap_id`/`posted_at` from metadata;
     - `lookup` is a new `SQLAlchemyNewsletterDataSource.get_timeline_rows(sitemap_ids)` (one SELECT, sitemaps ⋈ chunks L1 ⋈ articles).
2. **`newscrawler/core/story_arc.py`** (new, mirrors `story_summary.py`)
   - `PROMPT`: the PM draft in the PM decision file, verbatim, with a past-day worked example chosen in replay.
   - Index space: today's articles `0..n-1`, timeline `n..n+m-1`.
   - `StoryArc(judul, hari_ini, latar, agenda, sekilas, terkait, tidak_terkait, alur, demoted_alur=0, agenda_dropped=False)`.
   - `LIMITS = {judul: 12 (ask 10), hari_ini: 60, latar: 70, agenda: 20, sekilas: 15}`.
   - `write_arc(summarizer, shown, timeline, rejections) -> Optional[StoryArc]`: first answer, one retry with the refusal detail, then None.
   - **Guards.** REASONS = `json, length, number, date, subject, alur`.
     - *number*: `unsupported_number(hari_ini+latar+agenda+judul, source)` with source = today's `terkait` guard texts + the chosen `alur` items' headline+opening.
     - *date*: every `d/m` or `d <Bulan>` in the prose must be today's date, the date of a chosen `alur` item, or a date stated in a source (`_date_in`; an agenda's "Kamis (15/10)" is in its article).
     - *subject* (SYS-80): today's `terkait` off-subject → refuse first, demote on retry.
     - *alur*: each chosen item must share a name or ≥ 2 content words (`story_words`) with today's judul + hari_ini. First answer: refuse. Retry: demote the item, then re-run the number and date guards on the reduced source. If they fail → None.
     - *empty-history rule*: if `alur` is empty, `latar` may not contain a date other than today's (it is the why-it-matters paragraph).
     - *agenda*: dropped (not refused) when it has no date, number, or scheduled-event word found in a source. Its numbers stay under the number guard.
     - Causal-word attribution is **P1** (PM). P0 measures it in the hand-check sheet only.
3. **`newsletter_edition.py`** (changed)
   - With `NEWSLETTER_ARCS=1` only, the editor prompt and rules for **3-4** utama (`UTAMA_MIN, UTAMA_MAX = 3, 4`). With 0, today's 6-8 rules are unchanged:
     - max 2 per rubrik;
     - **≥ 1** non-finance when one qualifies (`NON_FINANCE_MIN_PORTALS`), scaled from 2-of-6-8;
     - the 6 largest stay guaranteed candidates and Sekilas lines (CTO 2026-10-05);
     - the 60-second block unchanged.
     - The editor rules' refusal rate is reported per day, as today.
   - New stage `arcs(summarizer, choice, cands, search, lookup)`, only when `NEWSLETTER_ARCS=1` and a `search` was given. A standalone generator without the index skips it, and every top story renders from its summary as prose.
   - **Render (pure prose, owner decision 7):**
     - arc: `### judul`, `hari_ini`, a blank line, `latar` (+ `agenda` appended as its closing sentence), meta line;
     - fallback from `StorySummary`: paragraph 1 = `inti` + `poin` joined, paragraph 2 = `mengapa_penting`, meta line.
     - With `NEWSLETTER_ARCS=0`, today's editor rules and renderer are used unchanged (the switch is exact; a unit test compares the output byte for byte).
   - **Budget:** `WORD_BUDGET` 1,200 unchanged. Trim Sekilas first (existing rule), then drop the 4th arc story to a Sekilas line.
   - **Stats:** `_edition.arcs = {built, fallback, refusals: {reason: n}, alur_items, no_history, agenda, demoted}`. `_edition.stories = [{judul, terkait_ids, alur_ids, arc}]` is the P1 hook; it lives in the existing JSON, so there is no migration.
4. **`newsletter_generator.py` / wiring** (changed)
   - `NewsletterGenerator(..., search_l1=None)`. `DataFlowRepositoryImpl` passes an adapter over `chunk_faiss_datasource.vs_l1`.
   - Each shown cluster gets `centroid` (the mean of its articles' L1 vectors, normalised). Only the utama's `terkait` articles' vectors are used for the arc query.
   - `newsletter_copy.py`: the new footer disclosure. No in-story labels exist to add.
5. **Replay harness `scripts/experiments/replay_story_arcs.py`** (new; read-only DB; loads NEWS_L1 via `index_generation.load_index`, no save)
   - Per `--dates`: run the summaries once, then the edition twice (`arcs=0`, `arcs=1`) on the same summaries and editor choice, so the only variable is the arc stage.
   - **Blind:** files `<date>-X` / `<date>-Y` (Markdown + phone PDF) assigned at random; the key goes to `key.json`.
   - **`handcheck.csv`:**
     - one row per `alur` item: date, story, item date, outlet, headline, `same_thread` (blank);
     - one row per prose sentence containing a causal word: `attributed` (blank).
   - **Metrics JSON:** words, arcs built/fallback, refusals by reason, items per story, no-history count, calls and cost, and a repetition share (`latar` sentences of day d that share ≥ 60% content words with day d-1's for the same story).
   - Default A/B set: 2026-10-08..10-12 (consecutive, for repetition). Writes under `digests/preview/arcs/`.

### Failure modes
| Failure | Effect | Handling | Detection |
|---|---|---|---|
| NEWS_L1 not loaded / search raises | no timelines | stage logs once; every utama gets its summary as prose; edition still built | `_edition.arcs.built=0`, operator note |
| Thread finder returns noise | drift into the arc | LLM confirms `alur`; the alur guard refuses then demotes; hand-check ≥ 90% gate | `demoted`, handcheck |
| Arc refused twice | one story falls back | summary-as-prose for that story | `refusals` by reason |
| LLM quota/outage (`stats.stopped`) | no arc calls | arcs skipped like the editor today | existing stopped note |
| Prose exceeds budget | edition too long | Sekilas trim, then 4th arc to Sekilas | `words` |
| Repeated back-story on consecutive days | reader annoyance | P1 story memory | replay repetition share |
| A past date replayed | could leak later news | window ends before the date | unit test |

### Cost and time
- **Per story:** ≤ 2 calls × (~1k prompt + ~2.8k articles + timeline) ≈ 4.5k tokens in, ~0.5k out.
- **Per day:** ≤ 4 stories → ≤ 8 calls, ≤ 40k tokens. At DeepSeek prices that is well under $0.01, inside $0.05/day with the existing ~95 calls.
- **Time:** search is milliseconds per query over ~115k L1 vectors, and the calls add ~30-90 s to a 7-minute job.

### Testing
- **Unit:**
  - `thread_finder` with a fake `search`/`lookup`: window, floor, one-per-day, earliest kept, no peeking, exclusion;
  - `story_arc`: each refusal reason, demotion, agenda drop, empty-history rule, index spaces;
  - render: exact `arcs=0` equality with today's output, prose fallback, budget trim.
- **Mutants:** registered per guard (`qa_mutation_runner.py`).
- **Integration:** `get_timeline_rows` on `newsaggregator_test`.
- **Acceptance:** the replay A/B plus the hand-check (PM success criteria 1-4).

### Migration path
1. Code lands with `NEWSLETTER_ARCS=0` (default): production output is unchanged.
2. Replay A/B, then the owner's verdict.
3. On pass: set `NEWSLETTER_ARCS=1` in `.env`, and the next 12:00 run delivers arcs; the Phase 4 diary starts.
4. Rollback: set the flag to 0.
5. P1 story memory reads `_edition.stories` of the last 7 digests. It needs no schema change unless measurements say otherwise.

## Open for SDE (defaults chosen, change only with evidence)
- `ARC_FLOOR` 0.70, `ARC_MAX_ITEMS` 12, `ARC_FETCH_K` 3000: tune on the replay.
- The ≥ 1 non-finance rule for 3-4 slots replaces `MIN_NON_FINANCE = 2`. It is a scaled default, not an owner decision: flag it in the ticket.
