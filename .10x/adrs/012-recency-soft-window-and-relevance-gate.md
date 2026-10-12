# ADR-012: "This week" questions prefer the last 7 days (a soft window); a relevance gate for freshness was measured and rejected

**Status:** Accepted 2026-10-12. The owner chose the shape (as CTO/PM); after the measurement the owner chose "week window only".
**Date:** 2026-10-12
**Feature:** qa-senior-fixes-2026-10-12 (SYS-138 #317; SYS-112 #289 measured, not fixed here)
**Supersedes:** ADR-007 decision 3 for the week cue only. Its weights, its other cues and the keyword half's newest-first rule stay.

## Context
- **SYS-138.** "pekan ini / minggu ini" from the search box (no date filter) gets 2-10-week-old articles. A weight of 0.2 with a 3-day horizon gives a 4-day-old article only 0.064 over a 24-day-old one, less than a small semantic gap. The week's articles exist (141 KPK, 359 IHSG).
- **SYS-112.** "Siapa Menteri Keuangan sekarang?" and "Apa keputusan BI terbaru soal suku bunga?" lead with off-topic cards. The ticket's working theory was that same-day passing mentions win through the "sekarang" weight.

## Decision
1. **Soft window for the week cue.** `keywords.RecencyCue` gains `window`, and "pekan ini / minggu ini / sepekan terakhir" gets 7 days. A question with that cue and no date filter of the reader's is retrieved under `Filters(days=7)`, the same path as the reader's own range chip.
   - When at least `RAG_TOP_K` of the window's articles pass the floor, those are the result.
   - Otherwise they come first, and the unwindowed ranking fills the rest.
   - The rewrite and the keyword query run once; only the two retrievals repeat.
   - A reader's own date filter wins. The log reads `window=7d`, or `window=7d+N` when it was filled.
2. **No relevance gate, and no window for "sekarang / hari ini / terbaru".**

## Measurement
Offline, from one candidate dump of 15 questions: `scripts/experiments/probe_recency_tuning.py`, production 2026-10-12 ~12:00 WIB, EXPERIMENTS.md.

| Setting | Week questions ≥ 3/5 this week | "now" top-3 on-topic (sum) | Questions losing on-topic cards |
|---|---|---|---|
| current | 3/4 (KPK 0/5) | 10 | — |
| **week window 7d** | **4/4 (KPK 5/5, IHSG 5/5)** | 10 | **0** |
| gate δ 0.10 | 2/4 | 10 | 2 (banjir, Antam) |
| gate δ 0.15 | 3/4 | 11 | 1 (banjir) |
| week 7d + now 7d + gate 0.10 | 4/4 | 11 (Menkeu 0→2/3, Iran 3→2/3) | 0 |
| week 7d + now 3d | 4/4 | 10 | 1 (Menkeu 2→0) |

Live, read-only on the replay after the change:
- KPK "minggu ini": cards 8-11 Oct (were 18 Sep-30 Jul);
- IHSG: 10-12 Oct;
- every other replay question unchanged (Danantara, gibberish 0 cards, Antam today, BI-Rate, Iran).

**SYS-112 is not a recency problem:**
- "Apa keputusan **BI** terbaru…" is 0/3 under every setting. Its decision stories score semantic 0.43-0.53, below the 0.55 floor, because MiniLM does not read "BI" as Bank Indonesia; the long-form question gets 3/3.
- Menkeu's top paragraph by cosine (0.81) is a 26-day-old Hanura piece. Only a "now" window plus a gate lifts it to 2/3, and that costs Iran a top-3 card.

## Alternatives Considered
| Alternative | Why not |
|---|---|
| Larger week weight only | To lift a 4-day-old article over a 24-day-old one 0.15 closer, the weight must be ≥ 0.5. That puts any same-week mention above the BI decision (ADR-007's measured failure). |
| Hard 7-day filter | A quiet topic would return nothing for "minggu ini" |
| Relative relevance gate (δ 0.10-0.20) | Measured above: regressions (banjir, Antam, Iran) and no Done-when met |
| Window for "sekarang" too | Tuned on one question (Menkeu); changes what "sekarang" means for every question |

## Consequences
- **Positive:** "this week" means this week when the week has answers. Nothing else changes.
- **Negative:** a thin week runs two retrievals (+~100-600 ms).
- **Open:** SYS-112's two real causes, abbreviations and old high-cosine passing mentions, are returned to QA/owner with this evidence.
