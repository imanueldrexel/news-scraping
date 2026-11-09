# RAG search redesign: data (DBA, 2026-10-07)

**No schema change, no migration.**

## New reads
| Query | Measured (prod, 2026-10-07) |
|---|---|
| Metadata by sitemap_id: `sitemaps JOIN articles LEFT JOIN chunks(level 1)`, `WHERE s.sitemap_id = ANY(:ids)` (<= 220 ids) | PK and unique-key lookups; L1 is at most 1 row per sitemap (measured max 1) |
| FTS with filters: optional `LEFT JOIN articles` on topic, `s.sources =`, `s.posted_at BETWEEN` | 0.6 s with a topic + date filter, 0.13 s unfiltered |
| Site stats: `articles JOIN sitemaps GROUP BY sources` + `MAX(finished_at)` of article crawls | 0.28 s; cached 10 min |

## New writes
- **`api_usage_log`:** one upsert per answered question under `web:<model>`, with tokens and `cost_usd`. Existing columns (SYS-39). The key prefix keeps the page out of the extraction's budget row.

## Notes
- **Dates:** `crawl_log.started_at` / `finished_at` are the container's UTC `NOW()`; the hero adds 7 h for WIB. `api_usage_log.log_date` is UTC `CURRENT_DATE`, so the page's daily cap resets at 07:00 WIB.
- **No index is added.** The filtered FTS cost is dominated by the GIN match; revisit if SYS-103 widens the query to OR terms (more matches to rank).
