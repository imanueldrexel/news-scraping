# Entity links: hidden company links -> mispricing candidates (design, 2026-10-11)

**Feature slug:** `entity-links`. **Status:** brainstorm approved section by section by the owner on 2026-10-10/11. Revised 2026-10-12 with an exact merge undo, the link-job pilot before the full pass, and the order of production writes. Awaiting the owner's review of this document.
**Evidence:** EXPERIMENTS.md "2026-10-11 — entity-links design: what the stored corpus can support".

## Goal
Link entities in the knowledge base to each other, using the news and IDX's official ownership data, so the owner can find **listed companies exposed to a piece of news that their price has not reflected yet**. The same links also make the newsletter's stories richer.

## Non-goals
- No buy/sell recommendations, orders, or automated trading. The output is a ranked list of *candidates to check*, and every reader-facing surface says "Bukan rekomendasi investasi".
- No intraday prices. Daily bars only.
- No drawn network graph in v1. Pages are tables; a graph view is a later option.
- No people-to-people social graph. People matter only as board members linking companies.

## Owner decisions (2026-10-10/11)
1. Use the knowledge base for links between entities; the end goal is finding stocks that are wrongly priced. The newsletter should use the links too.
2. All three signal patterns: **second-order exposure**, **ownership & group ties**, **rising attention**.
3. Daily IDX prices: **from the owner's existing price project's database** (read-only). It holds tickers and daily prices only, no company names. This lifts PRD §3's non-goal "IDX price data integration (news only)", and "relationship/graph extraction (post-MVP)" is now in scope.
4. Surfaces: **web explorer page** + **newsletter section**. No Telegram alert, no CLI-only.
5. Typed links from news by **approach B**: a separate link-extraction job whose prompt gets the article plus its already-resolved entities.
6. Ownership: the **KSEI > 1% shareholder file is the backbone**. News-derived ownership links are kept, tagged "reported".
7. Horizon: **depends on the signal**. Every detector is scored at 1/5/20/60 trading days.
8. Universe: **every listed stock, flagged**. Illiquid/suspended/special-board/limit-locked stocks are badged and excluded from the gate statistics.
9. Daily load: **top 5** on `/sinyal`.

## What the data showed (and how the design answers it)
| Finding (2026-10-11, read-only probes) | Design consequence |
|---|---|
| BBCA is 5 entities and PGAS 17; 433 entity rows hold non-4-letter tickers; 960 distinct tickers vs ~950 listed | Step 1 merges against an official company list; one entity per ticker is enforced by a unique index |
| Supplier/customer wording in 3% of company-pair articles (~20/day); contract 8%, lender 9%, M&A 7% | Second-order exposure starts thin and grows; the link-quality gate also measures recall |
| Ownership wording in 13%; IDX/KSEI publish all shareholders > 1% monthly since 2026-03 | Ownership backbone from KSEI (decision 6) |
| Dense news only since 2026-09 | News detectors pass their gate by **forward test**; group divergence can also be backtested on price history |
| `posted_at` is a date; the sitemap's time is parsed and dropped (`crawler.py:628`) | Step 0 stores the publication timestamp |
| IDX microstructure: auto-rejection limits, suspensions, special board, thin trading, corporate actions | Flags (decision 8); adjusted prices required (see "Inputs from the owner") |

## Components and build order
```
[0] Publication timestamp  ->  sitemaps.published_at
[1] Merge duplicate entities against listed_companies (IDX list)
[2] PriceSource adapter (owner's DB, read-only)      [3a] KSEI > 1% ingest (monthly)
[3b] Link extraction job (approach B)  ->  entity_relations
[4] Graph: entity_links (typed) + entity_comention_weekly
[5] Signal engine (3 detectors) -> link_signals; outcome filler
[6] Surfaces: /entitas, /sinyal, newsletter "Terkait" + "Efek berantai"
```

### 0. Publication timestamp
- New nullable `sitemaps.published_at timestamptz`. It's filled from `news:publication_date` (or `lastmod`) when the value has a time.
- Existing rows stay null. Alignment code treats a null as "date only" and uses the two-day window (§5).

