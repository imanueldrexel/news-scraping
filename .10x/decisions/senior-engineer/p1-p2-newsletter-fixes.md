# p1-p2-newsletter-fixes — senior engineer

### 2026-10-04 — Approach
- OPS-20/SYS-68: new summarizer module, generator takes a summarizer (default built from config), `SummaryStats`, footer + `_summaries`, ERROR + crawl_log note below `NEWSLETTER_MIN_SUMMARY_SHARE`.
- SYS-67: read-only sweep script in scripts/experiments before choosing; merge pass as a pure function so it is unit-testable.
- SYS-63: pure `clean_body_paragraphs`, applied in `_get_news_details` after both extractor paths.
