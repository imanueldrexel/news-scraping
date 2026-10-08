# ADR-007: Search candidates are scored on both signals, on one cosine scale; recency follows the question's cue; a follow-up is retrieved with its thread

**Status:** Accepted 2026-10-08 (SDE, fixing QA's findings of 2026-10-07; measured on the replay, owner informed with the evidence)
**Date:** 2026-10-08
**Feature:** rag-retrieval-quality (SYS-104 #274, SYS-105 #275, SYS-106 #276, SYS-107 #277, SYS-108 #278, SYS-110 #284)
**Amends:** ADR-006 decision 4 (the re-rank) and ADR-005's retrieval step.

## Context
QA's independent pass (2026-10-07) measured the page's retrieval, not its UI:
- **Keyword-only finds never reached the reader.** 0 of 95 top-5 cards were keyword-only.
  - The re-rank was `0.6·semantic + 0.3·keyword + 0.1·recency`, with a missing score counted as 0. A keyword-only hit scored at most 0.40.
- **One-word sign-off chunks were semantic hubs.** "(jon)", "--" filled "Apa itu Danantara?" 5/5, and gibberish got 3 cards.
- **"Berapa harga emas Antam hari ini?" answered with the 1 Oct price.** Candidates were the 20 most similar paragraphs of the whole corpus, whatever their date.
- **A follow-up was retrieved on its own words.** "Berapa target pertumbuhannya tahun depan?" after an OJK credit question returned GDP 2027.

While fixing these, two further facts surfaced (both ticketed):
- **SYS-110 (#284).** `search_l2` read FAISS's squared L2 distance as a distance (`1 - d²/2`). Its `semantic_score` was not the cosine: cos 0.82 read 0.93 and cos 0.29 read 0. A keyword-only paragraph's real cosine could not be compared with it.
- **SYS-109 (#283), not fixed here.** MiniLM embeds only the first 128 tokens (~97 words) of a 450-word chunk.

## Decision
1. **Score every candidate on both signals.**
   - A keyword-only article's paragraph gets its cosine to the question. The vector is its stored NEWS_L2 one (`chunks.embedding_id`), embedded only when missing; re-embedding cost 250-500 ms a question.
   - A FAISS-only article's paragraph gets its IDF-weighted coverage, from the same `to_tsvector('simple', …)` that `chunks.fts_vector` stores. One SQL round trip over the texts.
   - `semantic_score` is the cosine everywhere (`1 - d/2`).
   - `RAG_MIN_SEMANTIC_SCORE` 0.60 → 0.55: the same FAISS pass set on the new scale.
   - The weighted sum and the floor are otherwise ADR-006's.
2. **No fragment is a candidate.**
   - A matched paragraph under 15 words is skipped, from either retriever.
   - The chunker merges a short last paragraph backward.
   - Stored fragments are re-chunked by `scripts/rechunk_stale_chunks.py`. That is an owner-approved production write; the entity mentions are kept.
3. **Recency follows the question.**
   - A cue sets a horizon (recency halves there) and a weight:
     - "hari ini / sekarang / saat ini / kini" → 1 day, 0.3;
     - "pekan ini / minggu ini / sepekan terakhir" → 3 days, 0.2;
     - "terbaru / terkini" → 7 days, 0.1.
   - Recency counts only for an article relevant by meaning (semantic ≥ the floor).
   - Under a cue, the keyword half orders the paragraphs that hold every word newest first. Otherwise it keeps `ts_rank_cd`, as ADR-006 measured.
   - Without a cue, recency is ADR-006's slow fade.
   - FAISS over-fetches 100 paragraphs without a filter (was 20).
4. **A follow-up is retrieved with its thread.**
   - The follow-up's words come first, then the session's last two questions, for both retrievers.
   - The session keeps every question asked apart from the answered turns. The prompt still gets the answered turns only (SYS-97).
   - The search box retrieves on its own text.
5. **A document frequency of 0 is not cached.** A new name is found as soon as its articles are crawled.

## Alternatives Considered
| Alternative | Why not (measured, EXPERIMENTS.md 2026-10-08) |
|---|---|
| Reciprocal rank fusion | Loses the absolute floor that turns an off-topic question into `no_hits`; QA's gibberish case needs it |
| Semantic of a keyword-only hit = its headline's cosine, or the window around the matched word | Neither separated relevant from off-topic better than the paragraph (Menkeu: rice-aid story headline 0.26 vs paragraph 0.52; gold today: 0.61-0.69 vs 0.61-0.62); costs an embedding per candidate |
| One recency weight (0.3) for every cue | On the cosine scale it put today's market outlooks above the BI decision for "...suku bunga terbaru?" |
| Multiplicative recency (relevance × (1 + 0.3·recency)) | The 1 Oct gold price stayed first |
| Recency for every hit over the floor | "Siapa Menteri Keuangan sekarang?" ranked a rice-aid story (semantic 0.52, coverage 1.0 on two common words) first |
| A follow-up's own words choose the keyword anchors, the thread's only weigh | No measurable gain on 7 pairs; two lost co-found articles |
| Rewrite the follow-up with one model call | A model call before the cards (~1-3 s); option 1 met the Done-when on 5/7 pairs, 2 mixed |

## Consequences
### Positive
- On the replay plus QA's questions:
  - keyword-only cards 0 → 59 of 160;
  - fragment cards 14 → 0;
  - "Apa itu Danantara?" gives 5 Danantara articles; gibberish gives `no_hits`;
  - the gold question cites 7-8 Oct;
  - the BI decision stays in the top 5;
  - 5 of 7 elliptical follow-ups are on topic (2 were off topic before).
- Latency, measured on a second :8765 instance (16-question replay, run twice):
  - warm retrieval is 62-625 ms, and 1.1 s for the follow-up with the longest combined text;
  - cold first touches reach 2.1 s;
  - before, warm was 108-358 ms and cold up to 1.3 s (SYS-103).
  - The cards still render before the answer (ADR-005).

### Negative
- One more SQL round trip per question (coverage, 24-85 ms for ~100 texts).
- The cue table is a judgment (three weights), measured on 12 recency questions.
- A follow-up that changes subject still carries the old one, for up to two turns or until "Pertanyaan baru".

### Risks
- **SYS-109.** The cosine of a long paragraph sees only its first ~97 words, so a keyword-only paragraph naming the subject late scores low. Coverage carries it (Danantara: cosine 0.18-0.29, coverage 1.0).
- **Unknown names.** "Purbaya" is 3/5 on topic: MiniLM does not know the name, and FAISS fills two slots with weakly related paragraphs. No stemming (ADR-006) either.

## Dependencies
- `chunks.embedding_id` points at the NEWS_L2 docstore id (SYS-17 / DBT-10).
- One encoder revision for index and query (SYS-61).
- ADR-005 (two-step turns, sessions in one worker) and ADR-006 (keyword half).