### 1. Entity merging
- **Anchor:** `listed_companies` loaded from IDX's published company list (ticker, legal name, sector, listing/delisting date). It's committed as `newscrawler/core/reference/idx_listed_companies.csv` and refreshed monthly. Each refresh reports tickers in the CSV that have no prices in the owner's database, and the reverse.
- **Organization rules, exact only and no fuzzy matching:**
  - Same valid ticker → merge.
  - Same name after normalising → merge. Normalising means: casefold; strip `PT`, `Tbk`, `(Persero)`, `Persero`, a trailing `(XXXX)` ticker, and punctuation; collapse spaces.
  - A ticker not in `listed_companies` is set to null.
  - Group siblings stay separate (INDF ≠ ICBP; `PT Bank BCA Syariah` ≠ BBCA). These are test cases.
- **Person rules:** exact match after normalising, which also strips honorifics (`Dr.`, `Ir.`, `H.`, `Hj.`, academic suffixes). No surname folding: "Prabowo" stays separate from "Prabowo Subianto" unless an alias row says otherwise.
- **Mechanics:**
  - Mentions are re-pointed to the surviving entity; when an article mentions both copies, one mention is kept.
  - Every merged-away name becomes an `entity_aliases` row, and every merge is written to `entity_merges` (undoable).
  - **Undo is exact (owner, 2026-10-12):** `entity_merges` keeps everything the merge changes. That covers the merged-away entity row as it was, the ids of the mentions re-pointed, the alias rows added, and **every mention row deleted as a duplicate, in full**. Undo restores the entity, re-points those mentions back, re-inserts the deleted mentions, removes the added aliases and recomputes the counts. The pg_dump is the backstop, not the undo path.
  - `mention_count`, `first_seen_at` and `last_seen_at` are recomputed.
- **Going forward:** the normaliser checks `listed_companies` and the alias table on every extraction, so duplicates stop being created.
- **Safety:**
  - Dry run first: a report of every merge group (survivor, rows folded in, mention counts). The owner can veto individual groups.
  - pg_dump backup, then the owner approves the production write.
  - It must not run while `extract_knowledge` is running: it takes the same run lock or checks `crawl_log`.

### 2. PriceSource adapter
- An interface `PriceSource` with:
  - `bars(tickers, start, end) -> {ticker: [(date, close, volume, value?)]}`
  - `index_bars("IHSG", start, end)`
  - `trading_days(start, end)`
- The production implementation reads the owner's database with a read-only connection from `PRICES_DB_*` env vars. Tests use an in-memory fake.
- The trading calendar is the set of days that have an IHSG bar.
- Nothing is copied into `newsaggregator`, except the snapshot each signal keeps.

### 3a. KSEI ingest (monthly)
- Loads IDX's monthly "Pemegang saham diatas 1% (KSEI) [Semua Emiten Saham]" file into `entity_relations` with `source='ksei'`, `relation_type='shareholder_of'`, `stake_pct` and `as_of`.
- Holder names are resolved to entities with the same rules as step 1. Holders that don't exist yet are created.
- **Custodian and nominee accounts are excluded from group ties.** Examples: "UBS AG Singapore", "HSBC-Fund Services", "Citibank Singapore S/A …", "Masyarakat". They are kept as rows but marked `holder_kind='custodian'`, because otherwise they would link every company to every other one. The rule is a committed pattern list plus a hand-checked top-50 holder review.

### 3b. Link extraction job (approach B)
- **Task and timing:** new task `extract_links`. It's a separate `crawl_log` task and runs after `extract_knowledge` in the nightly window, through the same `ExtractionProvider`. It has the same peak-hours guard, the stop after 5 failures in a row, and the OPS-09 rule that a transient error never counts against an article.
- **Budget:** its own daily cap `LINKS_DAILY_COST_LIMIT_USD`. Usage is logged in `api_usage_log` under `links:<model>`.
- **Queue:** extracted articles with ≥ 2 resolved ORGANIZATION/PERSON entities and `links_extracted = false`. Finance topics go first, newest first. It uses the same poison-pill handling as SYS-19 (`links_extract_attempts`, `last_link_error`).
- **Prompt:**
  - Input is the article (first 3,000 chars) plus a numbered list of its resolved entities.
  - Output is JSON `[{subject: n, relation: <type>, object: m, evidence: "<sentence>"}]`.
  - Subject and object must be numbers from the list, so the model can't invent an entity.
  - Types: `supplier_of`, `customer_of`, `contract_with`, `lender_to`, `jv_partner`, `acquires`, `subsidiary_of`, `shareholder_of`, `director_of`, `commissioner_of`, `same_group`.
  - Instructions: return nothing when no link is stated; a quote by a CEO is not a link between companies.
