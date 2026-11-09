# RAG retrieval quality: QA's findings of 2026-10-07, fixed (SDE, 2026-10-08)

ADR-007. Commits 715b4d8..b269431 on `dev`. EXPERIMENTS.md "2026-10-08 — SDE fixes of QA's retrieval findings".

## Built
| Ticket | What | Where |
|---|---|---|
| SYS-105 #275 | Short last paragraph merges backward; matched paragraphs < 15 words skipped; stored fragments re-chunked (mentions kept) | `core/chunker._merge_short`, `query_processor.substantial/MIN_PARAGRAPH_WORDS`, `scripts/rechunk_stale_chunks.py` |
| SYS-106 #276 | Every candidate scored on both signals: keyword-only → stored NEWS_L2 vector's cosine (`chunks.embedding_id`, id→position map per loaded index); FAISS-only → coverage via `to_tsvector('simple', …)`; `origin` on hits; log `keyword_only=` | `query_processor._complete_scores/_coverage/_word_tests`, `ChunkFAISSDatasource.similarity/_l2_positions` |
| SYS-107 #277 | FAISS over-fetch 100; recency cue table (`keywords.recency_cue`): hari ini 1 d/0.3, pekan ini 3 d/0.2, terbaru 7 d/0.1, only for semantic ≥ floor; FTS orders full-coverage paragraphs newest first under a cue | `keywords.RecencyCue`, `query_processor.recency/_re_rank/_fts_sql` |
| SYS-104 #274 | Follow-up retrieved on its words + the session's last 2 questions; the session keeps every question apart from answered turns | `query_processor.retrieval_text`, `SessionManager.record_question/get_questions`, `app.py` both routes |
| SYS-108 #278 | df 0 not cached | `keywords.DocFrequency.get` |
| SYS-110 #284 (found) | `semantic_score` = cosine (1 - d/2); floor 0.60 → 0.55 | `ChunkFAISSDatasource.search_l2`, `constants.RAG_MIN_SEMANTIC_SCORE` |
| SRC-60 #279 | `Crawler.out_of_scope_reason(link)` applied in `get_news_in_bulk` and the health sample; KUMPARAN keeps `kumparan*` desks + `pandangan-jogja`; stored rows settled | `scrapers/crawler.py`, `kumparan_crawler.py`, `crawler_service_impl._branch_note`, `check_crawlers.py`, `scripts/settle_out_of_scope_links.py` |
| SRC-61 #280 | Body cleaner drops a header ending in "waktu baca N menit" within the first 5 lines (prose kept); "Ikuti kumparan di Google" is chrome | `core/utils/utils._reading_time_header`, `clean_body_paragraphs` |
| DBT-61 #281, OPS-46 #259 | Integration tests isolate the run lock and the Telegram outbox per test; a test adding to the real outbox fails | `tests/integration/conftest.py` |
| DBT-62 #282 | 7 tests for QA's surviving mutants | RAG unit tests |
| DBT-63 #285 (found) | `.gitattributes` eol=lf for fixtures in subdirectories | `.gitattributes` |
| Filed, not fixed | SYS-109 #283: MiniLM embeds only the first 128 tokens (~97 words) of a chunk | — |

## Production writes (owner-approved 2026-10-08 ~17:00 WIB, fresh pg_dump first: `newsaggregator_20261008T100931Z.dump`)
1. SRC-60 settle: 364 sitemaps, 357 articles, 1,092 chunk rows = 1,092 vectors, 1,168 mentions; 676 entity counters recomputed. Backup `backups/src60_KUMPARAN_20261008T101051Z`.
2. SRC-61: `repair_boilerplate_bodies.py --apply --source KUMPARAN`: 1,521 rewritten and re-chunked, 0 failed; 4,858 mentions deleted, 576 articles reset for extraction. Backup `backups/sys73_KUMPARAN_20261008T101222Z`.
3. SYS-105: `rechunk_stale_chunks.py --apply`: 3,075 articles, 17,222 chunk rows, 5,962 mentions detached and re-attached. Backup `backups/sys105_ALL_20261008T101935Z`. Results in the ticket comment.

## Deviations from QA's suggested fixes
- **SYS-107's FTS date tie-break** applies only under a recency cue, and only among full-coverage paragraphs. ADR-006 measured newest-first over every tie letting off-topic paragraphs in (QA's ticket said ADR-006 had measured it as the primary order; it was the tie-break).
- **SYS-106:** both signals are completed, not RRF (RRF loses the absolute floor). The cosine comes from stored vectors, not re-embedding (latency).
- **SYS-105:** the retrieval minimum is 15 words, not 8. Every L2 chunk under 30 words was an article's last chunk; 10-14-word DETIK chunks were hubs too ("Purbaya"). The chunker logs nothing per article (one line per article would be noise).
- **SYS-104:** option 1 (no model call). It works when the answer failed, because the thread is every question asked.

## Evidence
- unit 2,756 passed / 5 skipped (QA baseline 2,655); integration 205 passed / 1 skipped (+ 2 new live files).
- Mutants (scratch worktrees, `QA_MUTANT_TESTS` = RAG/chunker/cleaner/KUMPARAN files):
  - QA's 67 dev + 38/40 `qa1007_*` (2 known equivalents);
  - 44 new `sys104..sys110_*`, `src60_*`, `src61_*` all killed (2 after adding tests).
  - 11 unrelated mutants were already stale at HEAD (`ops32/33/35`, `sys67/68`, `ops20`): QA's to ticket.
- Probe (no model call), 20 questions + 7 follow-up pairs:
  - keyword-only cards 0 → 59 of 160; fragment cards 14 → 0;
  - Danantara 5/5; gibberish `no_hits`; gold 5/5 from 7-8 Oct;
  - BI decision in the top 5; follow-ups 5/7 on topic.
- Live (:8765): warm retrieval 62-625 ms (1.1 s one follow-up), cold up to 2.1 s; `followup=True` on follow-ups.

## Not done / risks
- **The SumoPod key is blocked** (`401 Key is blocked`), found 2026-10-08. The page shows `failed`; the 12:00 newsletter and the 21:00 extraction are affected too. The owner unblocks it. SYS-107's "cites an article of that day" needs a working answer; the sources are proven.
- Residuals: "Apa kabar terbaru soal Purbaya?" 3/5 (an unknown name for MiniLM); "Bagaimana kasus Pertamina?" 1 case article; 2/7 follow-ups mixed; retrieval slower than SYS-103 (62-625 vs 108-358 ms warm).
- SYS-109 limits every cosine; the re-chunk for it would supersede SYS-105's.
