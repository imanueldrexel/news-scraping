# Newsletter 5-minute edition (SDE, 2026-10-05)

Tracker #244. PM spec: `.10x/decisions/product-manager/newsletter-5min-edition.md`.
Tickets: SYS-80 #236, SYS-81 #237, OPS-41 #238, SYS-82 #239, SYS-83 #240, SYS-84 #241, OPS-42 #242, OPS-43 #243; found while building: SYS-85 #245.

## What was built (commit 654a81e + follow-ups)
| Module | Ticket | Role |
|---|---|---|
| `core/newsletter_copy.py` | SYS-81, SYS-84 | every reader string; `tanggal()`/`tanggal_pendek()` from explicit tables (never `strftime("%B")`); `OUTLET_NAMES` for every `WebsiteName` (+ retired KAPANLAGI/BATAMPOS/GRIDID); `SECTION_NAMES/TITLES/SHORT` (moved here from the generator; `ng.SECTION_TITLES` is the same object) |
| `core/story_summary.py` | SYS-82, SYS-80 | the ticket's prompt verbatim; `pick_articles` (one per outlet by authority, then the rest, max 6); `parse` = JSON shape/indexes ("json"), word limits ("length"), number guard ("number"); `summarize_story` = one retry with the reason |
| `core/newsletter_edition.py` | SYS-83 | candidates (top 3 per section), editor prompt verbatim, `parse_editor` (quotas), `deterministic` fallback, `render` with the 1,200-word budget, `briefing()` for Telegram |
| `core/newsletter_generator.py` | all | applies `terkait` (SYS-80), renders the digest in the new copy, writes the edition, `_edition` stats, `DigestPath.edition` |
| `core/newsletter_pdf.py` | OPS-41, OPS-42 | `parse()` -> blocks; `build_story` (A4 archive) and `build_edition_story` (phone); numbered-canvas footer `Rangkuman Berita · <tanggal_pendek> · n/N` |
| `scripts/run_scheduled_newsletter.py`, `scripts/notify_telegram.py` | OPS-43 | `_deliver`: message (`send_html`) then edition PDF; no edition -> notice + A4 digest PDF |

## Decisions the tickets left open (made here; QA/owner may revisit)
- **Which articles the summarizer sees:** up to 6, one per outlet first (was: top 3 by authority, same outlet possible -- which is how a TVONENEWS link nobody summarized reached the Sarmuji story). An article the model did not see stays in the cluster: it counts towards "Diberitakan N portal" but is never a link or the headline. Rationale: dropping unseen articles would turn the 11-portal Antam story into "3 portal".
- **Number guard:** digit runs with `.`/`,` removed must be in the shown articles' text (outlet + headline + l1[:800]; the prompt's own example and limits are excluded). A short date `d/m` passes when the articles have `d/m` literally or `d <Bulan>` (the prompt asks for "Jumat (2/10)", which an article may write out). Optional `poin`/`mengapa_penting`/`tidak_terkait` may be missing or null.
- **Refusal reasons:** json (unparseable, wrong types, bad/duplicate/missing indexes), length, number. A refusal is not an outage (does not count towards NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS).
- **Edition candidates:** only summarized stories reach the editor and Berita Utama. A fallback story can appear in Sekilas as its portal headline, and then the edition carries the degraded notice with that count (so "N berita hanya ditampilkan judulnya" is true of the document it is in).
- **Editor rules:** utama count `min(6, capacity)..8` where capacity is what the quotas allow (a thin day is not a refusal); non-finance requirement = `min(2, distinct non-finance events with >= 3 portals)`; overlapping duplicate groups are merged; 60-second count `min(3, len(utama))..5`. Reasons: json, rules, length, number, error, quota.
- **Deterministic fallback:** 6 stories; reserve the required non-finance by portal count, then finance, then the rest; shown in portal-count order.
- **Full-digest source line:** `**Diberitakan N portal:** Kontan · Investor.id · ...` plus the 3 `Artikel terkait` links with brand-name labels (the archive keeps depth; the one "Baca di" link is the edition's).
- **Edition footer** adds "Edisi lengkap memuat N berita." (the More line is removed from the edition, per SYS-84).
- **Telemetry:** `SummaryStats.footer()` renamed `describe()`: it is the operator's line (log, crawl_log note, DEGRADED Telegram line), never the reader's.
- **Edition failure:** any exception is caught, logged, recorded as `_edition: {"built": false, "reason": ...}`, appended to the note ("5-minute edition not built: ...") and a stale `-ringkas.md` of that date is removed. A day with no summarized story has no edition (same path).
- **Phone PDF title link** is in the text colour; the visible link is the "Baca di <Outlet> →" line (colour + arrow, not colour alone).
- **Telegram message and edition PDF are not queued in the outbox** (as OPS-40 decided for documents).

## Changes made from the replay (commits 5dacec7, a90067e, 81f7483)
- **Refusals name every broken limit** (with the text to shorten), not just the first.
- **On the retry, a poin still over 20 words (or past the 2nd) is dropped whole, never cut** (`_summaries.poin_dropped`). Not in the ticket: the ticket said a second refusal falls back to the headline list. Done because 133/133 v1 refusals were poin length and poin are optional ("Nol poin boleh").
- **Unsummarized stories are not in the edition** (v1 showed the Kapolri event twice: a top story and its unsummarized twin as a raw portal headline). The edition's notice reads "Sebagian ringkasan tidak tersedia hari ini; N berita hanya ada di edisi lengkap." (`DEGRADED_EDITION`, a wording variant of SYS-84's, true of the edition). Cost: 09-28's 15-portal BI-rate story was refused twice (judul 12 words) and so is missing from the edition.
- **Editor: more than 5 sixty-second sentences -> keep the first 5 whole** (`_edition.sixty_trimmed`). The prompt wording ("3-5 kalimat SAJA") did not change the model's one-per-story habit.
- **OPS-42 page (owner decision 2026-10-05, AskUserQuestion: "Taller page + allow splits"):** 105x228 mm (phone ~9:19.5); on the phone a story may continue on the next page after its title + first sentence; the Baca-di line stays with the line before it; Sekilas lines flow one by one. A4 archive unchanged (whole stories, OPS-41). OPS-42's Done-when "<= 6 pages" becomes "readable without zoom, no orphaned heading or link line" (real days: 7 pages).

