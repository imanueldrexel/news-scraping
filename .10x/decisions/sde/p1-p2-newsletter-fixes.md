# p1-p2-newsletter-fixes — SDE

### 2026-10-04 — What was built (dev, branch dev)
- **OPS-20 #136 / SYS-68 #216** (7dd67a1): `core/summarizer.py` (OpenAI-compatible + Gemini, `QuotaExhausted`, counted after the answer); `NewsletterGenerator` takes a summarizer, counts summarized/total, stops on a quota 429 or N consecutive errors, writes the footer, `categories._summaries` and a `crawl_log` note (the `DigestPath` str subclass carries `.note`). `GEMINI_DAILY_CALL_LIMIT` (20) separated from `DAILY_API_CALL_LIMIT`; the extractor warns once per run on a quota 429. ADR-001.
- **SYS-63 #204** (54beb4b, 4c19429): `clean_body_paragraphs` in `core/utils/utils.py`, applied in the base `Crawler` to the site selector, trafilatura and newspaper output; paragraphs with nothing to remove are returned byte-identical; call-to-action pattern widened after the replay (`scripts/experiments/replay_clean_body.py`).
- **SYS-67 #215** (4c19429): `core/story_grouping.py`, one grouping call per section, cap of 2 slots per story. ADR-002.
- Tools: `scripts/preview_newsletter.py` (no DB writes), `scripts/experiments/replay_clean_body.py`.

### Deviations from the spec
- SYS-67: the planned token merge pass and distance sweep were tried and failed (EXPERIMENTS.md); replaced by the summarizer grouping. Contamination is not detected or split. The Done-when "<= 1 contaminated cluster per day" is not asserted.
- SRC-56 and SRC-03 left open (owner decisions, Cloudflare).

### Tech debt created
- `categories` JSON holds a non-topic key `_summaries`; consumers must skip `_` keys (none exist today).
- Summaries are serial (about 2.3 s each); parallelising would cut a digest from 4.5 min to under 1.
- A mixed cluster's "Sumber (N portal)" and links can include a stray article.

### Tests
Unit 1788+ passed, integration 156 passed; 59 new mutants registered and killed (19 + 15 + 20 + 2 re-runs, plus 2 stale ones retargeted).

### 2026-10-04 (later) — QA feedback fixed (SYS-71, SYS-72, DBT-51, DBT-52)
Prioritization: followed QA's handoff and the EM sequence (blocking P2 first, then P3s); no new ordering question for the senior dev. Remaining P1/P2 are not code or need the owner (see Open).
- **SYS-71 #219** (2cf4f47): `call_guarded` in `core/summarizer.py` shared by both providers. Only a 429 that names a per-day quota is `QuotaExhausted`; any other waits `Retry-After`/`retryDelay` (default 5 s, cap 30 s), retries once, then a plain `SummarizerError`. Footer for that path is "layanan gagal berulang", never "harian".
- **SYS-72 #220** (a5f9001, 186acea): `_BOILERPLATE_LINE` keyed on shape (colon/bar after Baca/Lihat juga, `Lihat juga Video`, promo noun for the Google News ask, `Baca selengkapnya ... di sini|detik*|melalui tautan ini`); editor tag cut only after a sentence end/newline and never for a denylisted pair (`_NOT_INITIALS`). Replay: 17,791 stored lines removed before, 4 not removed now, 0 new. My first version dropped 81 real chrome lines; found by an old-vs-new line comparison, not by the per-source percentages.
- **DBT-51 #221** (ae58c86): test for `more` with unclustered articles.
- **DBT-52 #222** (02a4312): EOL-only normalising commit for the SRC-54 block (39 lines back to LF); the SYS-72 diff for utils.py is 47 lines.
- 11 mutants registered/retargeted, all KILLED (one SURVIVED first: `sys72_tail_needs_no_sentence_end`; test added). Unit 1,827 passed / 5 skipped, integration 156 passed.
- **Newsletter** (owner-approved run): `task=newsletter` with no date digests TODAY, not yesterday. It first wrote a partial-day digest for 2026-10-04 (236 articles, 27/27 summaries; `digests/2026-10-04.md` + a `newsletter_digests` row), then I ran 2026-10-03 through `init_crawler().crawler_service.generate_newsletter(date(2026,10,3))`: 2,052 articles, 320 clusters, 94/94 summaries, 12 groupings ok. The stray 2026-10-04 row is not deleted (waiting on the owner).

### Tech debt created
- `task=newsletter` cannot take a date from the event (CrawlerAPI calls `generate_newsletter()` with none); a date arg or a yesterday default belongs in OPS-38 #212.
- Unverified: a SumoPod daily-limit 429 body; if it has no day wording it degrades to the consecutive-error stop.
- The harness this session mangles backslash escapes in heredoc Python (`\b` -> backspace, `\n` -> newline); regex edits to `utils.py` go through the Edit tool.

### Open
- SYS-73 #223 (stored-row repair) is unblocked; next is the read-only dry run, then owner approval + backup.
- #136 OPS-20 not labelled: its Done-when needs the owner's provider choice and extraction still runs on Gemini.
- #204 waits for tonight's 19:00 run (first run of the final cleaner).
