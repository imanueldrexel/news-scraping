# Newsletter story arcs: architecture (2026-10-13)

Status: **Accepted 2026-10-13** (ADR-016). Tracker #336; P0 SYS-147 #337 thread finder, SYS-148 #338 arc writer, SYS-149 #339 edition stage, SYS-150 #340 replay + A/B (ship gate); P1 SYS-151 #341 story memory, SYS-152 #342 causal check. **Re-scoped 2026-10-13 by ADR-017:** DBT-72 #344 source_check, DBT-73 #345 ask_json, DBT-74 #346 newsletter-only setup (NEWS_L1 loaded explicitly — the "already in memory" note below describes init_crawler, which the 12:00 job stops using), DBT-75 #347 plan/build + Story; order in decisions/engineering-manager/newsletter-story-arcs.md. Requirements: `.10x/decisions/product-manager/newsletter-story-arcs.md`. Evidence: EXPERIMENTS.md "2026-10-13 — Newsletter story arcs".

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

---

# 2026-10-15: QA rework of the arc guards (SYS-157/158 sent back; SYS-161..164, DBT-77)

No new ADR: every change stays inside ADR-017's seam (checks live in `source_check`, style measures in
`arc_style`, `story_arc.parse` only wires them), and the arc's data flow is unchanged.

## Decisions (dev's calls the tickets left open)
- **SYS-157: "N pekan/bulan/hari lalu" is read with its own span, never as the shorter phrase.**
  One count-ago entry replaces "dua pekan lalu" and "N hari lalu": hari N±1, pekan 7N±3 (N=1 keeps
  sepekan's 7±2), bulan = the calendar month N back. A vague count ("beberapa", "puluhan", "dua puluh")
  is matched and left unread: it occupies the text, so the shorter phrase inside it is never read.
  Why read rather than leave unread: an unread phrase is an unchecked time claim, the hole SYS-157 closed.
- **One phrase finder, two views.** `relative_phrases(text)` (position, phrase; no edition date needed)
  feeds `relative_times(text, today)` (spans) and `arc_style.time_anchors` (SYS-164). Dates are blanked
  length-preserving, so positions hold.
- **SYS-162:** `unbacked_times` takes the stated text of today's `terkait` articles only. Dates the
  chosen items state still back a phrase (they are absolute).
- **SYS-158:** a record's key is the whole time phrase (structured: part + month/tahun/bulan/pekan,
  day + month, d/m, a bare year; else up to 3 words to the next stopword/punctuation). A year after a
  month or a date is dropped from the key: the number/date guards hold it. "N kali berturut-turut" is a
  series. A word ordinal after a me-/di-/ber- verb, or before "belah", is collective; a short list of
  nouns with those prefixes (menteri, diskusi, direktur, ...) stays a noun. Missing a claim costs an
  unchecked count (the pre-SYS-158 state); a false claim costs a retry, so the rule leans to collective.