- **Validation:** a link is rejected when its type is outside the list, its entity number is outside the list, its subject equals its object, or its evidence is not a substring of the article (after whitespace normalisation).
- **Cost estimate:** ~1,000 tokens in and ~150 out per article. The one-time pass over ~85k articles is ~$20 off-peak; ongoing ~3,000 articles/day is ~$0.7–0.9/day. The ~85k is an estimate: the real queue is counted after the `extract_knowledge` backlog clears, and that count goes into the approval request.
- **Pilot first, then the one-time pass (owner, 2026-10-12):**
  1. **Pilot:** `extract_links` runs on ~300 queued articles (~$0.07), stratified so that every relation-cue group from the corpus probe is present. No approval needed.
  2. **Quality gate on the pilot:**
     - Hand-check 100 sampled links, stratified by type: precision must be **≥ 85%**.
     - Recall is measured on 50 articles with supplier/contract wording: reported, not gated.
     - A failed gate means changing the prompt or validation and re-running the pilot, never the full pass.
  3. **Full pass:** only after the pilot passes, and on the owner's approval with the real queue count and cost. It runs under `LINKS_DAILY_COST_LIMIT_USD`, so it spreads over several nights.
- Step 4 is used nowhere until the gate has passed.

### 4. Graph
- **`entity_links`** is a materialised view refreshed after each `extract_links` run and each KSEI ingest. It has one row per (A, B, type) with: `evidence_count`, `distinct_sources`, `first_seen`, `last_seen`, the `sources` set (`news`/`ksei`), and for KSEI the latest `stake_pct`/`as_of`.
  - A news-reported ownership link later confirmed by KSEI becomes one row with both sources.
  - "Reported" means a news-only row.
- **Well-backed link:** evidence_count ≥ 2 or distinct_sources ≥ 2, last_seen within 365 days. KSEI rows count as well-backed.
- **Groups:**
  - Groups are connected components over control edges: `subsidiary_of`, `same_group`, KSEI `shareholder_of` with `stake_pct ≥ 20` from a non-custodian holder, and two companies sharing a `director_of`/`commissioner_of` person.
  - The build reports the component size distribution. A component above 60 listed members (the state-holding case) is split at its weakest edges, and the split is logged.
- **`entity_comention_weekly`:** (A, B, ISO week, article count) for ORGANIZATION/PERSON pairs, built incrementally.

### 5. Signal engine (daily, after `extract_links`)
- **Return:** a stock's daily return minus IHSG's.
- **Big move:** |return| ≥ 2.5 × that stock's 60-day standard deviation of returns.
- **Not reacted:** |return| < 1 × that deviation.
- **Day alignment:** an article with `published_at` after 16:00 WIB maps to the next trading day. A date-only article counts the same trading day and the next.
- **Trigger:** entity A has news on the day with a material `event_type` (`corporate_action`, `legal_case`, `commodity_price`, `policy_announcement`, `economic_data`, `market_movement`) and either:
  - A is listed and made a big move, or
  - A is unlisted and its article count ≥ 3 × its 30-day daily average, from ≥ 2 outlets.

**Detectors:**
1. **`second_order`:**
   - From A, follow well-backed typed links to a listed B: one step, or two when the second step is `subsidiary_of`/`shareholder_of`.
   - B is a candidate if it has no article on the day naming it with A's event and has not reacted.
   - Score = trigger strength × log(1 + evidence_count) × distinct-source factor × type weight (supplier/customer/lender 1.0, contract/JV 0.8, ownership 0.7, M&A 0.6), halved for two steps.
   - Direction hint from A's move and the link type, shown as a hint only.
