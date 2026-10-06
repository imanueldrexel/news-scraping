# RAG search redesign: architecture (2026-10-07)

Tracker #272; ADR-005. The PM's copy and prompt: `decisions/product-manager/rag-search-redesign.md`.

## Components (all under `newscrawler/web/` unless named)
| Unit | Does | Depends on |
|---|---|---|
| `core/web_copy.py` | Every reader-facing string of the page; date/time/hero/filter-summary formatters | `newsletter_copy` (dates, outlet names, section names) |
| `web/answer.py` | Pure functions: the prompt; Markdown cleanup; parse the text into blocks of text/citation segments; the cited set; the number check; history formatting without `[n]` | `story_summary.unsupported_number`, `web_copy` |
| `web/query_processor.py` | `retrieve(question, filters) -> Retrieval` (FAISS + FTS, merge, DB metadata, filters, re-rank, floor, top-K); `answer(question, retrieval, history) -> AnswerResult` (state machine, usage + cap); `query()` = both | FAISS datasource, DB client, `Summarizer`, usage datasource |
| `web/filters.py` | `Filters` (topic, source, date_from, date_to), parsed and validated from form/JSON input; the `rentang` chips | `filter_rubric.TOPICS`, `WebsiteName` |
| `web/turn_store.py` | In-memory pending turns (TTL, cap, thread-safe) | — |
| `web/site_stats.py` | Cached corpus line (articles, portals, last update) and the portal list for the dropdown | DB client |
| `web/app.py` | Routes, singletons, warm-up lifespan | all of the above |
| templates | `index.html` (shell, hero, search, filters, thread, follow-up), `_turn.html`, `_answer.html`, `_sources.html` | `copy` global |

## Data flow
```
Tanya ──POST /api/query/form──▶ Filters.parse ─▶ retrieve()
                                   │  FAISS L2 (k=20, or RAG_FILTERED_K with a filter)
                                   │  FTS L2 (filters in SQL)
                                   │  merge by sitemap_id ─▶ one SQL: sitemaps ⟕ articles ⟕ chunks(L1)
                                   │  filter ─▶ re-rank ─▶ floor ─▶ top K
                                   ▼
                      TurnStore.put(turn) ─▶ _turn.html (question, cards, placeholder | no-hits state)
                                   ▼ (hx-trigger=load)
                      POST /api/answer/{turn_id} ─▶ answer(): cap? ─▶ Summarizer.complete ─▶ usage(web:model)
                                   ▼                  ─▶ clean ─▶ parse ─▶ number check
                      _answer.html (ok | unavailable | failed + Coba lagi | expired)
                      session.update(question, answer without [n])   (ok only)
```

## Boundaries and contracts
- **The answer text is untrusted.** It is rendered from segments with autoescape; a citation's `href` is `#src-{turn_id}-{n}` with n in range.
- **The scraped headline, snippet and link are untrusted.** They are autoescaped, and a link becomes an `href` only for `http://` or `https://`.
- **Filter values are validated against closed sets:** topics from `filter_rubric`, sources from `WebsiteName`, dates as ISO. An unknown value is dropped and logged, never passed to SQL. SQL takes bind parameters only.
- **The web layer never shows** an internal source name outside `value=` / URLs, a yyyymmdd date, an exception, "chunk", or a timing.

## Failure modes
| Failure | Behaviour |
|---|---|
| FTS query fails | Logged; semantic hits only (unchanged) |
| Metadata query fails | Logged; the hits keep FAISS metadata, and topic filters match nothing (safe direction) |
| FAISS search fails | Logged; FTS only (unchanged) |
| No summarizer / quota / cap | `unavailable` copy, cards visible |
| Provider error / empty reply | `failed` copy + "Coba lagi" (same turn) |
| Turn expired / server restarted | `expired` copy |
| DB down for the hero stats | Generic hero line without numbers; dropdown without portals except the "Semua portal" option |
| Model warm-up fails | Logged; the first request builds it (old behaviour) |

## Non-goals
- Query rewriting for follow-ups (retrieval uses the follow-up text alone, as before).
- Auth / rate limiting: needed before the page is shared (security review).
- Streaming.
