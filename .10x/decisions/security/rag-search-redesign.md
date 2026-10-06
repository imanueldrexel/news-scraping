# RAG search redesign: security (2026-10-07)

Full review: `.10x/reviews/2026-10-07-security-review.md`.

## Decisions
- **Model and scraped text are untrusted.** They are rendered as escaped segments. Citation `href`s are built from ids, and links are http(s) only.
- **Spend is bounded per day** under the page's own `web:<model>` key.
- **The page stays local-only.** Before sharing: auth, a rate limit, self-hosted fonts.

## Verdict
Sign-off for local use; no open high or critical finding.