2. **`group_divergence`:** in a group with ≥ 3 listed members, one member makes a big move on the day of group-related news, and members that have not reacted are the candidates.
3. **`rising_attention`:**
   - Listed B whose weighted co-mention degree over the last 7 days is ≥ 3 standard deviations above its trailing 8-week mean, with ≥ 3 partners never linked before.
   - B's 20-day cumulative return must be within ±1 standard deviation.
   - It needs 8 weeks of baseline, so its first signals come about 8 weeks after weekly co-mentions are first built.

**Flags** (badge; flagged candidates are excluded from the gate statistics and from the newsletter):
- `illiquid`: 20-day average traded value < Rp1 bn, or volume × close as a proxy when value is missing.
- `suspended`.
- `special_board`.
- `limit_locked`: the close equals the day's auto-rejection limit.

A flag the price database cannot support is not computed, and the page says which flags are unavailable.

**Ranking:**
- Each candidate's score is turned into a percentile within its detector's own history.
- `/sinyal` shows the **top 5 overall, at most 2 per detector**.
- Every candidate is stored.

**`link_signals` row:** date, detector, trigger entity, candidate entity and ticker, path (each step's type and `entity_relations` ids), score, percentile, flags, direction hint, and the **price snapshot used**. Outcome columns `ret_1d/5d/20d/60d` are filled by a nightly outcome job once each window has passed.

**Gate:** a script, run by hand, that writes a report. It runs per detector and per window w ∈ {1, 5, 20, 60}, over unflagged candidates and separately over the top-5 cut.
- Mean |return over w| ≥ 1.2 × that of random unflagged listed stocks from the same sector on the same date.
- n ≥ 50.
- Bootstrap p < 0.0125 (0.05 / 4 windows).
- Direction-hint accuracy is reported, not gated.

A detector passing is an **owner decision** recorded in config (`LINK_DETECTORS_PASSED`), never automatic. Group divergence also gets a price-only backtest on historical prices using the current ownership snapshot; the report labels the hindsight caveat.

### 6. Surfaces
**Web** (existing FastAPI app, read-only routes, `core/web_copy.py` for every string, no `| safe`, one worker):
- **`/entitas`:** search by name/ticker/alias.
- **`/entitas/{id}`:**
  - Header with type, ticker, sector, and the last 5 days' returns against IHSG.
  - **Hubungan:** links by type, with direction, evidence count, outlets, last seen, and source badges ("KSEI x% per <date>", "dilaporkan").
  - htmx partial `/entitas/{id}/hubungan/{other}` shows the evidence sentences with article links.
  - **Sering disebut bersama:** this week vs the 8-week average.
  - **Grup:** members.
  - **Sinyal:** recent signals involving the entity.
- **`/sinyal?date=`:** the day's top 5, then the rest collapsed. Each shows the path in words, trigger and candidate returns, flags, evidence, matured outcomes, and an **"eksperimen"** label for detectors not in `LINK_DETECTORS_PASSED`.

**Newsletter:**
- **"Terkait" line** on each top story (5-minute edition and archive):
  - Up to 3 well-backed linked listed companies the story does not name, with the link in words, e.g. "Terkait: XXXX (pemasok Antam), YYYY (satu grup)".
  - Built deterministically, without a language model; copy in `core/newsletter_copy.py`.
- **"Efek berantai"** in the 5-minute edition:
  - At most 3 lines, only from passed detectors and unflagged candidates; left out otherwise.
  - Fixed size inside the 1,200-word budget (the budget still trims Sekilas only).
  - Its numbers come from the signal's price snapshot. They are checked against that snapshot and kept outside SYS-87's article-number check by design.
  - It ends with "Bukan rekomendasi investasi."

## Production writes and their order
Each one gets a pg_dump backup first (`scripts/backup_db.py`) and its own owner approval. Every migration runs on `newsaggregator_test` first (DBT-22).

| # | Write | Contents | Undo |
|---|---|---|---|
| 1 | **Migrations, batch A** (additive) | `sitemaps.published_at`, `listed_companies`, `entity_merges`, `entity_relations`, `articles.links_extracted`/`links_extract_attempts`/`last_link_error`, `entity_comention_weekly`, `link_signals`, the `entity_links` view | Drop the new objects; existing code never reads them |
| 2 | **Entity merge** | Step 1, after its dry-run report | Exact undo from `entity_merges` |
| 3 | **Migrations, batch B** | Partial unique index: one entity per non-null ticker | Drop the index |
| 4 | **Link pass** | The one-time `extract_links` pass, after the pilot passes | Delete `entity_relations` rows with `source='news'`; the money is spent |

Batch B can't run before the merge: today's duplicates (BBCA ×5) would make the index fail. Writes 1–3 may share one approval if the owner prefers.

## When each part goes live
| After | Live |
|---|---|
| 0 + 1 | Correct entity counts; `kb_query` improves |
| 3a + 3b + 4, and the ≥ 85% link-precision gate | `/entitas`, newsletter "Terkait" |
| 5 | `/sinyal` (eksperimen) and outcome scoring |
| A detector passes its gate (owner decision) | That detector in "Efek berantai", without the eksperimen label |

## Failure modes
- **Price database unreachable:**
  - The signal run fails with the reason in `crawl_log`; it is not silently empty.
  - `/entitas` still renders without returns.
  - The newsletter leaves out "Efek berantai" and keeps "Terkait".
- **KSEI file format changes:** the ingest refuses (column check) and keeps the previous month's rows.
- **Provider budget, peak hours or failures:** same stop rules as SYS-39; the queue simply waits.
- **Bad merge:** reversible from `entity_merges`, and the pg_dump is the backstop.
- **Giant group component:** split and logged (§4).

## Testing strategy
- **Unit:**
  - Name normaliser and merge-rule table, including the sibling cases (INDF/ICBP, BCA Syariah).
  - Link validation (evidence substring, id range, closed types).
  - Custodian patterns.
  - Day alignment around 16:00 and null timestamps.
  - Each detector on hand-built fixtures with a fake PriceSource.
  - Flag logic, percentile ranking and the top-5 cap.
  - The gate statistic on synthetic data with a known effect and with no effect.
  - The newsletter's Terkait/Efek berantai copy and word budget.
  - Web copy and no-`| safe` tests extended.
- **Integration (`newsaggregator_test`):**
  - The migrations.
  - Merge apply + undo. After undo, the `entities`, `entity_mentions` and `entity_aliases` rows touched must equal the snapshot taken before the merge, including mentions deleted as duplicates.
  - Batch B fails on a DB that still holds duplicate tickers (the order is enforced, not just documented).
  - Unique-ticker enforcement.
  - `entity_links` refresh.
  - `extract_links` end to end with a fake provider.
- **Mutation:** the QA practice (`qa_mutation_runner.py`) on the merge rules, link validation and detector thresholds.
- **Bake-off:** link precision ≥ 85% on the 100-link hand check of the pilot, before the full pass and before anything shows links.

## Inputs from the owner
- Price database access (host, database, read-only user).
- Whether prices are **split/rights-adjusted**. The design needs adjusted prices; if they're raw, an adjustment step is added before §5 is built.
- Whether volume and/or traded value exist (the `illiquid` flag).
- Whether suspension or special-board status exists (those flags).
- Whether the price project already computes market-relative returns or signals (reuse rather than rebuild).
- Approval of each production write in "Production writes and their order": migrations A, the step-1 merge, migrations B, and the one-time `extract_links` pass (~$20, after the pilot).

## Risks
- **The edge may be weak or absent.** The research supports a lag, and some replications doubt its size. The forward test is the honest answer; the cost of finding out is ~3 months of watching plus ~$1/day.
- **Thin supplier graph early on.** Second-order signals will be rare at first; ownership and co-mention carry the early weeks.
- **News-derived links can be wrong in ways that look plausible.** Every link shows its evidence sentence, and the precision gate comes first.
- **Hindsight in the group-divergence backtest:** today's ownership is used for past years, and the report labels it.
