# ADR-005: RAG answers through the shared Summarizer on DeepSeek, as explicit answer states, in two-step turns

**Status:** Accepted 2026-10-07 (owner chose DeepSeek via SumoPod for SYS-98)
**Date:** 2026-10-07
**Feature:** rag-search-redesign
**Author:** 10x-Team (Architect + Staff Engineer)

## Context
`web/query_processor.py` calls `google.genai` directly with `GEMINI_MODEL`. The free tier gives this project 20 requests/day/model (OPS-20), so the search answer stops early every day. Failures come back as answer text, either the raw exception or an English developer note (SYS-94). The newsletter and the extraction already run on configurable providers with typed failures (`core/summarizer.py`: `QuotaExhausted`, `SummarizerError`; ADR-001, ADR-003). The extraction also records tokens and dollars in `api_usage_log` and enforces a daily dollar budget per model key (`deepseek-v4-flash`).

The redesign (tracker #272) also needs:
- the sources visible before the answer;
- an honest two-step loading message ("Mencari artikel…", then "Menyusun jawaban dari n artikel…");
- `[n]` citations that link to source cards (SYS-99);
- a conversation thread (SYS-97).

## Decision
1. **Provider:** the answer step depends on the `Summarizer` protocol. `RAG_LLM_PROVIDER` selects it: `openai` (default, the owner's decision 2026-10-07: DeepSeek on SumoPod) or `gemini`. A forced provider without its key means no answers (state `unavailable`); it never falls back to the other provider. `build_summarizer` takes the provider and the variable's name for its error.
2. **Usage and cost:**
   - `Summarizer.complete(prompt) -> Reply(text, input_tokens, output_tokens)` is added. It makes the call but does not count it. `summarize()` keeps its contract, so the newsletter is unchanged.
   - The web counts each answered call in `api_usage_log` under its own key, `web:<model>`, with tokens and dollars (`peak_hours.cost_usd` for a priced provider, 0 for Gemini). The search page therefore never spends the extraction's `KNOWLEDGE_DAILY_COST_LIMIT_USD`, which is read from the bare model key.
   - The new `RAG_DAILY_COST_LIMIT_USD` (default $1.00, about 1,000 answers) caps the page's own spend. When it is reached, the state is `unavailable`.
3. **Answer states, not answer text:** `QueryProcessor.answer()` returns one of:
   - `ok`;
   - `unavailable`: no summarizer, `QuotaExhausted`, or the day's cap reached;
   - `failed`: `SummarizerError`, an empty reply, or any other exception;
   - `no_hits`: no relevant article, and no model call is made.

   The exception goes to the log only. The page renders each state's copy from one table (`core/web_copy.py`).
4. **The answer is data, never markup:**
   - The model's text is cleaned of Markdown, then parsed into blocks of segments: text, or a citation `n`.
   - A citation is rendered as a link only when 1 <= n <= the number of cards. The `href` is built from the turn id and n, never from model text.
   - Templates never use `| safe` (SYS-93). A source link is rendered as `href` only when it is http(s).
5. **Two-step turns:**
   - `POST /api/query/form` retrieves and renders the turn: the question, the source cards, and an answer placeholder. The placeholder then calls `POST /api/answer/{turn_id}` itself (htmx `hx-trigger="load"`).
   - Retrieved turns wait in an in-memory `TurnStore` (TTL 15 min, at most 500 turns).
   - A failed answer keeps its turn, so "Coba lagi" re-posts the same turn id.
   - Only an `ok` answer, with its `[n]` markers removed, is written to the session history.
   - The JSON `POST /api/query` stays a single call (retrieve + answer).
6. **Filters run on database truth:**
   - Every merged hit gets its headline, link, source, `posted_at` and `articles.topic` from one SQL query by `sitemap_id`, before filtering. FAISS metadata is no longer trusted for display or filtering (SYS-91 dates).
   - The FTS query applies the topic, portal and date filters in SQL.
   - FAISS over-fetches (`RAG_FILTERED_K`, default 200) when a filter is active.
7. **Conversation:**
   - The main search box always starts a new session: no `session_id` field.
   - The follow-up form appends to the thread and carries the session id, which the response sets out-of-band.
   - "Pertanyaan baru" clears the thread on the client.
8. **Start-up warm-up:** the app's lifespan starts a background thread that builds the processor (embedding model + FAISS) and runs one search, so the first question is not the slow one (`RAG_WARM_AT_STARTUP`, default on).

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Keep calling `google.genai` directly | No change | 20 answers/day; no typed failures | The defect itself (SYS-98) |
| Reuse `ExtractionProvider` (it already returns tokens) | Tokens without a protocol change | Forces JSON mode and temperature 0; it is the extractor's contract | The answer is prose; the ticket names the shared Summarizer |
| Count RAG usage under the bare model key | One row per model | Eats the extraction's daily dollar budget; mixes two products' spend | A separate `web:` key costs nothing |
| One request (retrieve + answer) and a timed fake second loading line | Simpler server | The second line would lie about progress; the sources stay hidden until the model ends | Two requests show the sources at once and the true step |
| Stream the answer (SSE) | Fastest perceived answer | The number check and citation parsing need the whole text; more moving parts | Not needed at ~3-8 s per answer |
| Keep filtering on FAISS metadata | No extra query | Stale or wrong dates (SYS-91); no `articles.topic` | One indexed query by primary key over <= 220 ids |

## Consequences

### Positive
- The answer is available every day. A provider failure degrades to "articles only" with clear copy.
- The spend is visible per day under `web:<model>` and bounded by its own cap.
- The answer can no longer inject markup, and citations always point at a visible card.
- Sources appear as soon as retrieval ends; the answer follows.

### Negative
- Two HTTP requests per question. A server restart between them loses the turn: the page then shows the "expired" copy and asks the reader to resubmit.
- One more metadata query per question: about 10-50 ms by primary key. A topic-filtered FTS is 0.6 s against 0.13 s unfiltered (measured 2026-10-07).
- `RAG_LLM_PROVIDER`, `RAG_DAILY_COST_LIMIT_USD`, `RAG_FILTERED_K` and `RAG_WARM_AT_STARTUP` are four more variables to document.

### Risks
- **The page is unauthenticated.** Anyone who can reach it can spend up to the daily cap. That is acceptable while it is local-only; sharing it needs auth and a rate limit first (security review).
- **The in-memory `TurnStore` and sessions** assume one worker process. Running uvicorn with `--workers > 1` would split them, so the runbook says one worker.
- **Number check false positives:** a number written differently from the source shows the warning line, which is the safe direction.

## Dependencies
- `core/summarizer.py` (ADR-001) gains `complete()` and `Reply`.
- `core/peak_hours.cost_usd` and the `KNOWLEDGE_PRICE_*` variables price the calls; both products run on the same SumoPod key and price list.
- `api_usage_log` columns from SYS-39; no schema change.
- Constrains: any future second worker process or shared deployment must move `TurnStore`/`SessionManager` to a shared store.
