# QA report (independent): RAG search redesign + keyword search, 2026-10-07 (evening)

**Scope:**
- tracker #272: SYS-92..SYS-102 (#261-#271, commits ceb73cf, d2b48d4);
- SYS-103 #273 (c69d34d, ADR-006);
- scheduled-run evidence that arrived today for held tickets.

**Role:** independent QA, separate from the dev-side report `2026-10-07-qa-report.md`.

## Verdicts
| Ticket | Verdict | Basis |
|---|---|---|
| SYS-92 #261 | **Close** | Unit + integration green. Live: all 12 topic options give 5 cards, every card in that topic. |
| SYS-93 #262 | **Close** | `<img onerror>` / `<b>` in the question render escaped (live). Mutants killed: `sys93_*` (4), `qa1007_cite_zero_linked`. |
| SYS-94 #263 | **Close** | State tests green. The live `expired` / notice states show copy only. |
| SYS-95 #264 | **Close** | Live scan of index / turn / answer / expired / notice / too-long: no enum outside attributes or article text, no 8-digit date, no English month, no timing. |
| SYS-96 #265 | **Close** | Contrast + label tests green. QA's own keyboard e2e: 14/14. (No screen reader or axe, as for dev; the Done-when allows either.) |
| SYS-97 #266 | **Close** | e2e: 2 turns in one session; "Pertanyaan baru" sends no session. New defect: follow-up *retrieval* ignores the thread → SYS-104 #274. |
| SYS-98 #267 | **Close** | `api_usage_log` has `web:deepseek-v4-flash` and `web:gemini-2.5-flash` rows with tokens/dollars; OPERATIONS lists the variables. |
| SYS-99 #268 | **Close** | Live answers: citations resolve to cards, ≤ 120 words, the exact "belum cukup" sentence on thin evidence. |
| SYS-100 #269 | **Close** | Live: portal + 7 days, topic, and a reversed custom range narrow correctly; chips by brand name. |
| SYS-101 #270 | **Close** | Template literal-text test green; each state's copy seen live. |
| SYS-102 #271 | **Close** | Screenshots at 375 / 1280, light/dark, match the approved mockup. Warm-up 22.9 s at start-up. |
| SYS-103 #273 | **Close** (Done-when met) | BI decision at rank 3; `fts=20` on every question. The ADR's "a name lifts its article" is false for keyword-only finds → SYS-106 #276. |
| SRC-58 #231 | **Close** | 07:00 and 19:00 crawls: PIKIRANRAKYAT "62 skipped", sitemap phase 29-34 s (was 147 s); KONTAN / OKEZONE "gone"; VIVA `jatim` 500/502 still a failure. |

## Suites and mutants
- `tests/unit`: 2,655 passed, 5 skipped.
- `tests/integration`: 198 passed, 1 skipped. On the first run, 8 failed while the 19:00 crawl held the run lock (→ DBT-61 #281); they pass after it.
- Dev mutants `sys92_*`..`sys103_*`: **67/67 killed**.
- QA mutants `qa1007_*`: 29/40 killed; the 11 survivors also survive the full tests/unit: 7 real test gaps -> DBT-62 #282, 4 equivalent (listed there). None of the 7 is a defect in the shipped behaviour (verified live).

## Defects filed
| Ticket | Sev | Finding |
|---|---|---|
| SYS-104 #274 | P2 | A follow-up is retrieved on its own words: the OJK credit follow-up returned and answered GDP growth 2027. |
| SYS-105 #275 | P2 | The chunker keeps an article's trailing sign-off as its own L2 chunk (1,606 under 10 words). Those 1-word vectors are hubs: "Apa itu Danantara?" got 5/5 "(jon)"/"--" cards, and gibberish gets 3 cards instead of `no_hits`. |
| SYS-106 #276 | P2 | Re-rank: a keyword-only hit scores ≤ 0.40 and never reaches the top 5. Over 19 questions, 0 of 95 cards were keyword-only, and 340 such hits were over the floor. |
| SYS-107 #277 | P2 | Candidates ignore dates: "harga emas Antam hari ini" was answered with the 1 Oct price; 21 articles from 7 Oct exist. |
| SYS-108 #278 | P3 | The df cache keeps a 0 for 24 h, so a new name stays out of keyword search after its articles land. |
| SRC-60 #279 | P2 | KUMPARAN reader blog posts are stored as news (314 rows, 17%). They are the BI-Rate question's ranks 1-2. |
| SRC-61 #280 | P3 | KUMPARAN bodies start with chrome ("·waktu baca N menit"): 95% of rows. |
| DBT-61 #281 | P3 | `tests/integration` fails 8 tests during every scheduled crawl (it reads the production run lock). |
| DBT-62 #282 | P3 | 7 RAG boundaries no test guards (top-K cap, FTS chunk level, peak pricing, merge max, the 500-char limit, rel=noopener, the follow-up's filters). |
| OPS-46 #259 | (comment) | Recurred: the 12:00 newsletter delivered 10 test alerts queued at 09:35 by the dev's SYS-103 integration run. |

## Held tickets: evidence seen today
- **OPS-43 #243:** 2026-10-07 12:00 was a valid run (message + phone PDF sent, 88/90 summaries, 904-word edition). It is **1 of 3** (10-06 was degraded).
- **SRC-59 #260 (P2, open, not worked):** INVESTORID `sitemap_news.xml` still 404 at 07:00 and 19:00.
- **OPS-20 #136 / SYS-39 #125:** the next evidence is tonight's 21:00 extraction.
- **SRC-57, SYS-64, SYS-66, SYS-82/83, OPS-42:** unchanged (run counts or owner checks pending).

## Release readiness
- The page is better than the version it replaces on every ticketed point, and safe for local use (security review S1-S12 stands; the escapes were re-verified live).
- **The owner's :8000 still runs the pre-redesign code** (process started 00:16, before ceb73cf at 06:49): restart it, one worker.
- **Retrieval quality is the open risk, not the UI:**
  - questions about a named entity (SYS-105/106), about "today" (SYS-107), and follow-ups (SYS-104) can get confident wrong-topic or stale sources;
  - the answer usually says "belum cukup" honestly, but the follow-up and stale-price cases do not.
- Recommended order: SYS-105 (the retrieval-side skip is cheap) → SYS-106 → SYS-107 → SYS-104; SRC-60 alongside.
