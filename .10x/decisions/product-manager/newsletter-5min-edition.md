# Newsletter 5-minute edition (PM, 2026-10-05)

Tracker: #244. Tickets: SYS-80 #236, SYS-81 #237, OPS-41 #238, SYS-82 #239, SYS-83 #240, SYS-84 #241, OPS-42 #242, OPS-43 #243.

## Problem
The newsletter is meant to be a ~5-minute phone read. The 2026-10-04 digest is 23 A4 pages, 90 stories, ~12,000 words (headlines + bullets 7,897 words, ~40 min at 200 wpm; the source/link lines are another 3,963 words). No "what matters today"; every story has equal weight; 9.5pt A4 is ~6pt on a phone; footer is pipeline telemetry; internal source names; English dates. Evidence: design critique 2026-10-05 (rendered pages 1, 6, 23), EXPERIMENTS.md "2026-10-05 — newsletter reading length".

## Target user
The owner today, reading on the phone in Telegram at the 12:00 delivery. Designed for a wider audience later (owner decision), so the edition must stand alone: AI disclosure, brand names, fact checks.

## Owner decisions (2026-10-05, AskUserQuestion)
- Audience: wider audience later.
- Full 90-story digest: kept as a second file (archive), not sent.
- Top stories: finance-first, max 2 per section, at least 2 non-finance when important.
- Delivery: Telegram message (60-second block) + phone PDF.

## Approaches considered
- **MVP:** new prompt + word budget + Telegram text only, no PDF work. Cheap, but there is no readable full 5 minutes on a phone. Rejected.
- **Recommended (chosen):** the 8 tickets: structured summary with guards, editor pass, copy, phone PDF, Telegram message + PDF.
- **Full vision (later):** subscribers, email/web archive, personalisation, read analytics, brand. Deferred until the edition meets its success criteria.

## Scope / priority
- P0 (the edition cannot exist without): SYS-82, SYS-83, SYS-80 (bug, fixed through SYS-82).
- P1: SYS-84 (copy), OPS-42 (phone PDF), OPS-43 (Telegram), SYS-81 (bug).
- P2: OPS-41 (bug, page breaks; small).
- Build order: SYS-81, OPS-41, SYS-82 (+SYS-80) → SYS-84 → SYS-83 → OPS-42 → OPS-43.

## User stories
- As a reader on my phone, I want the day's 3-5 essentials in the Telegram message, so I know what matters without opening anything.
- As a reader, I want 6-8 top stories with one sentence, at most two facts and why it matters, so I can finish in 5 minutes.
- As a reader, I want to trust the numbers, so every figure must come from the articles and the summaries say they are AI-written.
- As the owner, I want the full digest kept, so depth is there when I need it.

## Success criteria
1. Edition ≤ 1,200 words, every day.
2. Owner reads it end to end on the phone in ≤ 5 min (3 editions).
3. No number outside its articles; ≤ 1 factual error in all Berita Utama across 3 hand-checked editions.
4. ≥ 5 of the day's 6 largest events (by portal count) in Berita Utama or Sekilas.
5. 7/7 days delivered; ≥ 95% LLM summaries (not fallback).
6. LLM calls per day no higher than today (~90 + ~12 + 1 editor).

## Not building
Subscriber lists, email/web delivery, personalisation, analytics, images/charts, rebrand, clustering changes (SYS-40/65/67 stand).

## Risks
Flash model ignoring limits or inventing numbers (guards + fallback, reported); number guard false rejects (verbatim-number rule, measured in replay); bad editor picks (deterministic fallback + coverage metric); a public factual error once shared wider (disclosure, guard, hand-check before sharing).
