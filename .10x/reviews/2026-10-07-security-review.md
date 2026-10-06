# Security review: RAG search redesign (tracker #272), 2026-10-07

**Scope:** `newscrawler/web/` (app, answer, filters, query_processor, turn_store, site_stats, templates, static), `core/web_copy.py`, `core/summarizer.complete`. **Reviewer:** 10x-Team (Security), in the dev session; QA verifies independently.

## Threat model
| Asset | Threat | Source of the threat |
|---|---|---|
| The reader's browser | Script injection (XSS) | Scraped article text, headlines and links (third-party pages); the model's answer, built from that text |
| SumoPod balance | Cost exhaustion | Anyone who can reach the page (it has no auth) |
| Postgres | SQL injection | Filter values and questions from the browser |
| Answer integrity | Prompt injection in an article; invented numbers | Scraped text; the model |
| Conversation privacy | Reading someone else's thread | Guessable session or turn ids |

## Findings and controls
| # | Area | Status | Control / evidence |
|---|---|---|---|
| S1 | Answer XSS (SYS-93) | **Fixed** | The answer is parsed into segments and autoescaped. No template contains `| safe`, `Markup(` or `autoescape false` (test). `<img onerror>` and `<b>` render as text (test). Mutant `sys93_answer_text_unescaped` is killed. |
| S2 | Citation links | **Fixed** | The `href` is `#src-{turn_id}-{n}`: the turn id is hex from uuid4, and n is checked against the card count. A model-written `[9]` stays text (test). |
| S3 | Scraped link scheme | **Fixed** | `safe_link` keeps http(s) only, so a `javascript:` sitemap link renders no `href` (test, mutant `sys93_any_link_scheme`). Cards open with `rel="noopener noreferrer"`. |
| S4 | Scraped headline/snippet | OK | Autoescaped (test with `<b>` in a headline; mutant `sys93_title_unescaped`). |
| S5 | SQL | OK | Filter values are checked against closed sets (topics from `filter_rubric`, outlets from `OUTLET_NAMES`, ISO dates). The SQL is built from fixed fragments with bind parameters only; a test asserts that values never appear in the SQL text. |
| S6 | Cost exhaustion | **Mitigated** | `RAG_DAILY_COST_LIMIT_USD` ($1/day) under the page's own key `web:<model>`; questions are at most 500 chars; there is no model call without relevant articles. A burst still spends up to the cap each day. |
| S7 | No auth / CSRF | **Accepted, local-only** | uvicorn binds 127.0.0.1 by default. Running with `--host 0.0.0.0`, or sharing the page, needs auth plus a per-client rate limit first (see below). SYS-93's P2 rating already depends on this. |
| S8 | Prompt injection via articles | **Accepted, mitigated** | The model's output is untrusted text (S1/S2). An article can still steer the wording. The reader sees the cards, the disclosure "Disusun AI … bisa keliru", and the number warning (`unverified_number`). The model has no tools and no data beyond the prompt. |
| S9 | Session / turn ids | OK for local | Session: uuid4. Turn: 48 random bits. Both live in memory with a TTL (30 min / 15 min). Knowing an id reveals a question and its answer, and nothing else. |
| S10 | Third-party scripts | **Fixed** | htmx 1.9.12 is vendored in `static/` (0BSD license, sha256 `449317ad…a452`), so no script comes from a CDN at runtime (test, mutant `sys102_htmx_from_cdn`). |
| S11 | Privacy: web fonts | Accepted | Google Fonts CSS is requested on page load: the reader's IP reaches Google. The page renders with the fallback stack when offline. To remove the request, self-host the two families. |
| S12 | Secrets in output | OK | Provider exceptions go to the log only (SYS-94). The page never renders exception text (test with a `429 RESOURCE_EXHAUSTED` message). Keys are never logged. |

## Required before the page is shared beyond localhost
1. Authentication (or an allow-list reverse proxy).
2. A per-client rate limit on `/api/query*` and `/api/answer/*`.
3. Keep `RAG_DAILY_COST_LIMIT_USD` at or under the owner's tolerance.
4. Self-host fonts if outside parties will read it.

**Verdict:** sign-off for local use. No open high or critical finding.
