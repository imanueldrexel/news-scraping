# ADR-010: A follow-up is rewritten into a standalone question by one LLM call before retrieval; a deterministic rule is the fallback

**Status:** Accepted 2026-10-12 (owner, as CTO/PM, chose the rewrite over a rule-only gate and over merging two retrievals)
**Date:** 2026-10-12
**Feature:** qa-senior-fixes-2026-10-12 (SYS-104 #274, SYS-140 #322)
**Supersedes:** ADR-007 decision 4 ("a follow-up is retrieved with its thread"). ADR-007's other decisions stand.

## Context
- ADR-007 retrieved a follow-up on its own words followed by the last two questions of the thread.
- That fixed elliptical follow-ups (5/7 on topic). QA then measured follow-ups that change subject, and these broke: 5/5 topic switches gave 0-1 of 5 on-topic cards (`probe_topic_switch_followups.py`). An example is "Apa itu Danantara?" after an OJK credit question.
- The joined thread also leaked the old question's recency cue.
- It turned the first word of each earlier question into a required "name" anchor (SYS-140: `kebijakan`, df 4.8%).
- ADR-007 rejected a rewrite call for its latency (~1-3 s before the cards). The owner now prefers correctness of the follow-up over that latency.

## Decision
1. **Only a follow-up is rewritten.** A follow-up is a turn whose session already holds at least one question. The search box and the first turn are retrieved on their own text, with no call, as today.
2. **One call, one line out.** `newscrawler/web/followup.py` builds a short Indonesian prompt from the last `FOLLOWUP_CONTEXT_TURNS` (2) questions and the follow-up. It asks for **one standalone question**, under these rules:
   - Resolve references (`-nya`, *dia*, *itu*, *tersebut*) from the thread.
   - Return the follow-up unchanged when it already names its own subject or changes subject.
   - Never carry a time expression ("hari ini", "pekan ini") into a question about a new subject.
3. **The rewrite is checked before it is used.** It must be one line, non-empty, at most `REWRITE_MAX_CHARS` (300), and must not be a refusal or a list. The checks strip quotes and a leading "Pertanyaan:". A rewrite that fails them is not used.
4. **What the rewrite feeds.**
   - Both retrievers, the coverage and the semantic scores all use the rewritten question, exactly as a search-box question.
   - The recency cue is taken from the rewritten question. The answer prompt still gets the reader's own follow-up plus the answered turns (SYS-97). The model sees what the reader typed.
5. **Fallback, with no call or a failed one.** The fallback covers no provider, the page's daily dollar cap (`RAG_DAILY_COST_LIMIT_USD`), a quota, a timeout (`RAG_REWRITE_TIMEOUT_S`, default 6 s), an error, or an output that fails the checks. It is deterministic:
   - **The follow-up refers back** (a word ending in `-nya`, or *dia / mereka / beliau / tersebut / itu* used as a reference):
     - retrieve on its own words plus the thread, with keyword terms taken **per question** (SYS-140);
     - the recency cue comes from the follow-up's own words only.
   - **Otherwise:** retrieve on its own words alone.
6. **No waiting on a rate limit.** The rewrite's summarizer never sleeps on a 429. The page falls back instead of holding the cards for up to `RATE_LIMIT_MAX_WAIT_S`.
7. **Accounting.** The call is counted under `web:<model>` with tokens and dollars, like the answer (ADR-005), and against the same daily cap.
8. **Observability.** `rag retrieve` logs `rewrite=llm|kept|fallback-thread|fallback-own`, the rewrite's ms, and the rewritten text.

## Alternatives Considered
| Alternative | Pros | Cons | Why not |
|---|---|---|---|
| Rule-only gate (reference marker / weak own retrieval) | Free, deterministic, no latency | "Bagaimana tanggapan buruh?" (elliptical, no marker) vs "Di mana terjadi banjir minggu ini?" (new subject, no marker): the structure can't tell them apart | Owner chose the rewrite; the rule is kept as the fallback |
| Retrieve both ways and merge | No call | A topic switch gets about half old-topic cards; fails QA's ≥ 4/5 | Fails the Done-when |
| Keep ADR-007's joined thread, fix SYS-140 only | Smallest change | Topic switches still 0/5 | Fails the Done-when |

## Consequences
### Positive
- A topic switch is retrieved on its own subject; an elliptical follow-up on its resolved subject.
- SYS-140 disappears on the main path: the keyword terms come from one well-formed question.
- The old recency cue cannot leak into a new subject; the rewrite carries a cue only when the follow-up continues the same event.

### Negative
- A follow-up's cards wait for one model call (~1-3 s measured on DeepSeek; at most `RAG_REWRITE_TIMEOUT_S`).
- Retrieval of follow-ups now depends on the SumoPod balance. When it is blocked, the fallback (item 5) is weaker on unmarked elliptical follow-ups.
- Cost: ~150 input + ~30 output tokens per follow-up, well under $0.0001 each.

### Risks
- **The model rewrites a self-contained question badly** (adds a subject that was not asked). Mitigation:
  - the prompt says to return such questions unchanged;
  - the measurement over 5 topic-switch + 7 elliptical pairs + held-out pairs is recorded in EXPERIMENTS.md;
  - the rewritten text is logged for QA.
- **Prompt injection through the follow-up.** The output is only a search string. It is bound as SQL parameters and embedded. It is never rendered or executed. Length is capped.

## Dependencies
- ADR-005 (shared Summarizer, two-step turns), ADR-006 (keyword half), ADR-007 decisions 1-3, 5.
- `RAG_LLM_PROVIDER` + the SumoPod key.