- **SYS-161:** `source_check.change_claims(text)`: "(bertambah|naik|...) [up to ~8 words] (men)jadi
  [sekitar] N". It passes when a source sentence holding N (by value) holds a change verb, a total word
  ("total", "kumulatif", "akumulasi", "keseluruhan") or a cumulative period ("hingga/sampai/per/
  sepanjang/sejak" + a time: month, date, awal/akhir, tahun, kuartal, periode, kini). Bare "hingga" is
  not one: the 10-11 TRIBUN headline holds "199 ... Kakorlantas hingga Wakabaintelkam". Refused as
  `number`. Applied to every prose field, like the other number checks. Prompt rule 3 says it too.
- **SYS-163: the repeated agenda is dropped, not refused** (`agenda_dropped`): it shares a date with the
  latar/hari_ini and >= 50% of its content words are there. By definition it adds nothing, so a retry
  would spend a call and risk a fallback for no reader gain.
- **SYS-164:** a time anchor = a calendar date or a non-"sejak" relative phrase. `opens_on_time`
  (date or anchor opening; "Pada tanggal/hari", "Pada Sabtu, 3 Oktober," shapes) drives the tie and the
  openings cap; `MAX_LATAR_ANCHORS = 3` beside `MAX_LATAR_DATES = 2`; the metric adds `time_led` and
  `with_3_anchors_or_more`. `opens_on_date` keeps its meaning (calendar only) for `date_led`.

## Failure modes accepted
- Change claim: a source sentence that holds N and an unrelated change verb still licenses it.
- Collective rule: a noun with a me-/di-/ber- prefix missing from the list hides a real claim (unchecked).

# 2026-10-16 (dev): QA's 10-16 queue (SYS-167..170, DBT-79, DBT-80)

No new ADR. Every change stays inside ADR-017's seam: text-vs-source checks live in `source_check`,
style measures in `arc_style`, and `story_arc.parse` only wires them. The arc's data flow is unchanged.

## Decisions
- **SYS-169: an unstated future time is refused as `date` (owner, 2026-10-16), not dropped.** The check is
  the same as for an unstated calendar date. The retry tells the model to write the time the article states, which
  is the prompt's own format ("Kamis (15/10)"), so a real next step survives in the right form.
  - Backed only when today's `terkait` articles state the same future time by key ("minggu depan" = "pekan
    depan", "esok" = "besok", "mendatang" = "depan"). A timeline item's "minggu depan" was written on another
    day (SYS-162's reasoning).
  - **No span backing.** The ticket's optional "a source date in the span backs it" is not taken: with today
    Mon 12/10, any source date this week would back "pekan ini", including the date of an unrelated deadline.
  - Runs on every prose field, like `unbacked_times` (past) and SYS-161: a false "besok" in hari_ini is the same
    error as one in the agenda.
- **The future-time table moves from `story_arc._FUTURE` to `source_check`** (`future_phrases` / `future_key`),
  beside `_RELATIVE`. It is now read by a check (SYS-169) as well as by `_agenda_kept` / `agenda_repeats`, and
  ADR-017 puts checks there.
- **SYS-168 (owner, 2026-10-16): bare "bulan ini" / "tahun ini" are not future times.** They are mostly past
  tense in news and span a whole month or year. "akhir bulan ini" / "akhir tahun ini" are. Added: esok,
  (pekan|minggu|bulan|tahun) mendatang.
- **SYS-170:** a change claim is `<verb> ... (men)jadi | hingga | sampai | ke (angka|level|posisi) N`. "naik
  hingga 5%" as a range is still decided by the source side (a sentence with N and a change verb backs it).
- **SYS-167:** "<hari> pekan/minggu lalu" spans that weekday of last week. "awal/pertengahan/akhir pekan lalu"
  spans the whole of last week, because "akhir pekan" (weekend vs end of week) is ambiguous: no new refusals
  from a narrower guess. The phrase starts at the modifier, so the opening and frame rules see it unchanged.

# 2026-10-16 (dev, night): QA's evening queue (SYS-169 rework, SYS-171, SYS-172, SYS-173)

No new ADR. All four stay inside ADR-017's seam (`source_check` holds the tables and checks; `story_arc.parse`
wires them). The arc's data flow is unchanged.

## Decisions
- **SYS-169 rework: a future phrase is judged by key only, never by span.** The span check
  (`story_arc.unbacked_times`) skips a relative phrase that is also a future phrase ("akhir bulan ini"), and
  `unstated_future_times` drops its relative-phrase exemption. Reason: a span holding today backs an invented
  "akhir bulan ini" from the 21st on, which is the span backing SYS-169 chose against. It is still named once,
  now by the future check.
- **SYS-171: weekday future times** "(hari) <hari> depan/mendatang" join `_FUTURE`, keyed `hari <hari> depan`
  (so "Kamis mendatang" backs "Kamis depan", and a weekday never meets "pekan depan"). "Minggu depan" is the
  Sunday only with a capital M, as in `_RELATIVE` ("Minggu lalu"); lowercase is next week. Accepted cost: a
  sentence-initial "Minggu depan, ..." meaning next week is read as Sunday, so an article's "pekan depan"
  does not back it (a retry, not a false fact).
- **SYS-171 (owner, 2026-10-16 night): "se<unit> / N <unit> ke depan" counts as a future time.** Like
  SYS-169, a time window the articles don't state is the model's own; an uncounted one printed whenever the
  agenda had "akan". Keyed with minggu->pekan, seminggu->sepekan. Cost: the occasional retry on a forecast.
- **SYS-172:** the change claim reads bare `ke N`, `mencapai`/`total` among the words before N (up to two),
  and a comma after the verb. "<verb> mencapai N" with no to-word is still not a claim (not in the ticket).
- **SYS-173:** a part of last week is narrowed like a month part: awal Mon-Wed, pertengahan Tue-Thu,
  akhir Thu-Sun (covers both readings of "akhir pekan"). Supersedes the 10-16 (dev) whole-week call.

# 2026-10-16 (dev, late night): QA's night queue (SYS-171 rework, SYS-174, SYS-175, SYS-176)

No new ADR. All four stay inside ADR-017's seam: `source_check` holds the tables, `story_arc.parse` wires them. The
data flow and the prompt are unchanged; `relative_name` (the phrase shown beside each timeline item) is unchanged.

## Decisions
- **SYS-171 rework: "<hari> pekan/minggu depan|mendatang|ini" is that weekday, keyed `hari <hari> pekan depan|ini`.**
  - It does not share a key with "Kamis depan". From a Monday, "Kamis depan" may be this week's Thursday; "Kamis
    pekan depan" cannot be. Sharing would let one back the other across a week.
  - A stated one also states its week: an article's "Kamis pekan depan" backs the arc's "pekan depan". The reverse
    does not hold. Only the backing side gets the extra key (`unstated_future_times`). The repeat check
    (`agenda_repeats`, SYS-163/165) keeps exact keys.
  - "pekan ini" is included. "Rabu pekan ini" had the same hole: it was read as "pekan ini" alone.
  - Any case, and "Minggu pekan depan" is the Sunday: the week word after it removes the doubt.
  - No comma form ("Senin, pekan depan" may be today plus next week).
- **SYS-174: today never backs a relative span that still runs past it. In the agenda, only a day after today
  backs one.** (`story_arc._backing_days`; `unbacked_times(..., schedule=key == "agenda")`)
  - This is the ticket's first option, made by field. The literal option ("only a day after today backs a running
    span", in every field) was built and measured first. It refused 6 of the 39 stored v4/v5 arcs. Each was a true
    past "awal Oktober" in the latar on 8-9/10, backed by an early-October timeline item. That would cost about 15%
    of arcs a retry.
  - A past day inside a running span backs the past reading. The agenda is the scheduled step by construction, so
    there it backs nothing.
  - Today backs neither reading: it sits inside the span either way.
  - The ticket's second option (key the month part as a future time while it runs) was rejected. It would refuse a
    true past part that a timeline item backs, and it would make `future_phrases` depend on the edition date.
  - "sejak <bulan>" now spans that month only up to today. A start is never ahead, so it never runs past today, and
    today keeps backing it as before.
- **SYS-175: "mencapai" is the to-word only right after the verb (optional comma).**
  - Corpus, read-only: 55 sentences have "<verb> mencapai N", all real change claims ("naik mencapai 13,74 persen").
  - With a 1-8 word gap there are 1,181 sentences. There "mencapai" mostly belongs to another noun, often the
    earlier value ("turun 35,30% dari bulan sebelumnya yang mencapai 41.201 unit").
  - So the to-word may not stand after the gap.
- **SYS-176: a weekday may stand before the date of a running period** ("Hingga Senin (12/10)", "per Senin, 12/10",
  "sampai hari Senin (12/10/2026)", "hingga Kamis 8 Oktober"). It does so only when a date follows (lookahead). A bare
  "hingga Senin" may end a list.

## Failure modes accepted
- SYS-174, latar: an invented schedule in the latar, inside a running span that also holds a past day from the
  sources or the timeline, is still backed. The agenda is closed; the latar keeps the past reading.
- SYS-171: an arc's "Kamis depan" and an article's "Kamis pekan depan" for the same day do not meet. Cost: a retry.

## 2026-10-17: causal claims (SYS-152) -> ADR-018
- The owner chose the research-backed design ("better to follow that rather than we invented new approach").
- The prompt asks for a `sebab` quote, first in the JSON. Code decides: the quote must be a normalised substring of the source, hold a causal word, and cover both halves of the prose sentence. Attribution never exempts. One retry, then fallback.
- The judge is a shadow only, on another model family, for 2 weeks (SYS-180 #379).
- Superseded: SYS-152's rules (a) and (b), both of which pass the MK sentence.

# 2026-10-17 (dev): QA's SYS-152 send-back queue -> ADR-019, plus SYS-186 and SYS-174/177/178/179

## Causal gate (SYS-152 send-back, SYS-181..185, DBT-82) -> ADR-019
- The gate now matches a claim to ONE link of the quote: cause half to cause side, effect half to effect side,
  around one causal word that lies in the quoted span. The sides are cut from the SOURCE sentences the quote
  covers, and those are counted in the source.
- Owner, 2026-10-17: **strict per half**. The dev's OMC fixture becomes an accepted false refusal, like Ojol.
- Order of work: direction + one link (SYS-152 + SYS-181, the same change), then the source span (SYS-182), the
  word table (SYS-184), the fronted cause (SYS-183), negation (SYS-185), and the DBT-82 tests.

## SYS-186: "hingga / sampai <time>" is an end point, and the source must put it there
- New `source_check.unbacked_end_times(text, source)`, wired into `story_arc.parse` as a `date` refusal in every
  field. It is the same pattern as SYS-170's change claims: a guard on what the source SAYS about a value, not
  only that the value exists.
- A prose "hingga|sampai" + up to 3 words with no digit + a time (a month, a dated day, a year, "semester/kuartal"
  + numeral, or "akhir/awal/pertengahan" + one of those) must be matched by a source sentence. That sentence must
  put "hingga|sampai" (+ up to 3 words) before a time whose parts hold all of the prose time's parts (day, month,
  year, part, semester/quarter). "setelah November 2026" in the source never backs "hingga November 2026".
- No verb list. The ticket asked to count the replays first: every "hingga <time>" in v4..v6 is a period-to-date
  figure ("Defisit APBN hingga 30 September 2026") that its source states the same way. A verb list would leave
  "beroperasi hingga" and "melemah hingga" unguarded.
- Relative times ("hingga kini", "hingga akhir pekan") are not read here. "kini/saat ini/hari ini" is no end
  point, and future relative times are judged by key (SYS-169).
- Residual: the time matches, but the subject may not ("diskon berlaku hingga Desember" backs "pembekuan berlanjut
  hingga Desember"). That is the general fact-transplant risk the number guards share too. It is not built here.

## SYS-174 rework + SYS-177: backing days by field
`story_arc._backing_days(known, last, digest_date, ahead_only, today_runs)`:

| field | a span still running past today | a span ending today |
|---|---|---|
| agenda | only a day after today backs it | the same (`today_runs`), except "sejak <bulan>", a start, never a schedule |
| judul, hari_ini, sekilas (SYS-177) | only a day after today backs it | today and every known day back it (the present reading) |
| latar, a future verb within 4 words before the phrase in its sentence (SYS-177) | only a day after today | as before |
| latar, no such verb | a past known day backs it, today does not (SYS-174) | as before |

- The future verbs: akan, bakal, dijadwalkan, ditargetkan, direncanakan, rencananya, menyusul. The verb must stand
  BEFORE the phrase: the replay's "pada awal Oktober, ... yang akan memanggil" stays a past narration.

## SYS-178: bare "akhir tahun" / "akhir pekan" are future times
- Not followed by ini/lalu/depan/mendatang/kemarin/sebelumnya or a year. Keyed as "akhir tahun ini" and
  "akhir pekan ini": the bare form and the "ini" form mean the same end, so either one stated backs the other.
- A Monday article's past "akhir pekan" now costs a retry when the arc repeats it bare and the article wrote
  "akhir pekan lalu". The replays are re-checked.

## SYS-179: the parts of a future period are keyed with their part
- `_FUTURE` reads "(awal|pertengahan|akhir) (pekan|minggu|bulan|tahun) (depan|mendatang)" and "(awal|pertengahan|akhir)
  (pekan|minggu) ini", keyed with the part.
- On the backing side only, a stated part also states its whole period ("awal pekan depan" backs "pekan depan"),
  never the reverse. This is the SYS-171 rule for a weekday of a week.

# 2026-10-18 (dev): QA's 10-18 queue -> ADR-020, plus the time checks (SYS-186/191/193, SYS-177, SYS-190)

## Causal gate (SYS-188, SYS-181, SYS-189, SYS-185, SYS-192, SYS-183, SYS-187, DBT-83) -> ADR-020
- Owner, 2026-10-18: **every word of a half is covered** (no 60% share); unlisted verbs gated with a purpose
  exemption for membuat/mendorong/menekan; a hedged link needs any hedge in the claim.
- Names may stand elsewhere in the link's sentence, never on its opposite side. The previous sentence is lent only
  to a reference, a near-empty side, or an anaphor on the side's own subject that names the previous sentence.

## SYS-186 send-back + SYS-191 + SYS-193: what an end point is, and whose end it is
- **Gap.** Between the opener and the time, up to 3 words, of which the last may be "pada" ("hingga evaluasi indeks
  pada November 2026"). A digit, a degree word (level, posisi, puncak, tertinggi, terendah, rekor) or a function word
  (di, ke, dari, sejak, dengan, yang, dan, atau, setelah, sebelum) in the gap still blocks: "hingga level tertinggi
  pada Oktober" ends no period.
- **A part is keyed with its unit.** ("part", "akhir", "month") is not ("part", "akhir", "year"): "akhir 2027" is
  December 2027 and is not backed by "akhir Juni 2027". "hingga 2027" is still backed by it.
- **"per" after berlaku/mulai/efektif is a start**, never a stated end. "Defisit APBN per 30 September" stays one.
- **End openers without "hingga" (SYS-191).** berakhir, selesai and dicabut (each with an optional "pada"), and
  "s.d." / "s/d", open an end point in the prose and a stated end in the source.
- **Subject (SYS-193).** A stated end backs a prose end only when its sentence shares a content root with the prose
  clause before the opener. A clause with no content word (a bare "Hingga Oktober, ...") needs no subject.

## SYS-177 send-back: the latar's cue
- The cue verbs: akan, bakal, dijadwalkan, ditargetkan, direncanakan, rencananya, rencana, berencana, menyusul,
  diperkirakan, diproyeksikan, diharapkan, segera, hendak, siap, "mulai berlaku". A bare "mulai" stays out: "asap
  mulai meluas awal Oktober" is past.
- **Where.** Anywhere before the time in its clause (clause = up to the previous , ; : or sentence start). After the
  time, in the same clause, only while no "yang" and no verb stands between ("akhir Oktober aturan barunya akan
  terbit"). "awal Oktober Presiden menyatakan aturan akan terbit" stays past narration: "menyatakan" stands between.
- `CUE_WORDS` (4) is gone.

## SYS-190: a whole future month or period is keyed like a future time
- New `source_check.future_periods(text, today)` reads a month ("Desember", "bulan Desember", "November 2026",
  "November mendatang"), a semester/quarter with a year, and a year part ("akhir 2026", "akhir tahun 2026"). Each is
  keyed by its parts, like an end time (`_end_key`). "penghujung" is "akhir".
- **Which are judged:**
  - in the agenda, every one;
  - in the present fields (judul, hari_ini, sekilas), and in the latar under SYS-177's cue, only one that is not
    over (its last day >= today).
  - A bare year ("2026") is never one.
- **Backing.** Today's terkait articles must give the same key or a more precise one: "akhir Desember" and "15
  Desember" back "Desember", never the reverse. That is `unstated_future_times`' rule, with SYS-179's "a stated part
  states its whole".
- A future "akhir Desember" is still also judged by its span, as before.