## Replay result (v4, 81f7483) -- full table in EXPERIMENTS.md 2026-10-05
first try 62 / 59 / 46% (target 90, missed); after retry 96.7 / 100 / 92.7% (target 95, 2 of 3); edition 869 / 949 / 916 words; editor valid first try 3/3; coverage 6 / 6 / 4 (target 5, 2 of 3); phone 7 / 7 / 7 pages; document checks clean; number refusals 2 in 278 (one verified as the model rounding US$84.777,58).

## Open (owner / PM)
1. SYS-82 first-try >= 90% is not reachable with these limits on deepseek-v4-flash (it overshoots by 1-3 words); ~35-60 extra calls/day (~$0.01) breaks tracker criterion 6 ("calls no higher than today"). Options: accept; or a 12-word judul (most remaining fallbacks are judul 11-12).
2. SYS-83 duplicates: 09-28 showed the Trump/Iran proposal as a top story and as Sekilas; 10-03 had two angles of the police reshuffle. The editor's `duplikat` is conservative; no deterministic guard exists.
3. Finance-first is prompt-only: the editor picked 5 of 8 non-finance top stories on 10-04. No quota caps non-finance (the tickets set only a minimum of 2).
4. Coverage: a story ranked 4th in a crowded section (09-28 IHSG, 14 portals) is never a candidate (top 3 per section by size x sources, per SYS-83).

## Deviations / open
- `response_format=json_object` (optional in SYS-82) not sent: 0-1 json refusals per day made it unnecessary.

## QA's findings fixed (2026-10-05 night; commits 468b75d..41a3ab6)
QA report: `.10x/reviews/2026-10-05-qa-report.md`. Evidence and numbers: EXPERIMENTS.md "2026-10-05 (night) — SDE fixes of QA's tracker #244 findings".

| Ticket | What was built | Decision made here |
|---|---|---|
| SYS-86 #246 | `core/story_words.py`: one definition of content words and names (no titles, months, number units, digit tokens, currency prefixes, legal forms, single letters, roman numerals). `echoes()`: >= 2 shared event words (a name in neither text) + a name in both, or >= 4 event words. A Title Case judul marks no names. | A word that is a name in either text says who, not what (10-01's Wamenkeu/Kapolri wrong hide). Final rule: 1 wrong hide (09-25 dana pensiun) on 5 untuned days, at the Done-when limit; not tuned further. |
| SYS-80 #236 | `story_summary.off_subject`: every `terkait` article must name a summary name, or share >= 2 judul words. First answer: refused (`subject`). Retry: a stray is demoted to `tidak_terkait` (`_summaries.strays_demoted`). Number guard reads only the `terkait` text; so does the edition's 60-second guard. | The first version refused on both tries: 13 lost stories on 6 days (09-28 at 92.7%). Demotion trades a portal for a story, never the summary. |
| SYS-87 #247 | `values()`: Indonesian notation first, English where Indonesian cannot read it or both can; `guard_text` without the outlet name. | "1.500" is 1500 only; "1,500" is 1,5 or 1500. A digit glued to letters (Liputan6.com in the body) still counts: a residual, not fixed. |
| OPS-44 #248 | A PDF the message promised and that does not arrive is followed by "PDF tidak tersedia hari ini." | Follow-up message, not a reorder (keeps OPS-43's order). Also covers the full digest's render failing after its message (same defect). |
| SYS-88 #249 | `utils.unescape_headline` at `_get_sitemap`, `_get_page_title`, and the newsletter's read path; `scripts/unescape_stored_headlines.py` (dry run: 2,410 rows). | Backfill **not applied**: needs the owner's approval for the production write. |
| DBT-56/57/58 | The tests QA's mutants asked for. | — |
| DBT-59 #254 (found here) | The "unseen article counts as a portal" test patched `MAX_ARTICLES`, which `pick_articles` binds as a default argument; it passed on the fallback. Fixed. | — |

Mutants: 112 newsletter mutants in `qa_mutation_runner.py` (re-pointed where code moved). Tooling: `replay_newsletter_edition.py` writes `<date>-stories.json`; `check_story_subjects.py`, `probe_echo_guard.py` re-measure offline.

**The replay round was cut short when the SumoPod prepaid balance ran out (~23:00 2026-10-05; owner: not topped up).** That account also serves the 21:00 extraction (stopped at 6,081/6,090) and the 12:00 newsletter. Valid v7 days: 10-03, 10-04 only; the after-retry share with the final SYS-80 code is measured on those two (100%, 98.9%).

## Tech debt
- `notify_telegram.send_html` duplicates `send_document`'s retry loop (kept separate so the OPS-40 mutants' patterns stay valid).
- `newsletter_pdf.build_edition_story` recognises the 60-second box and the lead story by the copy strings (`SIXTY_SECONDS`, `TOP_STORIES`): a wording change in newsletter_copy moves both together, but a hand-written edition with other headings renders as plain bands.
